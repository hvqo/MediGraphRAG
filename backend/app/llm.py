import json
import asyncio
import httpx
import time
import uuid
from contextlib import nullcontext
from .storage import now


class ModelError(RuntimeError):
    pass


class ModelClient:
    def __init__(self, store, db=None, role="generation", template="structured-v1"):
        self.store = store
        self.db, self.role, self.template = db, role, template
        self.usage = (None, None)

    def _headers(self):
        return {"Authorization": "Bearer " + self.store.key()}

    def snapshot(self, role=None, template=None):
        from types import SimpleNamespace

        with getattr(self.store, "lock", nullcontext()):
            settings, key = self.store.get().model_copy(deep=True), self.store.key()
        if role == "review" and settings.review_provider != "same":
            settings.provider = settings.review_provider
            if settings.review_model:
                setattr(
                    settings, "ollama_model" if settings.provider == "ollama" else "cloud_model", settings.review_model
                )
        return ModelClient(
            SimpleNamespace(get=lambda: settings, key=lambda: key),
            self.db,
            role or self.role,
            template or self.template,
        )

    async def check(self):
        settings = self.store.get()
        self.usage = (None, None)
        try:
            async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
                if settings.provider == "ollama":
                    response = await client.get(settings.ollama_base_url + "/api/tags")
                    response.raise_for_status()
                    names = [item["name"] for item in response.json().get("models", [])]
                    matched = settings.ollama_model in names or settings.ollama_model + ":latest" in names
                    return {
                        "ok": matched,
                        "message": "模型可用" if matched else "服务已连接，但指定模型尚未下载",
                        "models": names,
                    }
                if not settings.cloud_base_url or not settings.cloud_model or not self.store.key():
                    return {"ok": False, "message": "请填写云端地址、模型名称和 API 密钥"}
                response = await client.get(settings.cloud_base_url + "/models", headers=self._headers())
                response.raise_for_status()
                return {
                    "ok": True,
                    "message": "服务已连接；模型可调用性以实际生成结果为准",
                    "models": [item["id"] for item in response.json().get("data", [])],
                }
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
            return {"ok": False, "message": "无法连接模型服务，请检查地址、网络或凭据"}

    async def json(self, system, prompt):
        started, output, error = time.perf_counter(), None, ""
        self.usage = (None, None)
        settings = self.store.get()
        from .retrieval import revision

        source_revision = revision(self.db.chunks()) if self.db else ""
        try:
            output = await self._json(system, prompt)
            return output
        except ModelError as exc:
            error = str(exc)
            raise
        except asyncio.CancelledError:
            error = "调用中断"
            raise
        except Exception:
            error = "调用内部处理失败"
            raise
        finally:
            if self.db:
                with self.db.connect() as connection:
                    connection.execute(
                        "INSERT INTO traces VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            uuid.uuid4().hex,
                            self.role,
                            settings.provider,
                            settings.ollama_model if settings.provider == "ollama" else settings.cloud_model,
                            self.template,
                            "failed" if error else "completed",
                            round(time.perf_counter() - started, 4),
                            *self.usage,
                            json.dumps(
                                {
                                    "system": system,
                                    "prompt": prompt,
                                    "settings": settings.model_dump(),
                                    "source_revision": source_revision,
                                },
                                ensure_ascii=False,
                            ),
                            json.dumps(output, ensure_ascii=False) if output is not None else None,
                            error,
                            now(),
                        ),
                    )

    async def _json(self, system, prompt):
        settings = self.store.get()
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout, trust_env=False) as client:
                if settings.provider == "ollama":
                    response = await client.post(
                        settings.ollama_base_url + "/api/chat",
                        json={
                            "model": settings.ollama_model,
                            "messages": messages,
                            "stream": False,
                            "format": "json",
                            "options": {"temperature": 0.15, "num_ctx": 8192},
                        },
                    )
                    response.raise_for_status()
                    payload = response.json()
                    content = payload["message"]["content"]
                    self.usage = (payload.get("prompt_eval_count"), payload.get("eval_count"))
                else:
                    if not settings.cloud_base_url or not settings.cloud_model or not self.store.key():
                        raise ModelError("云端模型尚未配置完整")
                    response = await client.post(
                        settings.cloud_base_url + "/chat/completions",
                        headers=self._headers(),
                        json={
                            "model": settings.cloud_model,
                            "messages": messages,
                            "temperature": 0.15,
                            "response_format": {"type": "json_object"},
                        },
                    )
                    response.raise_for_status()
                    payload = response.json()
                    content = payload["choices"][0]["message"]["content"]
                    usage = payload.get("usage") or {}
                    self.usage = (usage.get("prompt_tokens"), usage.get("completion_tokens"))
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            result = json.loads(content)
            if not isinstance(result, dict):
                raise ValueError("Expected JSON object")
            return result
        except ModelError:
            raise
        except httpx.HTTPStatusError as exc:
            raise ModelError(f"模型服务返回 HTTP {exc.response.status_code}，请检查模型和配置") from None
        except httpx.HTTPError:
            raise ModelError("模型服务连接失败或超时，请检查服务状态") from None
        except (ValueError, KeyError, TypeError, IndexError, AttributeError):
            raise ModelError("模型没有返回有效的结构化结果，请重试或更换模型") from None


def for_task(model, role, template):
    """Freeze a real client, while supporting narrow test transports."""
    return model.snapshot(role, template) if isinstance(model, ModelClient) else model
