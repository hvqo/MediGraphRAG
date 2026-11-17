"""Adopt the prepared local server for default local profiles; preserve custom providers and keys."""

from datetime import datetime
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.config import SettingsStore, SettingsUpdate
from backend.app.storage import Database
from backend.app.retrieval import Retriever


def main():
    runtime = json.loads((ROOT / ".runtime/local-inference.json").read_text(encoding="utf-8-sig"))
    directories = [ROOT / ".runtime", *sorted((ROOT / ".runtime/libraries").glob("*"))]
    configured, indexed = 0, 0
    for directory in directories:
        if not directory.is_dir():
            continue
        store = SettingsStore(directory)
        raw = store._read().get("settings", {})
        settings = store.get().model_dump()
        if store.path.exists():
            backup = store.path.with_name(
                "settings.before-local-upgrade-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".json"
            )
            shutil.copy2(store.path, backup)
        if (
            settings["provider"] == "ollama"
            and settings["ollama_model"] in ("qwen2.5", "qwen2.5:latest", "qwen2.5:7b")
            and settings["ollama_base_url"] in ("http://127.0.0.1:11434", "http://localhost:11434")
        ):
            settings.update(provider="openai", cloud_base_url=runtime["base_url"], cloud_model=runtime["model"])
        if not raw.get("vision_model") or raw.get("vision_model") == "qwen2.5vl:7b":
            settings.update(
                vision_provider="openai", vision_base_url=runtime["base_url"], vision_model=runtime["model"]
            )
        settings.update(
            embedding_model="auto",
            use_vectors=True,
            use_reranker=(ROOT / ".runtime/models/bge-reranker-v2-m3/model.safetensors").exists(),
        )
        store.update(SettingsUpdate.model_validate(settings))
        configured += 1
        if (directory / "knowledge.sqlite3").exists():
            db = Database(directory)
            if db.chunks():
                Retriever(db, store).build()
                indexed += 1
    print(
        f"Configured {configured} local stores, rebuilt {indexed} indexes; saved settings backups; custom generation endpoints/credentials preserved."
    )


if __name__ == "__main__":
    main()
