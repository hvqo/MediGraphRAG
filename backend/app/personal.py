"""Local-first browser-owned personal libraries, with isolated files, SQLite and vector indexes."""

from http.cookies import SimpleCookie
import hashlib
import json
from pathlib import Path
import secrets
import shutil
import sqlite3
import threading
from starlette.responses import JSONResponse

COOKIE = "medigraph_library"


class PersonalLibraries:
    def __init__(self, directory, factory):
        self.directory = Path(directory)
        self.factory = factory
        self.path = self.directory / "personal-libraries.json"
        self.lock = threading.RLock()
        self.apps = {}

    def resolve(self, token):
        with self.lock:
            records = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []
            digest = hashlib.sha256(token.encode()).hexdigest() if token else ""
            for record in records:
                if secrets.compare_digest(digest, record["token_hash"]):
                    return record, None
            token = secrets.token_urlsafe(32)
            identifier = secrets.token_hex(12)
            record = {
                "id": identifier,
                "name": "我的个人资料库",
                "token_hash": hashlib.sha256(token.encode()).hexdigest(),
            }
            target = self.directory / "libraries" / identifier
            target.mkdir(parents=True)
            # First local library adopts the legacy local data by a consistent copy, never a move/delete.
            if not records and (self.directory / "knowledge.sqlite3").exists():
                source = sqlite3.connect(self.directory / "knowledge.sqlite3")
                destination = sqlite3.connect(target / "knowledge.sqlite3")
                try:
                    source.backup(destination)
                finally:
                    source.close()
                    destination.close()
                if (self.directory / "settings.json").exists():
                    shutil.copy2(self.directory / "settings.json", target / "settings.json")
                if (self.directory / "uploads").exists():
                    shutil.copytree(self.directory / "uploads", target / "uploads")
            records.append(record)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.path)
            return record, token

    def app(self, record):
        with self.lock:
            if record["id"] not in self.apps:
                self.apps[record["id"]] = self.factory(self.directory / "libraries" / record["id"])
                self.apps[record["id"]].state.jobs.recover()
            return self.apps[record["id"]]


class PersonalMiddleware:
    def __init__(self, app, registry):
        self.app = app
        self.registry = registry

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] in ["/health", "/api/health"]:
            return await self.app(scope, receive, send)
        cookies = SimpleCookie()
        try:
            cookies.load(dict(scope["headers"]).get(b"cookie", b"").decode())
        except Exception:
            pass
        token = cookies[COOKIE].value if COOKIE in cookies else ""
        record, issued = self.registry.resolve(token)

        async def send_cookie(message):
            if issued and message["type"] == "http.response.start":
                message.setdefault("headers", []).append(
                    (b"set-cookie", f"{COOKIE}={issued}; HttpOnly; SameSite=Strict; Path=/; Max-Age=31536000".encode())
                )
            await send(message)

        if scope["path"] in ["/profile", "/api/profile"]:
            return await JSONResponse(
                {
                    "id": record["id"],
                    "name": record["name"],
                    "storage": "browser-owned local library",
                    "account_login": False,
                }
            )(scope, receive, send_cookie)
        application = self.registry.app(record)
        application.state.operations.start()
        await application(scope, receive, send_cookie)


async def shutdown(registry):
    for application in registry.apps.values():
        await application.state.operations.shutdown()
        await application.state.jobs.shutdown()
