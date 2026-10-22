import io
import tempfile
import unittest
import zipfile
from fastapi.testclient import TestClient
from web.api.main import create_app


class DocumentTests(unittest.TestCase):
    def test_pdf_preserves_page_number_and_warns_about_blank_page(self):
        from pypdf import PdfWriter
        from pypdf.generic import NameObject, DictionaryObject, DecodedStreamObject
        stream = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(300, 300)
        page = writer.add_blank_page(300, 300)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        content = DecodedStreamObject()
        content.set_data(b'BT /F1 12 Tf 20 200 Td (Medical software fixture.) Tj ET')
        page[NameObject('/Contents')] = content
        writer.write(stream)
        with tempfile.TemporaryDirectory() as directory:
            client = TestClient(create_app(directory))
            result = client.post('/documents/upload', files={'file': ('fixture.pdf', stream.getvalue())})
            self.assertEqual(result.status_code, 201)
            self.assertEqual(result.json()['pages'], 2)
            self.assertEqual(len(result.json()['warnings']), 1)
            detail = client.get('/documents/' + result.json()['id']).json()
            self.assertEqual(detail['chunks'][0]['page'], 2)
            self.assertIn('Medical software fixture.', detail['chunks'][0]['text'])

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
