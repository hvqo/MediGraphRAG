import json
import asyncio
import httpx
import time
import uuid
import weakref
from contextlib import nullcontext
from .storage import now

_local_gates = weakref.WeakKeyDictionary()


def local_gate(address):
    gates = _local_gates.setdefault(asyncio.get_running_loop(), {})
    return gates.setdefault(address, asyncio.Lock())


class ModelError(RuntimeError):
    def __init__(self, message, status_code=503):
        super().__init__(message)
        self.status_code = status_code


class ModelClient:
    def __init__(self, store, db=None, role="generation", template="structured-v1", budget=None):
        self.store = store
        self.db, self.role, self.template = db, role, template
        self.usage = (None, None)
        self.budget = budget

    def _headers(self):
        return {"Authorization": "Bearer " + self.store.key()} if self.store.key() else {}

    def snapshot(self, role=None, template=None):
        from types import SimpleNamespace

        with getattr(self.store, "lock", nullcontext()):
            settings, key = self.store.get().model_copy(deep=True), self.store.key()
        if role == "review" and settings.review_provider != "same":
            settings.provider = settings.review_provider
            if settings.review_base_url:
                setattr(
                    settings,
                    "ollama_base_url" if settings.provider == "ollama" else "cloud_base_url",
                    settings.review_base_url,
                )
            key = getattr(self.store, "role_key", lambda role: "")("review") or key
            if settings.review_model:
                setattr(
                    settings, "ollama_model" if settings.provider == "ollama" else "cloud_model", settings.review_model
                )
        if role == "vision":
            settings.provider = settings.vision_provider
            settings.request_timeout = settings.vision_timeout
            setattr(
                settings,
                "ollama_base_url" if settings.provider == "ollama" else "cloud_base_url",
                settings.vision_base_url,
            )
            setattr(settings, "ollama_model" if settings.provider == "ollama" else "cloud_model", settings.vision_model)
            key = getattr(self.store, "role_key", lambda role: key)("vision")
        return ModelClient(
            SimpleNamespace(get=lambda: settings, key=lambda: key),
            self.db,
            role or self.role,
            template or self.template,
            budget=self.budget,
        )

    async def check(self):
        settings = self.store.get()
        self.usage = (None, None)
        try:
            async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
                if settings.provider == "ollama":
                    if self.role == "vision" and settings.ollama_model.startswith("qwen3-vl"):
                        version_response = await client.get(settings.ollama_base_url + "/api/version")
                        version_response.raise_for_status()
                        version = tuple(int(p) for p in version_response.json()["version"].split("-")[0].split(".")[:3])
                        if version < (0, 12, 7):
                            return {
                                "ok": False,
                                "message": "Qwen3-VL需要Ollama 0.12.7或更新版本，请运行scripts/prepare_ollama.ps1并启动项目模型服务",
                            }
                    response = await client.get(settings.ollama_base_url + "/api/tags")
                    response.raise_for_status()
                    names = [item["name"] for item in response.json().get("models", [])]
                    matched = settings.ollama_model in names or settings.ollama_model + ":latest" in names
                    return {
                        "ok": matched,
                        "message": "模型可用" if matched else "服务已连接，但指定模型尚未下载",
                        "models": names,
                    }
                if (
                    not settings.cloud_base_url
                    or not settings.cloud_model
                    or (settings.provider == "cloud" and not self.store.key())
                ):
                    return {"ok": False, "message": "请填写兼容接口地址和模型名称；云端服务还需要 API 密钥"}
                response = await client.get(settings.cloud_base_url + "/models", headers=self._headers())
                response.raise_for_status()
                return {
                    "ok": True,
                    "message": "服务已连接；模型可调用性以实际生成结果为准",
                    "models": [item["id"] for item in response.json().get("data", [])],
                }
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
            return {"ok": False, "message": "无法连接模型服务，请检查地址、网络或凭据"}

    async def json(self, system, prompt, images=None):
        started, output, error = time.perf_counter(), None, ""
        self.usage = (None, None)
        settings = self.store.get()
        from .retrieval import revision

        source_revision = revision(self.db.chunks()) if self.db else ""
        try:
            if self.budget:
                self.budget()
            output = await self._json(system, prompt, images) if images else await self._json(system, prompt)
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
                                    "image_count": len(images or []),
                                },
                                ensure_ascii=False,
                            ),
                            json.dumps(output, ensure_ascii=False) if output is not None else None,
                            error,
                            now(),
                        ),
                    )

    async def vision_json(self, system, prompt, images, model_name=None):
        client = self.snapshot("vision", "document-vision-v2")
        settings = client.store.get()
        if model_name:
            setattr(settings, "ollama_model" if settings.provider == "ollama" else "cloud_model", model_name)
        return await client.json(system, prompt, images)

    async def _json(self, system, prompt, images=None):
        settings = self.store.get()
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        if images:
            messages[-1]["images"] = images
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout, trust_env=False) as client:
                if settings.provider == "ollama":
                    async with local_gate(settings.ollama_base_url):
                        response = await client.post(
                            settings.ollama_base_url + "/api/chat",
                            json={
                                "model": settings.ollama_model,
                                "messages": messages,
                                "stream": False,
                                "format": "json",
                                "options": {
                                    "temperature": 0.15,
                                    "num_ctx": settings.vision_context_tokens if images else 8192,
                                    **({"num_predict": settings.vision_max_tokens} if images else {}),
                                },
                                # Release the large VLM before the following text-generation stage.
                                "keep_alive": 0 if images else "2m",
                            },
                        )
                    response.raise_for_status()
                    payload = response.json()
                    if payload.get("done_reason") == "length":
                        raise ModelError("模型输出达到长度上限，原页没有完整识别；请提高输出上限或拆分页/区域")
                    content = payload["message"]["content"]
                    self.usage = (payload.get("prompt_eval_count"), payload.get("eval_count"))
                else:
                    if (
                        not settings.cloud_base_url
                        or not settings.cloud_model
                        or (settings.provider == "cloud" and not self.store.key())
                    ):
                        raise ModelError("兼容接口尚未配置完整；云端服务还需要API密钥")
                    cloud_messages = messages
                    if images:
                        cloud_messages = [
                            messages[0],
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": prompt},
                                    *[
                                        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + image}}
                                        for image in images
                                    ],
                                ],
                            },
                        ]
                    async with local_gate(settings.cloud_base_url):
                        response = await client.post(
                            settings.cloud_base_url + "/chat/completions",
                            headers=self._headers(),
                            json={
                                "model": settings.cloud_model,
                                "messages": cloud_messages,
                                "temperature": 0.15,
                                "response_format": {"type": "json_object"},
                                **({"max_tokens": settings.vision_max_tokens} if images else {}),
                            },
                        )
                    response.raise_for_status()
                    payload = response.json()
                    if payload["choices"][0].get("finish_reason") == "length":
                        raise ModelError("模型输出达到长度上限，结果不完整；请拆分内容或提高输出上限")
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
