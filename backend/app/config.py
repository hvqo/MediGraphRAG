from pathlib import Path
import json
import os
import threading
from typing import Literal
from urllib.parse import urlsplit
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=False)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["ollama", "openai", "cloud"] = Field(
        default_factory=lambda: os.getenv("MEDIGRAPH_DEFAULT_PROVIDER", "ollama")
    )
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5"
    cloud_base_url: str = Field(default_factory=lambda: os.getenv("MEDIGRAPH_DEFAULT_API_BASE", ""))
    cloud_model: str = Field(default_factory=lambda: os.getenv("MEDIGRAPH_DEFAULT_API_MODEL", ""))
    top_k: int = Field(default=5, ge=1, le=10)
    use_vectors: bool = Field(default_factory=lambda: os.getenv("MEDIGRAPH_DEFAULT_VECTORS", "0") == "1")
    use_reranker: bool = Field(default_factory=lambda: os.getenv("MEDIGRAPH_DEFAULT_RERANK", "0") == "1")
    device: Literal["cpu", "cuda"] = "cpu"
    request_timeout: int = Field(default=180, ge=10, le=600)
    review_provider: Literal["same", "ollama", "openai", "cloud"] = "same"
    review_model: str = Field(default="", max_length=200)
    review_base_url: str = ""
    vision_provider: Literal["ollama", "openai", "cloud"] = Field(
        default_factory=lambda: os.getenv("MEDIGRAPH_DEFAULT_PROVIDER", "ollama")
    )
    vision_base_url: str = Field(
        default_factory=lambda: os.getenv("MEDIGRAPH_DEFAULT_API_BASE", "http://127.0.0.1:11434")
    )
    vision_model: str = Field(default="qwen3-vl:8b-instruct", min_length=1, max_length=200)
    vision_timeout: int = Field(default=600, ge=10, le=1200)
    vision_image_max_edge: int = Field(default=2400, ge=1024, le=4096)
    vision_context_tokens: int = Field(default=8192, ge=4096, le=32768)
    vision_max_tokens: int = Field(default=4096, ge=512, le=8192)
    embedding_model: Literal["auto", "bge-v1.5", "bge-m3"] = "auto"

    @field_validator("ollama_base_url", "cloud_base_url", "review_base_url", "vision_base_url")
    @classmethod
    def valid_url(cls, value):
        value = value.strip().rstrip("/")
        if value:
            url = urlsplit(value)
            if (
                url.scheme not in ("http", "https")
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
            ):
                raise ValueError("请输入不含凭据或查询参数的 HTTP(S) 服务地址")
        return value

    @field_validator("ollama_model", "cloud_model", "vision_model", "review_model")
    @classmethod
    def valid_model(cls, value):
        return value.strip()


class SettingsUpdate(Settings):
    cloud_api_key: str | None = Field(default=None, max_length=4096)
    vision_api_key: str | None = Field(default=None, max_length=4096)
    review_api_key: str | None = Field(default=None, max_length=4096)


class SettingsStore:
    def __init__(self, data_dir=None):
        self.directory = Path(data_dir or os.getenv("MEDIGRAPH_DATA_DIR", ROOT / ".runtime")).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "settings.json"
        self.lock = threading.RLock()

    def _read(self):
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def get(self):
        with self.lock:
            return Settings.model_validate(self._read().get("settings", {}))

    def key(self):
        with self.lock:
            return os.getenv("MEDIGRAPH_CLOUD_API_KEY") or self._read().get("cloud_api_key", "")

    def role_key(self, role):
        with self.lock:
            return os.getenv("MEDIGRAPH_" + role.upper() + "_API_KEY") or self._read().get(role + "_api_key", "")

    def public(self):
        return {
            **self.get().model_dump(),
            "cloud_api_key_configured": bool(self.key()),
            "cloud_api_key_from_environment": bool(os.getenv("MEDIGRAPH_CLOUD_API_KEY")),
            "vision_api_key_configured": bool(self.role_key("vision")),
            "vision_api_key_from_environment": bool(os.getenv("MEDIGRAPH_VISION_API_KEY")),
            "review_api_key_configured": bool(self.role_key("review")),
            "review_api_key_from_environment": bool(os.getenv("MEDIGRAPH_REVIEW_API_KEY")),
        }

    def update(self, value):
        with self.lock:
            document = self._read()
            secret_fields = {"cloud_api_key", "vision_api_key", "review_api_key"}
            document["settings"] = value.model_dump(exclude=secret_fields)
            for field in secret_fields:
                if getattr(value, field) is not None:
                    document[field] = getattr(value, field).strip()
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.chmod(0o600)
            temporary.replace(self.path)
        return self.public()


def model_paths():
    managed = ROOT / ".runtime/models/bge-large-zh-v1.5"
    modern_reranker = ROOT / ".runtime/models/bge-reranker-v2-m3"
    managed_reranker = (
        modern_reranker
        if (modern_reranker / "model.safetensors").exists()
        else ROOT / ".runtime/models/bge-reranker-base"
    )
    return (
        Path(
            os.getenv(
                "MEDIGRAPH_EMBEDDING_PATH",
                managed
                if (managed / "pytorch_model.bin").exists() or (managed / "model.safetensors").exists()
                else ROOT / "model/bge-large-zh-v1.5",
            )
        ),
        Path(
            os.getenv(
                "MEDIGRAPH_RERANKER_PATH",
                managed_reranker
                if (managed_reranker / "model.safetensors").exists()
                else ROOT / "model/bge-reranker-v2-m3",
            )
        ),
    )
