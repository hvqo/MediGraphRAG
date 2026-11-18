"""Persistent accounts, Argon2 passwords and revocable opaque sessions."""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from urllib.parse import urlsplit
import uuid

from .llm import ModelError

SESSION_COOKIE = "medigraph_session"


class AccountError(ValueError):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


def flag(name, default=False):
    raw = os.getenv(name, str(default)).strip().lower()
    if raw not in {"true", "false", "1", "0", "yes", "no"}:
        raise ValueError(f"{name}必须为true或false")
    return raw in {"true", "1", "yes"}


@dataclass
class AccountPolicy:
    required: bool
    secure_cookie: bool = True
    registration_enabled: bool = True
    public_origin: str = ""
    session_seconds: int = 604800
    request_bytes: int = 50 * 1024 * 1024
    storage_bytes: int = 512 * 1024 * 1024
    model_calls_per_day: int = 200
    pending_tasks: int = 3
    requests_per_minute: int = 300

    @classmethod
    def environment(cls, required=None):
        policy = cls(
            required=flag("MEDIGRAPH_AUTH_REQUIRED") if required is None else required,
            secure_cookie=flag("MEDIGRAPH_COOKIE_SECURE", True),
            registration_enabled=flag("MEDIGRAPH_ALLOW_REGISTRATION", True),
            public_origin=os.getenv("MEDIGRAPH_PUBLIC_ORIGIN", "").rstrip("/"),
            session_seconds=int(os.getenv("MEDIGRAPH_SESSION_SECONDS", "604800")),
            request_bytes=int(os.getenv("MEDIGRAPH_MAX_REQUEST_MB", "50")) * 1024 * 1024,
            storage_bytes=int(os.getenv("MEDIGRAPH_STORAGE_MB", "512")) * 1024 * 1024,
            model_calls_per_day=int(os.getenv("MEDIGRAPH_MODEL_CALLS_PER_DAY", "200")),
            pending_tasks=int(os.getenv("MEDIGRAPH_MAX_PENDING_TASKS", "3")),
            requests_per_minute=int(os.getenv("MEDIGRAPH_REQUESTS_PER_MINUTE", "300")),
        )
        if (
            min(
                policy.session_seconds,
                policy.request_bytes,
                policy.storage_bytes,
                policy.model_calls_per_day,
                policy.pending_tasks,
                policy.requests_per_minute,
            )
            <= 0
        ):
            raise ValueError("账号有效期和配额必须大于0")
        if policy.public_origin:
            value = urlsplit(policy.public_origin)
            if (
                value.scheme not in {"http", "https"}
                or not value.netloc
                or value.path
                or value.query
                or value.fragment
                or value.username
            ):
                raise ValueError("MEDIGRAPH_PUBLIC_ORIGIN必须是完整网站来源，不能带路径或凭据")
        if os.getenv("MEDIGRAPH_DEPLOYMENT_MODE") == "public":
            if not policy.required or not policy.secure_cookie or not policy.public_origin.startswith("https://"):
                raise ValueError("公网模式必须启用登录、Secure Cookie，并填写HTTPS网站来源")
        return policy


