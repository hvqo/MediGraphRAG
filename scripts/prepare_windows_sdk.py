"""Build the official Volcengine SDK from a short path on Windows."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import urllib.request

repo = Path(__file__).resolve().parents[1]
wheels = repo / ".environment-wheels"
wheels.mkdir(exist_ok=True)
with urllib.request.urlopen("https://pypi.org/pypi/volcengine-python-sdk/1.0.130/json") as response:
    metadata = json.load(response)
source = next(item for item in metadata["urls"] if item["packagetype"] == "sdist")
archive_path = wheels / source["filename"]
if not archive_path.exists():
    urllib.request.urlretrieve(source["url"], archive_path)
assert hashlib.sha256(archive_path.read_bytes()).hexdigest() == source["digests"]["sha256"]
build = repo.parent.parent / ".sdk"
build.mkdir(exist_ok=True)
build = build.resolve()
with tarfile.open(archive_path) as archive:
    for member in archive.getmembers():
        parts = Path(member.name).parts[1:]
        if not parts:
            continue
        if not build.joinpath(*parts).resolve().is_relative_to(build) or member.issym() or member.islnk():
            raise ValueError("Unsafe source archive path")
        member.name = str(Path(*parts))
        archive.extract(member, build)
subprocess.run(
    [sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", str(build), "--wheel-dir", str(wheels)],
    check=True,
)
