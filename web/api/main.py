from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import os
from medigraph.config import SettingsStore, SettingsUpdate, model_paths
from medigraph.llm import ModelClient, ModelError
from medigraph.storage import Database
from medigraph.documents import DocumentStore, DocumentError
from medigraph.document_routes import routes as document_routes
from medigraph.retrieval import Retriever
from medigraph.retrieval_routes import routes as retrieval_routes
from medigraph.questions import QuestionStore, GenerationJobs
from medigraph.question_routes import routes as question_routes
from contextlib import asynccontextmanager


def create_app(data_dir=None):
    @asynccontextmanager
    async def lifespan(application):
        application.state.jobs.recover()
        yield
        await application.state.jobs.shutdown()
    app = FastAPI(title="MediGraphRAG 医学知识与出题平台", version="0.2.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=os.getenv("MEDIGRAPH_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","), allow_credentials=False, allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Content-Type"])
    app.state.settings = SettingsStore(data_dir)
    app.state.model = ModelClient(app.state.settings)
    app.state.db = Database(app.state.settings.directory)
    app.state.documents = DocumentStore(app.state.db)
    app.include_router(document_routes(app.state.documents))
    app.state.retriever = Retriever(app.state.db, app.state.settings)
    app.include_router(retrieval_routes(app.state.retriever, app.state.model))
    app.state.questions = QuestionStore(app.state.db)
    app.state.jobs = GenerationJobs(app.state.questions, app.state.retriever, app.state.model)
    app.include_router(question_routes(app.state.questions, app.state.jobs))

    @app.exception_handler(DocumentError)
    async def document_error(request: Request, error: DocumentError):
        return JSONResponse(status_code=422, content={"detail": str(error)})

    @app.exception_handler(ModelError)
    async def model_error(request: Request, error: ModelError):
        return JSONResponse(status_code=503, content={"detail": str(error)})

    @app.get("/health")
    def health():
        return {"status": "ok", "version": app.version}

    @app.get("/status")
    def status():
        embedding, reranker = model_paths()
        weights = lambda directory: any((directory / name).exists() for name in ["model.safetensors", "pytorch_model.bin"])
        return {"status": "ok", "provider": app.state.settings.get().provider,
                "embedding_ready": weights(embedding), "reranker_ready": weights(reranker),
                "neo4j_configured": bool(os.getenv("MEDIGRAPH_NEO4J_PASSWORD")),
                "message": "服务已启动；资料导入与关键词检索不依赖本地模型权重"}

    @app.get("/settings")
    def settings():
        return app.state.settings.public()

    @app.put("/settings")
    def update_settings(value: SettingsUpdate):
        return app.state.settings.update(value)

    @app.post("/settings/test")
    async def test_settings():
        return await app.state.model.check()

    return app


app = create_app()
