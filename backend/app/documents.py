import hashlib
import io
import json
from pathlib import Path
import re
import zipfile
import threading
from xml.etree import ElementTree

from .storage import now
from .provenance import annotate, metadata, invalidate


class DocumentError(ValueError):
    pass


MAX_BYTES = 25 * 1024 * 1024
MAX_TEXT = 2_000_000


def decode_text(content):
    for encoding in ["utf-8-sig", "gb18030"]:
        try:
            return content.decode(encoding)
        except UnicodeError:
            continue
    raise DocumentError("文本编码无法识别，请保存为 UTF-8 后导入")


def parse(content, suffix):
    warnings = []
    page_count = 0
    if suffix in [".txt", ".md", ".markdown"]:
        text = decode_text(content).replace("\r\n", "\n")
        units = [
            (None, f"第 {index + 1} 段", paragraph.strip())
            for index, paragraph in enumerate(re.split(r"\n\s*\n", text))
            if paragraph.strip()
        ]
    elif suffix == ".pdf":
        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(content))
            if reader.is_encrypted and not reader.decrypt(""):
                raise DocumentError("PDF 已加密，请先解除密码保护")
            if len(reader.pages) > 500:
                raise DocumentError("首版单个 PDF 最多 500 页，请分卷导入")
            page_count = len(reader.pages)
            units = []
            for number, page in enumerate(reader.pages, 1):
                text = (page.extract_text() or "").strip()
                if text:
                    units.append((number, f"第 {number} 页", text))
                else:
                    warnings.append(f"第 {number} 页无可提取文字，可能需要 OCR")
        except DocumentError:
            raise
        except Exception:
            raise DocumentError("PDF 解析失败，请检查文件是否损坏或受保护") from None
    elif suffix == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                info = archive.getinfo("word/document.xml")
                if info.file_size > 10 * 1024 * 1024:
                    raise DocumentError("DOCX 正文过大，请分卷导入")
                document = ElementTree.fromstring(archive.read(info))
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            # Only w:t contributes visible document text; XML properties are excluded.
            units = []
            body = document.find(".//w:body", ns)
            for block in body if body is not None else []:
                if block.tag.endswith("}tbl"):
                    rows = []
                    for row in block.findall("./w:tr", ns):
                        cells = [
                            "".join(t.text or "" for t in cell.findall(".//w:t", ns))
                            for cell in row.findall("./w:tc", ns)
                        ]
                        rows.append("| " + " | ".join(cells) + " |")
                    units.append((None, f"表格块 {len(units) + 1}", "\n".join(rows)))
                elif block.tag.endswith("}p"):
                    units.append(
                        (
                            None,
                            f"第 {len(units) + 1} 段",
                            "".join(t.text or "" for t in block.findall(".//w:t", ns)).strip(),
                        )
                    )
            warnings.append("DOCX 不含稳定页码，引用使用正文段落位置")
        except DocumentError:
            raise
        except (zipfile.BadZipFile, KeyError, ElementTree.ParseError):
            raise DocumentError("DOCX 解析失败，请检查文件格式") from None
    else:
        raise DocumentError("支持 PDF、DOCX、TXT 和 Markdown 文件")
    units = [(page, location, text) for page, location, text in units if text]
    if not units:
        raise DocumentError("文件没有可用文字；扫描 PDF 请先完成 OCR")
    if sum(len(text) for _, _, text in units) > MAX_TEXT:
        raise DocumentError("正文超过 200 万字，请分卷导入")
    return units, warnings, page_count


