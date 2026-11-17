"""Prepare modern BGE checkpoints without changing Python or legacy benchmark assets."""

import hashlib
import json
import os
from pathlib import Path
import argparse
from asset_download import download

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--models", nargs="+", choices=["bge-m3", "bge-reranker-v2-m3"], default=["bge-m3", "bge-reranker-v2-m3"]
    )
    args = parser.parse_args()
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = "120"
    from huggingface_hub import HfApi, snapshot_download

    records = {}
    manifest_path = ROOT / "config/retrieval-models.json"
    pinned = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    for name in args.models:
        repo = "BAAI/" + name
        info = HfApi().model_info(repo, revision=pinned.get(repo, {}).get("revision"), files_metadata=True)
        revision = pinned.get(repo, {}).get("revision") or info.sha
        directory = ROOT / ".runtime/models" / name
        weight_name = "pytorch_model.bin" if name == "bge-m3" else "model.safetensors"
        snapshot_download(
            repo,
            revision=revision,
            local_dir=directory,
            allow_patterns=[
                "config.json",
                "tokenizer*.json",
                "special_tokens_map.json",
                "sentencepiece.bpe.model",
                "README.md",
                "LICENSE",
            ],
            max_workers=3,
        )
        weights = directory / weight_name
        artifact = next(f for f in info.siblings if f.rfilename == weight_name)
        if not weights.exists():
            partial = weights.with_suffix(weights.suffix + ".download")
            download(f"https://huggingface.co/{repo}/resolve/{revision}/{weight_name}", partial, artifact.size)
            actual = partial
        else:
            actual = weights
        digest = hashlib.sha256()
        with actual.open("rb") as stream:
            for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                digest.update(block)
        sha = digest.hexdigest()
        if sha != artifact.lfs.sha256:
            raise ValueError("Official LFS checksum mismatch: " + repo)
        if repo in pinned and pinned[repo].get("sha256") != sha:
            raise ValueError("Model checksum mismatch: " + repo)
        if actual != weights:
            actual.replace(weights)
        records[repo] = {"revision": revision, "weights": weight_name, "sha256": sha, "bytes": weights.stat().st_size}
        print(repo, json.dumps(records[repo]), flush=True)
    manifest_path.write_text(json.dumps({**pinned, **records}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
