from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from .documents import MAX_BYTES


class TextDocument(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=2_000_000)


def routes(store):
    router = APIRouter()

    @router.get('/documents')
    def list_documents():
        return store.list()

    @router.post('/documents/text', status_code=201)
    def add_text(value: TextDocument):
        return store.add('粘贴资料.txt', value.text.encode('utf-8'), value.title)

    @router.post('/documents/upload', status_code=201)
    async def upload(file: UploadFile = File(...)):
        try:
            content = await file.read(MAX_BYTES + 1)
            return await run_in_threadpool(store.add, file.filename or '资料.txt', content)
        finally:
            await file.close()

    @router.get('/documents/{identifier}')
    def detail(identifier: str):
        try:
            return store.get(identifier)
        except KeyError:
            raise HTTPException(404, '资料不存在')

    @router.get('/documents/{identifier}/source')
    def source(identifier: str):
        try:
            path, filename = store.source_path(identifier)
            return FileResponse(path, filename=filename)
        except KeyError:
            raise HTTPException(404, '资料不存在')

    @router.delete('/documents/{identifier}')
    def delete(identifier: str):
        try:
            store.delete(identifier)
            return {'deleted': True}
        except KeyError:
            raise HTTPException(404, '资料不存在')

    return router