def split_chunks(document_id, units, size=800, overlap=100):
    chunks = []
    for page, location, text in units:
        start = 0
        while start < len(text):
            end = min(start + size, len(text))
            if end < len(text):
                candidates = [text.rfind(mark, start + size // 2, end) for mark in ["。", "！", "？", "\n"]]
                boundary = max(candidates)
                if boundary > start:
                    end = boundary + 1
            value = text[start:end]
            identifier = hashlib.sha256(f"{document_id}:{location}:{start}:{end}".encode()).hexdigest()[:32]
            chunks.append(
                {
                    "id": identifier,
                    "document_id": document_id,
                    "ordinal": len(chunks),
                    "page": page,
                    "location": location,
                    "start_offset": start,
                    "end_offset": end,
                    "text": value,
                }
            )
            if len(chunks) > 5000:
                raise DocumentError("片段数量超过 5000，请分卷导入")
            if end == len(text):
                break
            start = max(start + 1, end - overlap)
    return chunks


class DocumentStore:
    def __init__(self, db):
        self.db = db
        self.lock = threading.RLock()
        self.uploads = db.directory / "uploads"
        self.uploads.mkdir(exist_ok=True)

    def list(self):
        return [self._public(row) for row in self.db.rows("SELECT * FROM documents ORDER BY created_at DESC")]

    def _public(self, row):
        return {**row, "warnings": json.loads(row["warnings"]), **metadata(self.db, row["id"])}

    def get(self, identifier):
        rows = self.db.rows("SELECT * FROM documents WHERE id=?", (identifier,))
        if not rows:
            raise KeyError(identifier)
        document = self._public(rows[0])
        chunks = self.db.rows(
            """SELECT c.*,coalesce(cm.heading,'') AS heading,
            coalesce(cm.bbox,'[]') AS bbox,coalesce(cm.kind,'text') AS kind FROM chunks c
            LEFT JOIN chunk_meta cm ON cm.chunk_id=c.id WHERE document_id=? ORDER BY ordinal""",
            (identifier,),
        )
        return {
            **document,
            "chunks": [
                {
                    **c,
                    "title": document["title"],
                    "filename": document["filename"],
                    "source_metadata": document["metadata"],
                    "bbox": json.loads(c["bbox"]),
                }
                for c in chunks
            ],
        }

    def add(self, filename, content, title=None, parser="native"):
        with self.lock:
            return self._add(filename, content, title, parser)

    def _add(self, filename, content, title=None, parser="native"):
        if not content or len(content) > MAX_BYTES:
            raise DocumentError("文件为空或超过 25MB")
        filename = filename.replace("\\", "/").rsplit("/", 1)[-1][:200]
        suffix = Path(filename).suffix.lower()
        identifier = hashlib.sha256(suffix.encode() + b"\0" + content).hexdigest()
        existing = self.db.rows("SELECT * FROM documents WHERE id=?", (identifier,))
        if existing:
            return {**self._public(existing[0]), "duplicate": True}
        units, warnings, page_count, extras = self._parse(content, suffix, parser)
        return self._save(filename, content, title, units, warnings, page_count, extras, parser)

    def add_extracted(self, filename, content, units, warnings, pages, extras=None):
        with self.lock:
            suffix = Path(filename).suffix.lower()
            identifier = hashlib.sha256(suffix.encode() + b"\0" + content).hexdigest()
            if self.db.rows("SELECT id FROM documents WHERE id=?", (identifier,)):
                return {**self.get(identifier), "duplicate": True}
            return self._save(filename, content, None, units, warnings, pages, extras or {}, "automatic")

    def _save(self, filename, content, title, units, warnings, page_count, extras, parser):
        suffix = Path(filename).suffix.lower()
        identifier = hashlib.sha256(suffix.encode() + b"\0" + content).hexdigest()
        chunks = split_chunks(identifier, units)
        row = {
            "id": identifier,
            "title": (title or Path(filename).stem).strip()[:200] or "未命名资料",
            "filename": filename,
            "kind": suffix.lstrip("."),
            "created_at": now(),
            "pages": page_count,
            "chunk_count": len(chunks),
            "warnings": json.dumps(warnings, ensure_ascii=False),
        }
        path = self.uploads / (identifier + suffix)
        path.write_bytes(content)
        with self.db.connect() as connection:
            connection.execute(
                "INSERT INTO documents VALUES (:id,:title,:filename,:kind,:created_at,:pages,:chunk_count,:warnings)",
                row,
            )
            connection.executemany(
                "INSERT INTO chunks VALUES (:id,:document_id,:ordinal,:page,:location,:start_offset,:end_offset,:text)",
                chunks,
            )
        self._annotate(identifier, chunks, parser, extras)
        return {**self._public(row), "duplicate": False}

    def delete(self, identifier):
        document = self.get(identifier)
        with self.db.connect() as connection:
            connection.execute("DELETE FROM documents WHERE id=?", (identifier,))
        (self.uploads / (identifier + "." + document["kind"])).unlink(missing_ok=True)
        invalidate(self.db, [c["id"] for c in document["chunks"]], "来源已删除，需重新核对依据")

    def source_path(self, identifier):
        document = self.get(identifier)
        return self.uploads / (identifier + "." + document["kind"]), document["filename"]

    def rechunk(self, identifier, size, overlap):
        with self.lock:
            path, _ = self.source_path(identifier)
            document = self.get(identifier)
            parser = "docling" if document["parser"].startswith("docling") else "native"
            units, _, _, extras = self._parse(path.read_bytes(), "." + document["kind"], parser)
            chunks = split_chunks(identifier, units, size, overlap)
            with self.db.connect() as connection:
                connection.execute("DELETE FROM chunks WHERE document_id=?", (identifier,))
                connection.executemany(
                    "INSERT INTO chunks VALUES (:id,:document_id,:ordinal,:page,:location,:start_offset,:end_offset,:text)",
                    chunks,
                )
                connection.execute("UPDATE documents SET chunk_count=? WHERE id=?", (len(chunks), identifier))
            self._annotate(identifier, chunks, parser, extras)
            updated = {c["id"]: c["text"] for c in chunks}
            invalidate(
                self.db,
                {c["id"] for c in document["chunks"] if updated.get(c["id"]) != c["text"]},
                "原文重新分块，旧引用需复核",
            )
            return self.get(identifier)

    @staticmethod
    def _parse(content, suffix, parser):
        if parser == "docling":
            from .parsing import docling_parse

            return docling_parse(content, suffix)
        if parser != "native":
            raise DocumentError("未知解析器")
        units, warnings, pages = parse(content, suffix)
        return units, warnings, pages, {}

    def _annotate(self, identifier, chunks, parser, extras):
        annotate(self.db, identifier, chunks, parser + "-v2")
        with self.db.connect() as connection:
            connection.execute("UPDATE document_meta SET parser=? WHERE document_id=?", (parser + "-v2", identifier))
            for chunk in chunks:
                extra = extras.get(chunk["location"], {})
                kind = extra.get("kind", "table" if chunk["text"].lstrip().startswith("|") else "text")
                if extra:
                    connection.execute(
                        "UPDATE chunk_meta SET heading=?,bbox=?,kind=? WHERE chunk_id=?",
                        (extra.get("heading", ""), json.dumps(extra.get("bbox", [])), kind, chunk["id"]),
                    )
                else:
                    connection.execute("UPDATE chunk_meta SET kind=? WHERE chunk_id=?", (kind, chunk["id"]))

    def reparse(self, identifier, parser):
        with self.lock:
            document = self.get(identifier)
            path, _ = self.source_path(identifier)
            units, warnings, pages, extras = self._parse(path.read_bytes(), "." + document["kind"], parser)
            chunks = split_chunks(identifier, units)
            with self.db.connect() as connection:
                connection.execute("DELETE FROM chunks WHERE document_id=?", (identifier,))
                connection.executemany(
                    "INSERT INTO chunks VALUES (:id,:document_id,:ordinal,:page,:location,:start_offset,:end_offset,:text)",
                    chunks,
                )
                connection.execute(
                    "UPDATE documents SET chunk_count=?,pages=?,warnings=? WHERE id=?",
                    (len(chunks), pages, json.dumps(warnings), identifier),
                )
            self._annotate(identifier, chunks, parser, extras)
            updated = {c["id"]: c["text"] for c in chunks}
            invalidate(
                self.db,
                {c["id"] for c in document["chunks"] if updated.get(c["id"]) != c["text"]},
                "原文重新解析，旧引用需复核",
            )
            return self.get(identifier)
