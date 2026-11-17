"""Resumable chunked HTTPS downloads for large official model assets."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
import subprocess


def download(url, target, size):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size == size:
        return
    if size < 256 * 1024 * 1024:
        subprocess.run(
            [
                "curl.exe",
                "--fail",
                "--location",
                "--silent",
                "--show-error",
                "--retry",
                "3",
                "--retry-all-errors",
                "--connect-timeout",
                "20",
                "--speed-limit",
                "1024",
                "--speed-time",
                "60",
                "--output",
                str(target),
                url,
            ],
            check=True,
        )
        return
    block = 256 * 1024 * 1024
    directory = target.with_name(target.name + ".parts")
    directory.mkdir(exist_ok=True)
    count = (size + block - 1) // block
    # Reuse complete chunks from an interrupted sequential transfer.
    if target.exists():
        with target.open("rb") as source:
            for number in range(min(count, target.stat().st_size // block)):
                piece = directory / str(number)
                if not piece.exists():
                    piece.write_bytes(source.read(block))
                else:
                    source.seek(block, 1)

    def part(number):
        start, end = number * block, min(size, (number + 1) * block) - 1
        piece = directory / str(number)
        if not piece.exists() or piece.stat().st_size != end - start + 1:
            subprocess.run(
                [
                    "curl.exe",
                    "--fail",
                    "--location",
                    "--silent",
                    "--show-error",
                    "--retry",
                    "3",
                    "--retry-all-errors",
                    "--connect-timeout",
                    "20",
                    "--speed-limit",
                    "1024",
                    "--speed-time",
                    "60",
                    "--range",
                    f"{start}-{end}",
                    "--output",
                    str(piece),
                    url,
                ],
                check=True,
            )
        if piece.stat().st_size != end - start + 1:
            raise ValueError("The official host did not return the requested byte range")
        print(f"Downloaded {number + 1}/{count} chunks: {target.name}", flush=True)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(part, range(count)))
    with target.open("wb") as output:
        for number in range(count):
            with (directory / str(number)).open("rb") as source:
                shutil.copyfileobj(source, output, length=8 * 1024 * 1024)
