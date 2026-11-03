"""Check source layout, Python syntax and complete notebook-source recovery."""

import ast
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    paths = (
        subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT)
        .decode("utf-8")
        .split("\0")
    )
    python_count, vue_count = 0, 0
    for name in sorted(set(paths)):
        if not name:
            continue
        path = ROOT / name
        if not path.is_file():
            continue
        if path.suffix == ".ipynb":
            raise SystemExit(f"Notebook files are not part of the source layout: {name}")
        if path.suffix == ".py":
            text = path.read_text(encoding="utf-8")
            compile(text, name, "exec")
            ast.parse(text)
            python_count += 1
        if path.suffix == ".vue":
            vue_count += 1
    for required in ["backend/app/main.py", "backend/app/cli.py", "frontend/src/App.vue", "pyproject.toml"]:
        if not (ROOT / required).is_file():
            raise SystemExit(f"Missing maintained source entry: {required}")
    subprocess.run([sys.executable, str(ROOT / "scripts/convert_legacy_notebooks.py")], cwd=ROOT, check=True)
    print(f"Source check passed: {python_count} Python files, {vue_count} Vue files, zero notebooks.")


if __name__ == "__main__":
    main()
