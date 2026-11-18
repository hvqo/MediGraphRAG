"""Disposable in-container deployment smoke; never use real accounts or model endpoints."""

import os
import secrets
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.update(
    MEDIGRAPH_AUTH_REQUIRED="true",
    MEDIGRAPH_COOKIE_SECURE="true",
    MEDIGRAPH_DEPLOYMENT_MODE="public",
    MEDIGRAPH_PUBLIC_ORIGIN="https://container-check.invalid",
)

from fastapi.testclient import TestClient
from backend.app.main import create_app


def main():
    import faiss
    import torch
    import transformers
    import rapidocr_onnxruntime

    assert faiss and torch and transformers and rapidocr_onnxruntime
    with tempfile.TemporaryDirectory() as directory:
        app = create_app(directory, personal=True)
        password = secrets.token_urlsafe(24)
        app.state.accounts.create("container_admin", password, "admin")
        with TestClient(app, base_url="https://container-check.invalid") as client:
            assert client.get("/health").status_code == 200
            assert client.get("/").status_code == 200, "Built frontend is absent"
            assert client.get("/api/documents").status_code == 401
            response = client.post("/api/auth/login", json={"username": "container_admin", "password": password})
            assert response.status_code == 200, response.text
            assert "Secure" in response.headers["set-cookie"]
            client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
            assert client.get("/api/settings").status_code == 200
            assert client.get("/api/documents").json() == []
            assert client.post("/api/auth/logout").status_code == 200
            assert client.get("/api/documents").status_code == 401
    print("PASS: non-root image, retrieval/OCR imports, frontend, secure login and logout; no external inference")


if __name__ == "__main__":
    main()
