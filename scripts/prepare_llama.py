"""Install a pinned official Windows/CUDA llama.cpp server beside the project."""

import hashlib
import json
from pathlib import Path
import zipfile
from asset_download import download

ROOT = Path(__file__).resolve().parents[1]
VERSION = "b12359"
ASSETS = [
    (
        "llama-b12359-bin-win-cuda-12.4-x64.zip",
        318976332,
        "e9c0abf442e8339c06728366c1ad2c711332f9939c0c00603fb75d85fd44c914",
    ),
    (
        "cudart-llama-bin-win-cuda-12.4-x64.zip",
        391443627,
        "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6",
    ),
]


def main():
    tools = ROOT / ".runtime/tools"
    target = tools / ("llama-" + VERSION)
    target.mkdir(parents=True, exist_ok=True)
    for name, size, checksum in ASSETS:
        archive = tools / name
        download("https://github.com/ggml-org/llama.cpp/releases/download/" + VERSION + "/" + name, archive, size)
        digest = hashlib.sha256()
        with archive.open("rb") as stream:
            for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != checksum:
            raise ValueError("Official release checksum mismatch: " + name)
        with zipfile.ZipFile(archive) as bundle:
            for item in bundle.infolist():
                if not (target / item.filename).resolve().is_relative_to(target.resolve()):
                    raise ValueError("Unsafe archive path")
            bundle.extractall(target)
        print("Verified and installed", name, flush=True)
    (target / "source.json").write_text(json.dumps({"version": VERSION, "assets": ASSETS}, indent=2), encoding="utf-8")
    print("llama.cpp ready:", target, flush=True)


if __name__ == "__main__":
    main()
