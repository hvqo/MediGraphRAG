"""Fetch a pinned Ollama registry artifact with resumable HTTPS transfers and SHA256 checks.

Useful when the Ollama downloader cannot work with the local DNS/proxy setup.
No network/security settings are changed. The manifest is published only after all blobs verify.
"""

from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
from pathlib import Path
import httpx
from asset_download import download

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True, help="Existing OLLAMA_MODELS directory")
    args = parser.parse_args()
    registry = "https://registry.ollama.ai/v2/library/qwen3-vl"
    pin_path = ROOT / "config/vision-model.json"
    if pin_path.exists():
        record = json.loads(pin_path.read_text(encoding="utf-8"))
        manifest = record["manifest"]
    else:
        response = httpx.get(registry + "/manifests/8b-instruct", timeout=60, follow_redirects=True)
        response.raise_for_status()
        manifest = response.json()
        record = {"model": "qwen3-vl:8b-instruct", "source": registry, "manifest": manifest}
        pin_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    blobs = args.directory.resolve() / "blobs"
    blobs.mkdir(parents=True, exist_ok=True)

    def fetch(item):
        digest = item["digest"]
        if not digest.startswith("sha256:") or len(digest) != 71:
            raise ValueError("Unexpected artifact digest")
        target = blobs / digest.replace(":", "-")
        partial = target.with_suffix(".download")
        if not target.exists():
            print("Downloading", digest, item["size"], flush=True)
            download(registry + "/blobs/" + digest, partial, item["size"])
            actual = partial
        else:
            actual = target
        checksum = hashlib.sha256()
        with actual.open("rb") as stream:
            for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                checksum.update(block)
        if checksum.hexdigest() != digest.split(":")[1] or actual.stat().st_size != item["size"]:
            raise ValueError("Artifact size/checksum mismatch: " + digest)
        if actual != target:
            partial.replace(target)
        print("Verified", digest, flush=True)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(fetch, [manifest["config"], *manifest["layers"]]))
    target = args.directory.resolve() / "manifests/registry.ollama.ai/library/qwen3-vl/8b-instruct"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, separators=(",", ":")), encoding="utf-8")
    temporary.replace(target)
    print("Ready: qwen3-vl:8b-instruct", flush=True)


if __name__ == "__main__":
    main()
