"""Download original research benchmarks and pinned real embedding checkpoints, never execute downloaded code."""

import hashlib
import json
import os
from pathlib import Path
import zipfile
import httpx

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".runtime/medical-data"


def fetch(url, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with httpx.Client(follow_redirects=True, timeout=120, trust_env=False) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                with path.with_suffix(path.suffix + ".partial").open("wb") as output:
                    for data in response.iter_bytes():
                        output.write(data)
        path.with_suffix(path.suffix + ".partial").replace(path)
    return {"url": url, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}


def main():
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = "120"
    from huggingface_hub import snapshot_download

    CACHE.mkdir(parents=True, exist_ok=True)
    manifest = {}
    pinned = json.loads((ROOT / "benchmarks/assets-manifest.json").read_text(encoding="utf-8"))
    for name, url in [
        ("nfcorpus.zip", "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/nfcorpus.zip"),
        ("ori_pqal.json", "https://raw.githubusercontent.com/pubmedqa/pubmedqa/master/data/ori_pqal.json"),
    ]:
        manifest[name] = fetch(url, CACHE / name)
        if manifest[name]["sha256"] != pinned[name]["sha256"]:
            raise ValueError("Data checksum mismatch: " + name)
        print(name, manifest[name], flush=True)
    with zipfile.ZipFile(CACHE / "nfcorpus.zip") as archive:
        for item in archive.infolist():
            target = (CACHE / item.filename).resolve()
            if not target.is_relative_to(CACHE.resolve()):
                raise ValueError("Unsafe archive member")
            archive.extract(item, CACHE)
    for repo, metadata in pinned.items():
        if "weights" not in metadata:
            continue
        name = repo.rsplit("/", 1)[-1]
        directory = ROOT / ".runtime/models" / name
        weights = metadata["weights"]
        snapshot_download(
            repo,
            revision=metadata["revision"],
            local_dir=directory,
            allow_patterns=[
                weights,
                "config.json",
                "tokenizer.json",
                "tokenizer_config.json",
                "special_tokens_map.json",
                "vocab.txt",
                "README.md",
                "LICENSE",
            ],
            max_workers=3,
        )
        manifest[repo] = {
            "revision": metadata["revision"],
            "weights": weights,
            "sha256": hashlib.sha256((directory / weights).read_bytes()).hexdigest(),
            "bytes": (directory / weights).stat().st_size,
        }
        if manifest[repo]["sha256"] != metadata["sha256"]:
            raise ValueError("Checkpoint checksum mismatch: " + repo)
        print(repo, manifest[repo], flush=True)
        (CACHE / "download-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    dataset = pinned["mteb/MedicalRetrieval"]
    directory = CACHE / "medicalretrieval"
    snapshot_download(
        "mteb/MedicalRetrieval",
        repo_type="dataset",
        revision=dataset["revision"],
        local_dir=directory,
        allow_patterns=list(dataset["files"]),
    )
    for name, expected in dataset["files"].items():
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected["sha256"]:
            raise ValueError("Dataset checksum mismatch: " + name)
    manifest["mteb/MedicalRetrieval"] = dataset
    (CACHE / "download-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
