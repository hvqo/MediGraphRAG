"""Optional enhanced parsing; imports are lazy and never change the base runtime."""

from pathlib import Path
import tempfile


def docling_parse(content, suffix):
    from .documents import DocumentError, MAX_TEXT

    try:
        from docling.document_converter import DocumentConverter
    except ImportError:
        raise DocumentError("增强解析器尚未安装；请在兼容环境安装 Docling 后从该环境启动应用，或选择轻量解析") from None
    try:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ("source" + suffix)
            path.write_bytes(content)
            document = DocumentConverter().convert(path).document
        units, extras = [], {}
        for item, _ in document.iterate_items():
            label = str(getattr(item, "label", "")).lower()
            text = item.export_to_markdown(doc=document) if "table" in label else getattr(item, "text", "")
            if not text or not str(text).strip():
                continue
            prov = next(iter(getattr(item, "prov", [])), None)
            page = int(prov.page_no) if prov else None
            location = f"第 {page} 页 · 结构块 {len(units) + 1}" if page else f"结构块 {len(units) + 1}"
            units.append((page, location, str(text).strip()))
            box = prov.bbox.model_dump(mode="json") if prov and getattr(prov, "bbox", None) else {}
            extras[location] = {
                "bbox": [box] if box else [],
                "kind": "table" if "table" in label else "text",
                "heading": str(text).strip() if "header" in label or "title" in label else "",
            }
        if not units or sum(len(item[2]) for item in units) > MAX_TEXT:
            raise DocumentError("增强解析结果为空或正文过大")
        return units, [], max((item[0] or 0 for item in units), default=0), extras
    except DocumentError:
        raise
    except Exception:
        raise DocumentError("增强解析失败，请检查 Docling 依赖、模型文件与源文件") from None
