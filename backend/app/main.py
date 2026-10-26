from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import os
from backend.app.config import SettingsStore, SettingsUpdate, model_paths
from backend.app.config import ROOT
from backend.app.llm import ModelClient, ModelError
from backend.app.storage import Database
from backend.app.documents import DocumentStore, DocumentError
from backend.app.document_routes import routes as document_routes
from backend.app.retrieval import Retriever
from backend.app.retrieval_routes import routes as retrieval_routes
from backend.app.questions import QuestionStore, GenerationJobs
from backend.app.question_routes import routes as question_routes
from backend.app.relations import RelationStore, routes as relation_routes
from backend.app.teaching import routes as teaching_routes
from backend.app.learning import routes as learning_routes
from backend.app.evaluations import routes as evaluation_routes
from contextlib import asynccontextmanager


def create_app(data_dir=None):
    @asynccontextmanager
    async def lifespan(application):
        application.state.jobs.recover()
        yield
        await application.state.jobs.shutdown()

    app = FastAPI(title="MediGraphRAG 医学知识与出题平台", version="0.4.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv("MEDIGRAPH_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type"],
    )
    app.state.settings = SettingsStore(data_dir)
    app.state.db = Database(app.state.settings.directory)
    app.state.model = ModelClient(app.state.settings, app.state.db)
    app.state.documents = DocumentStore(app.state.db)
    app.include_router(document_routes(app.state.documents))
    app.state.retriever = Retriever(app.state.db, app.state.settings)
    app.include_router(retrieval_routes(app.state.retriever, app.state.model))
    app.state.questions = QuestionStore(app.state.db)
    app.state.jobs = GenerationJobs(app.state.questions, app.state.retriever, app.state.model)
    app.include_router(question_routes(app.state.questions, app.state.jobs))
    app.state.relations = RelationStore(app.state.db)
    app.include_router(relation_routes(app.state.relations, app.state.model))
    app.include_router(teaching_routes(app.state.questions, app.state.jobs))
    app.include_router(learning_routes(app.state.questions))
    app.include_router(evaluation_routes(app.state.db, app.state.retriever, app.state.model))

    @app.middleware("http")
    async def api_alias(request, call_next):
        if request.scope["path"].startswith("/api/"):
            request.scope["path"] = request.scope["path"][4:]
            request.scope["raw_path"] = request.scope["path"].encode("utf-8")
        return await call_next(request)

    frontend = ROOT / "frontend/dist"
    if (frontend / "assets").exists():
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def homepage():
        if (frontend / "index.html").exists():
            return FileResponse(frontend / "index.html")
        return JSONResponse({"detail": "请先构建前端：cd frontend，然后运行 npm ci 和 npm run build"}, status_code=503)

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
        weights = lambda directory: any(
            (directory / name).exists() for name in ["model.safetensors", "pytorch_model.bin"]
        )
        return {
            "status": "ok",
            "provider": app.state.settings.get().provider,
            "embedding_ready": weights(embedding),
            "reranker_ready": weights(reranker),
            "neo4j_configured": bool(os.getenv("MEDIGRAPH_NEO4J_PASSWORD")),
            "message": "服务已启动；资料导入与关键词检索不依赖本地模型权重",
        }

    @app.get("/summary")
    def summary():
        return {
            "documents": app.state.db.rows("SELECT count(*) AS n FROM documents")[0]["n"],
            "chunks": len(app.state.db.chunks()),
            "pending": app.state.db.rows("SELECT count(*) AS n FROM questions WHERE status='pending_review'")[0]["n"],
        }

    @app.get("/parsers")
    def parsers():
        import importlib.util

        return {"native": True, "docling": importlib.util.find_spec("docling") is not None}

    @app.get("/settings")
    def settings():
        return app.state.settings.public()

    @app.put("/settings")
    def update_settings(value: SettingsUpdate):
        return app.state.settings.update(value)

    @app.post("/settings/test")
    async def test_settings():
        return await app.state.model.check()

    @app.post("/settings/test-review")
    async def test_review_settings():
        return await app.state.model.snapshot("review").check()

    return app


app = create_app()