class AccountStore:
    def __init__(self, directory, policy):
        from pwdlib import PasswordHash

        self.directory, self.policy = Path(directory), policy
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "accounts.sqlite3"
        self.passwords = PasswordHash.recommended()
        self.dummy_hash = self.passwords.hash(secrets.token_urlsafe(24))
        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS users(
                  id TEXT PRIMARY KEY, username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                  password_hash TEXT NOT NULL, library_id TEXT NOT NULL UNIQUE,
                  role TEXT NOT NULL CHECK(role IN ('user','admin')),
                  disabled INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions(
                  token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                  csrf_token TEXT NOT NULL, expires_at INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
                CREATE TABLE IF NOT EXISTS account_counters(
                  key TEXT PRIMARY KEY,count INTEGER NOT NULL,expires_at INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS counters_expiry ON account_counters(expires_at);
            """)
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def public(row):
        return {k: row[k] for k in ("id", "username", "role", "disabled", "created_at")}

    def create(self, username, password, role="user"):
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{2,31}", username) or not 12 <= len(password) <= 128:
            raise AccountError("账号需3–32位字母、数字或._-，密码需12–128位", 422)
        if role not in {"user", "admin"}:
            raise AccountError("账号角色无效", 422)
        digest = self.passwords.hash(password)
        identifier, library = uuid.uuid4().hex, uuid.uuid4().hex
        with self.connect() as connection:
            try:
                connection.execute(
                    "INSERT INTO users VALUES (?,?,?,?,?,0,?)",
                    (identifier, username, digest, library, role, int(time.time())),
                )
            except sqlite3.IntegrityError:
                raise AccountError("该账号已被使用", 409) from None
        return self.user(identifier)

    def user(self, identifier):
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id,username,library_id,role,disabled,created_at FROM users WHERE id=?", (identifier,)
            ).fetchone()
        if not row:
            raise AccountError("账号不存在", 404)
        return dict(row)

    def login(self, username, password):
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        valid = self.passwords.verify(password, row["password_hash"] if row else self.dummy_hash)
        if not row or not valid or row["disabled"]:
            raise AccountError("账号或密码错误，或账号已停用", 401)
        return self.issue(row["id"])

    def issue(self, identifier):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.connect() as connection:
            connection.execute("DELETE FROM sessions WHERE expires_at<=?", (int(time.time()),))
            connection.execute(
                "INSERT INTO sessions VALUES (?,?,?,?)",
                (
                    hashlib.sha256(token.encode()).hexdigest(),
                    identifier,
                    csrf,
                    int(time.time()) + self.policy.session_seconds,
                ),
            )
        return token, {"user": self.public(self.user(identifier)), "csrf_token": csrf}

    def session(self, token):
        if not token or len(token) > 128:
            return None
        with self.connect() as connection:
            row = connection.execute(
                """SELECT u.id,u.username,u.role,u.library_id,u.disabled,u.created_at,s.csrf_token
                FROM sessions s JOIN users u ON u.id=s.user_id
                WHERE s.token_hash=? AND s.expires_at>? AND u.disabled=0""",
                (hashlib.sha256(token.encode()).hexdigest(), int(time.time())),
            ).fetchone()
        return dict(row) if row else None

    def logout(self, token):
        with self.connect() as connection:
            connection.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))

    def password(self, identifier, new_password, current_password=None):
        if not 12 <= len(new_password) <= 128:
            raise AccountError("新密码需12–128位", 422)
        new_hash = self.passwords.hash(new_password)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT password_hash FROM users WHERE id=?", (identifier,)).fetchone()
            if not row:
                raise AccountError("账号不存在", 404)
            if current_password is not None and not self.passwords.verify(current_password, row["password_hash"]):
                raise AccountError("当前密码不正确", 400)
            connection.execute("UPDATE users SET password_hash=? WHERE id=?", (new_hash, identifier))
            connection.execute("DELETE FROM sessions WHERE user_id=?", (identifier,))

    def disable(self, identifier, disabled, actor):
        if identifier == actor:
            raise AccountError("不能停用自己的账号")
        self.user(identifier)
        with self.connect() as connection:
            connection.execute("UPDATE users SET disabled=? WHERE id=?", (int(disabled), identifier))
            if disabled:
                connection.execute("DELETE FROM sessions WHERE user_id=?", (identifier,))

    def list_users(self):
        with self.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT id,username,role,disabled,created_at FROM users ORDER BY created_at,id"
                )
            ]

    @staticmethod
    def counter(connection, key, limit, seconds):
        now = int(time.time())
        window = now // seconds
        key = f"{key}:{window}"
        row = connection.execute("SELECT count FROM account_counters WHERE key=?", (key,)).fetchone()
        if row and row["count"] >= limit:
            raise AccountError("请求过于频繁或已达到本周期额度，请稍后再试", 429)
        connection.execute("DELETE FROM account_counters WHERE expires_at<?", (now,))
        connection.execute(
            "INSERT INTO account_counters VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1",
            (key, (window + 1) * seconds),
        )

    def hit(self, key, limit, seconds):
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.counter(connection, key, limit, seconds)

    def charge(self, library_id):
        try:
            with self.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                user = connection.execute("SELECT id,disabled FROM users WHERE library_id=?", (library_id,)).fetchone()
                if not user or user["disabled"]:
                    raise AccountError("账号已停用，无法继续调用模型", 403)
                self.counter(connection, "model:" + user["id"], self.policy.model_calls_per_day, 86400)
        except AccountError as error:
            raise ModelError(str(error), status_code=error.status_code) from None

    def usage(self, identifier):
        key = f"model:{identifier}:{int(time.time()) // 86400}"
        with self.connect() as connection:
            row = connection.execute("SELECT count FROM account_counters WHERE key=?", (key,)).fetchone()
        return {
            "model_calls_today": row["count"] if row else 0,
            "model_calls_per_day": self.policy.model_calls_per_day,
            "storage_mb": self.policy.storage_bytes // (1024 * 1024),
            "reset_timezone": "UTC",
        }
