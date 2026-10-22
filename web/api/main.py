from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import os
from medigraph.config import SettingsStore, SettingsUpdate, model_paths
from medigraph.llm import ModelClient, ModelError


def create_app(data_dir=None):
    app = FastAPI(title="MediGraphRAG 医学知识与出题平台", version="0.2.0")
    app.add_middleware(CORSMiddleware, allow_origins=os.getenv("MEDIGRAPH_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","), allow_credentials=False, allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Content-Type"])
    app.state.settings = SettingsStore(data_dir)
    app.state.model = ModelClient(app.state.settings)

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
