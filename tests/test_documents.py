import io
import tempfile
import unittest
import zipfile
from fastapi.testclient import TestClient
from web.api.main import create_app


class DocumentTests(unittest.TestCase):
    def test_import_duplicate_provenance_and_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            client = TestClient(create_app(directory))
            payload = {'title': '医学学习资料', 'text': '这是用于软件测试的医学资料。\n\n第二段包含检查相关内容。'}
            result = client.post('/documents/text', json=payload)
            self.assertEqual(result.status_code, 201)
            identifier = result.json()['id']
            self.assertTrue(client.post('/documents/text', json=payload).json()['duplicate'])
            detail = client.get('/documents/' + identifier).json()
            self.assertEqual(detail['chunks'][1]['location'], '第 2 段')
            self.assertEqual(detail['chunks'][0]['document_id'], identifier)
            self.assertEqual(len(client.get('/documents').json()), 1)
            self.assertEqual(client.get(f'/documents/{identifier}/source').content.decode(), payload['text'])
            self.assertEqual(client.delete('/documents/' + identifier).status_code, 200)
            self.assertEqual(client.get('/documents/' + identifier).status_code, 404)
            self.assertEqual(client.app.state.db.chunks(), [])

    def test_docx_import_does_not_depend_on_shadowed_docx_package(self):
        with tempfile.TemporaryDirectory() as directory:
            client = TestClient(create_app(directory))
            content = io.BytesIO()
            with zipfile.ZipFile(content, 'w') as archive:
                archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>医学资料测试</w:t></w:r></w:p></w:body></w:document>')
            response = client.post('/documents/upload', files={'file': ('测试.docx', content.getvalue())})
            self.assertEqual(response.status_code, 201)
            identifier = response.json()['id']
            self.assertEqual(client.get('/documents/' + identifier).json()['chunks'][0]['text'], '医学资料测试')

    def test_reject_empty_pdf_and_unsupported_type(self):
        from pypdf import PdfWriter
        with tempfile.TemporaryDirectory() as directory:
            client = TestClient(create_app(directory))
            stream = io.BytesIO()
            writer = PdfWriter()
            writer.add_blank_page(100, 100)
            writer.write(stream)
            self.assertEqual(client.post('/documents/upload', files={'file': ('扫描.pdf', stream.getvalue())}).status_code, 422)
            self.assertEqual(client.post('/documents/upload', files={'file': ('test.exe', b'test')}).status_code, 422)
