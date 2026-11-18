import asyncio
import hashlib
import tempfile
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient
from backend.app.accounts import AccountPolicy, SESSION_COOKIE
from backend.app.main import create_app
from backend.app.llm import ModelError


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.contexts = ExitStack()
        self.addCleanup(self.contexts.close)
        self.directory = Path(self.temporary.name)
        self.policy = AccountPolicy(required=True, secure_cookie=False)
        self.app = create_app(self.directory, personal=True, account_policy=self.policy)
        self.client = self.contexts.enter_context(TestClient(self.app))

    def register(self, name="alice", client=None):
        target = client or self.client
        response = target.post("/api/auth/register", json={"username": name, "password": "test-password-12345"})
        self.assertEqual(response.status_code, 200, response.text)
        target.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        return response.json()["user"]

    def device(self):
        client = TestClient(self.app)
        client.portal = self.client.portal
        self.addCleanup(client.close)
        return client

    def test_public_gate_no_guest_adoption_and_hashes(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        self.assertFalse(self.client.get("/api/auth/status").json()["user"])
        self.assertEqual(self.client.get("/api/documents").status_code, 401)
        self.assertEqual(self.client.get("/docs").status_code, 401)
        self.assertFalse((self.directory / "personal-libraries.json").exists())
        self.app.state.documents.add("private.txt", b"legacy root private data")
        self.register()
        self.assertEqual(self.client.get("/api/documents").json(), [])
        with self.app.state.accounts.connect() as connection:
            row = connection.execute("SELECT password_hash FROM users").fetchone()
            self.assertTrue(row[0].startswith("$argon2id$"))
            token_hash = connection.execute("SELECT token_hash FROM sessions").fetchone()[0]
            self.assertEqual(token_hash, hashlib.sha256(self.client.cookies[SESSION_COOKIE].encode()).hexdigest())

    def test_two_accounts_and_second_device_isolation(self):
        self.register()
        response = self.client.post(
            "/api/documents/text", json={"title": "我的资料", "text": "高血压需要长期随访管理。"}
        )
        self.assertEqual(response.status_code, 201, response.text)
        identifier = response.json()["id"]
        bob = self.device()
        self.register("bob", bob)
        self.assertEqual(bob.get("/api/documents").json(), [])
        self.assertEqual(bob.get(f"/api/documents/{identifier}/source").status_code, 404)
        self.assertEqual(bob.delete(f"/api/documents/{identifier}").status_code, 404)
        device = self.device()
        login = device.post("/api/auth/login", json={"username": "ALICE", "password": "test-password-12345"})
        self.assertEqual(login.status_code, 200)
        self.assertEqual(device.get("/api/documents").json()[0]["id"], identifier)

    def test_csrf_origin_and_role_forgery(self):
        self.assertEqual(
            self.client.post(
                "/auth/login",
                headers={"Origin": "https://evil.example"},
                json={"username": "alice", "password": "test-password-12345"},
            ).status_code,
            403,
        )
        self.register()
        self.assertEqual(self.client.get("/settings").status_code, 403)
        self.assertEqual(self.client.post("/graph/neo4j", json={}).status_code, 403)
        self.assertEqual(self.client.get("/auth/admin/users", headers={"X-Role": "admin"}).status_code, 403)
        self.assertEqual(self.client.post("/auth/logout", headers={"X-CSRF-Token": "wrong"}).status_code, 403)
        self.assertEqual(
            self.client.post(
                "/auth/register", json={"username": "hacker", "password": "test-password-12345", "role": "admin"}
            ).status_code,
            422,
        )

    def test_logout_password_change_and_expiry(self):
        user = self.register()
        old_token = self.client.cookies[SESSION_COOKIE]
        response = self.client.post(
            "/auth/password", json={"current_password": "test-password-12345", "new_password": "a-new-password-12345"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/documents").status_code, 401)
        response = self.client.post("/auth/login", json={"username": "alice", "password": "a-new-password-12345"})
        self.client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        self.assertNotEqual(old_token, self.client.cookies[SESSION_COOKIE])
        self.assertEqual(self.client.post("/auth/logout").status_code, 200)
        self.assertEqual(self.client.get("/documents").status_code, 401)
        token, _ = self.app.state.accounts.issue(user["id"])
        with self.app.state.accounts.connect() as connection:
            connection.execute("UPDATE sessions SET expires_at=?", (int(time.time()) - 1,))
        self.assertIsNone(self.app.state.accounts.session(token))

    def test_admin_disable_reset_and_shared_settings(self):
        alice = self.register()
        store = self.app.state.accounts
        store.create("owner", "admin-password-12345", "admin")
        admin = self.device()
        response = admin.post("/auth/login", json={"username": "owner", "password": "admin-password-12345"})
        admin.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        self.assertEqual(admin.get("/settings").status_code, 200)
        self.assertEqual(len(admin.get("/auth/admin/users").json()), 2)
        self.assertEqual(admin.put(f"/auth/admin/users/{alice['id']}", json={"disabled": True}).status_code, 200)
        self.assertEqual(self.client.get("/documents").status_code, 401)
        admin.put(f"/auth/admin/users/{alice['id']}", json={"disabled": False})
        self.assertEqual(
            admin.post(
                f"/auth/admin/users/{alice['id']}/password", json={"password": "reset-password-12345"}
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post("/auth/login", json={"username": "alice", "password": "test-password-12345"}).status_code,
            401,
        )
        response = self.client.post("/auth/login", json={"username": "alice", "password": "reset-password-12345"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            all(a.state.settings is self.app.state.settings for a in self.app.state.libraries.apps.values())
        )

    def test_limits_and_budget_snapshot(self):
        user = self.register()
        self.policy.request_bytes = 20
        self.assertEqual(self.client.post("/documents/text", content=b"x" * 21).status_code, 413)
        self.policy.request_bytes = 1024
        self.policy.storage_bytes = 1
        self.assertEqual(self.client.post("/documents/text", json={"title": "test", "text": "test"}).status_code, 413)
        self.policy.model_calls_per_day = 1
        library = self.app.state.accounts.user(user["id"])["library_id"]
        model = self.app.state.libraries.app({"id": library}).state.model.snapshot("vision")
        with patch.object(model, "_json", new=AsyncMock(return_value={"ok": True})) as call:
            self.assertEqual(asyncio.run(model.json("system", "prompt")), {"ok": True})
            with self.assertRaises(ModelError) as caught:
                asyncio.run(model.json("system", "prompt"))
            self.assertEqual(caught.exception.status_code, 429)
            self.assertEqual(call.call_count, 1)
        self.assertEqual(self.client.get("/auth/usage").json()["model_calls_today"], 1)

    def test_registration_switch_and_login_limit(self):
        self.policy.registration_enabled = False
        self.assertEqual(
            self.client.post(
                "/auth/register", json={"username": "alice", "password": "test-password-12345"}
            ).status_code,
            403,
        )
        self.policy.registration_enabled = True
        self.register()
        for _ in range(10):
            self.assertEqual(
                self.client.post(
                    "/auth/login", json={"username": "alice", "password": "wrong-password-123"}
                ).status_code,
                401,
            )
        self.assertEqual(
            self.client.post("/auth/login", json={"username": "alice", "password": "test-password-12345"}).status_code,
            429,
        )

    def test_public_configuration_refuses_insecure_defaults(self):
        with patch.dict(
            "os.environ",
            {"MEDIGRAPH_DEPLOYMENT_MODE": "public", "MEDIGRAPH_PUBLIC_ORIGIN": "", "MEDIGRAPH_AUTH_REQUIRED": "false"},
        ):
            with self.assertRaises(ValueError):
                AccountPolicy.environment()
