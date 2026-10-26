from pathlib import Path
import json
import os
import threading
from typing import Literal
from urllib.parse import urlsplit
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / '.env', override=False)


class Settings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provider: Literal['ollama', 'cloud'] = 'ollama'
    ollama_base_url: str = 'http://127.0.0.1:11434'
    ollama_model: str = 'qwen2.5'
    cloud_base_url: str = ''
    cloud_model: str = ''
    top_k: int = Field(default=5, ge=1, le=10)
    use_vectors: bool = False
    use_reranker: bool = False
    device: Literal['cpu', 'cuda'] = 'cpu'
    request_timeout: int = Field(default=180, ge=10, le=600)

    @field_validator('ollama_base_url', 'cloud_base_url')
    @classmethod
    def valid_url(cls, value):
        value = value.strip().rstrip('/')
        if value:
            url = urlsplit(value)
            if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError('请输入不含凭据或查询参数的 HTTP(S) 服务地址')
        return value

    @field_validator('ollama_model', 'cloud_model')
    @classmethod
    def valid_model(cls, value):
        return value.strip()


class SettingsUpdate(Settings):
    cloud_api_key: str | None = Field(default=None, max_length=4096)


class SettingsStore:
    def __init__(self, data_dir=None):
        self.directory = Path(data_dir or os.getenv('MEDIGRAPH_DATA_DIR', ROOT / '.runtime')).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'settings.json'
        self.lock = threading.RLock()

    def _read(self):
        return json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}

    def get(self):
        with self.lock:
            return Settings.model_validate(self._read().get('settings', {}))

    def key(self):
        with self.lock:
            return os.getenv('MEDIGRAPH_CLOUD_API_KEY') or self._read().get('cloud_api_key', '')

    def public(self):
        return {**self.get().model_dump(), 'cloud_api_key_configured': bool(self.key()),
                'cloud_api_key_from_environment': bool(os.getenv('MEDIGRAPH_CLOUD_API_KEY'))}

    def update(self, value):
        with self.lock:
            document = self._read()
            document['settings'] = value.model_dump(exclude={'cloud_api_key'})
            if value.cloud_api_key is not None:
                document['cloud_api_key'] = value.cloud_api_key.strip()
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.chmod(0o600)
            temporary.replace(self.path)
        return self.public()


def model_paths():
    return (Path(os.getenv('MEDIGRAPH_EMBEDDING_PATH', ROOT / 'model/bge-large-zh-v1.5')),
            Path(os.getenv('MEDIGRAPH_RERANKER_PATH', ROOT / 'model/bge-reranker-v2-m3')))
