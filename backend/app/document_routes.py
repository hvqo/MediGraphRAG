from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from .documents import MAX_BYTES
from .provenance import DocumentMetadata, VersionLink, Chunking, update_metadata, link_version, version_impact
from typing import Literal


class TextDocument(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=2_000_000)


class ParserChoice(BaseModel):
    parser: Literal['native', 'docling'] = 'native'


def routes(store):
    router = APIRouter()

    @router.get('/documents')
    def list_documents():
        return store.list()

    @router.post('/documents/text', status_code=201)
    def add_text(value: TextDocument):
        return store.add('粘贴资料.txt', value.text.encode('utf-8'), value.title)

    @router.post('/documents/upload', status_code=201)
    async def upload(file: UploadFile = File(...), parser: Literal['native', 'docling'] = Form('native')):
        try:
            content = await file.read(MAX_BYTES + 1)
            return await run_in_threadpool(store.add, file.filename or '资料.txt', content, None, parser)
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

    @router.get('/documents/{identifier}/reader')
    def reader(identifier: str):
        try:
            return store.get(identifier)
        except KeyError:
            raise HTTPException(404, '资料不存在')

    @router.put('/documents/{identifier}/metadata')
    def edit_metadata(identifier: str, value: DocumentMetadata):
        try:
            return update_metadata(store, identifier, value)
        except KeyError:
            raise HTTPException(404, '资料不存在')

    @router.post('/documents/{identifier}/rechunk')
    def rechunk(identifier: str, value: Chunking):
        try:
            return store.rechunk(identifier, value.size, value.overlap)
        except KeyError:
            raise HTTPException(404, '资料不存在')

    @router.post('/documents/{identifier}/reparse')
    def reparse(identifier: str, value: ParserChoice):
        try:
            return store.reparse(identifier, value.parser)
        except KeyError:
            raise HTTPException(404, '资料不存在')

    @router.get('/documents/{identifier}/impact/{new_id}')
    def impact(identifier: str, new_id: str):
        try:
            return version_impact(store, identifier, new_id)
        except KeyError:
            raise HTTPException(404, '资料不存在')

    @router.post('/documents/{identifier}/version')
    def version(identifier: str, value: VersionLink):
        try:
            return link_version(store, identifier, value.predecessor)
        except KeyError:
            raise HTTPException(404, '资料不存在')
        except ValueError as error:
            raise HTTPException(422, str(error))

    @router.delete('/documents/{identifier}')
    def delete(identifier: str):
        try:
            store.delete(identifier)
            return {'deleted': True}
        except KeyError:
            raise HTTPException(404, '资料不存在')

    return router
