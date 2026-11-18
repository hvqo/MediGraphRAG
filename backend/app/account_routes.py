"""Account APIs and the boundary between public assets and private libraries."""

import hashlib
import secrets
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.requests import Request as ScopeRequest

from .accounts import AccountError, SESSION_COOKIE, flag


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=12, max_length=128)


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class AdminPassword(BaseModel):
    password: str = Field(min_length=12, max_length=128)


class Disabled(BaseModel):
    disabled: bool


def routes(store):
    router = APIRouter(prefix="/auth", tags=["accounts"])

    def issued(token, payload):
        response = JSONResponse(payload)
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=store.policy.session_seconds,
            httponly=True,
            secure=store.policy.secure_cookie,
            samesite="strict",
        )
        return response

    @router.get("/status")
    def status(request: Request):
        user = store.session(request.cookies.get(SESSION_COOKIE, ""))
        return {
            "enabled": True,
            "registration_enabled": store.policy.registration_enabled,
            "user": store.public(user) if user else None,
            "csrf_token": user["csrf_token"] if user else "",
        }

    @router.post("/register", status_code=201)
    def register(value: Credentials):
        if not store.policy.registration_enabled:
            raise AccountError("暂未开放注册，请联系管理员", 403)
        user = store.create(value.username, value.password)
        return issued(*store.issue(user["id"]))

    @router.post("/login")
    def login(value: Credentials, request: Request):
        digest = hashlib.sha256(value.username.casefold().encode()).hexdigest()
        store.hit("login-user:" + digest, 10, 900)
        return issued(*store.login(value.username, value.password))

    @router.post("/logout")
    def logout(request: Request):
        store.logout(request.cookies.get(SESSION_COOKIE, ""))
        response = JSONResponse({"message": "已退出登录"})
        response.delete_cookie(SESSION_COOKIE, secure=store.policy.secure_cookie, httponly=True, samesite="strict")
        return response

    @router.get("/usage")
    def usage(request: Request):
        return store.usage(request.state.account["id"])

    @router.post("/password")
    def password(value: PasswordChange, request: Request):
        store.password(request.state.account["id"], value.new_password, value.current_password)
        return {"message": "密码已修改，所有设备已退出，请重新登录"}

    @router.get("/admin/users")
    def users():
        return store.list_users()

    @router.post("/admin/users")
    def create_user(value: Credentials):
        return store.public(store.create(value.username, value.password))

    @router.put("/admin/users/{identifier}")
    def disable(identifier: str, value: Disabled, request: Request):
        store.disable(identifier, value.disabled, request.state.account["id"])
        return store.public(store.user(identifier))

    @router.post("/admin/users/{identifier}/password")
    def reset(identifier: str, value: AdminPassword):
        store.password(identifier, value.password)
        return {"message": "密码已重置，该账号的所有设备已退出"}

    return router


class AccountMiddleware:
    def __init__(self, app, store, registry):
        self.app, self.store, self.registry = app, store, registry

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = ScopeRequest(scope)
        path, method, policy = scope["path"], scope["method"], self.store.policy
        mutating = method not in {"GET", "HEAD", "OPTIONS"}

        async def secure_send(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).extend(
                    [
                        (b"cache-control", b"no-store"),
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"same-origin"),
                    ]
                )
            await send(message)

        try:
            if path in {"/", "/health", "/favicon.ico"} or path.startswith("/assets/"):
                return await self.app(scope, receive, secure_send)
            if mutating:
                origin = request.headers.get("origin")
                expected = policy.public_origin or str(request.base_url).rstrip("/")
                if (origin and origin != expected) or request.headers.get("sec-fetch-site") == "cross-site":
                    raise AccountError("请从本站页面提交请求", 403)
            user = self.store.session(request.cookies.get(SESSION_COOKIE, ""))
            public_auth = path in {"/auth/status", "/auth/login", "/auth/register"}
            if not user and not public_auth:
                raise AccountError("请先登录", 401)
            if user and mutating and not public_auth:
                if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), user["csrf_token"]):
                    raise AccountError("登录验证已失效，请刷新页面后重试", 403)
            admin_path = path.startswith(
                ("/settings", "/auth/admin/", "/graph/neo4j", "/relations/sync", "/docs", "/redoc", "/openapi.json")
            )
            if admin_path and (not user or user["role"] != "admin"):
                raise AccountError("此功能仅管理员可用", 403)
            if path in {"/auth/login", "/auth/register"} and mutating:
                address = request.client.host if request.client else "unknown"
                if flag("MEDIGRAPH_TRUST_GATEWAY"):
                    address = request.headers.get("x-real-ip", address)
                ip = hashlib.sha256(address.encode()).hexdigest()
                self.store.hit(
                    path + ":" + ip,
                    10 if path.endswith("register") else 100,
                    3600 if path.endswith("register") else 900,
                )
            elif user:
                self.store.hit("requests:" + user["id"], policy.requests_per_minute, 60)
            application = None
            if not path.startswith("/auth/"):
                application = self.registry.app({"id": user["library_id"]})
            if mutating:
                size, parts = 0, []
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    size += len(message.get("body", b""))
                    if size > policy.request_bytes:
                        raise AccountError(f"单次提交最多{policy.request_bytes // (1024 * 1024)}MB，请分批上传", 413)
                    parts.append(message)
                    if not message.get("more_body", False):
                        break
                if application and (path.startswith("/documents") or path == "/workspace/submit"):
                    directory = self.registry.directory / "libraries" / user["library_id"]
                    used = sum(p.stat().st_size for p in directory.rglob("*") if p.is_file())
                    if used + size * 2 > policy.storage_bytes:
                        raise AccountError("个人资料库空间不足，请先清理文件或联系管理员", 413)
                if application and path in {"/workspace/submit", "/workspace/request"}:
                    pending = application.state.db.rows(
                        "SELECT count(*) AS n FROM operations WHERE status IN ('queued','running','foreground_done')"
                    )[0]["n"]
                    if pending >= policy.pending_tasks:
                        raise AccountError("已有多个任务处理中，请等待完成后再提交", 429)
                original_receive = receive

                async def replay():
                    return parts.pop(0) if parts else await original_receive()

                receive = replay
            scope.setdefault("state", {})["account"] = user
            if path == "/profile":
                return await JSONResponse(
                    {"id": user["id"], "name": user["username"], "role": user["role"], "account_login": True}
                )(scope, receive, secure_send)
            if application:
                application.state.operations.start()
            await (application or self.app)(scope, receive, secure_send)
        except AccountError as error:
            await JSONResponse({"detail": str(error)}, status_code=error.status_code)(scope, receive, secure_send)
