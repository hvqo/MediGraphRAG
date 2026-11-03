from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.app.cli import main


class CliTests(unittest.TestCase):
    def invoke(self, args):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(args), 0)
        return json.loads(output.getvalue())

    def test_regular_python_import_search_and_dry_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "fixture.txt"
            source.write_text("糖尿病是本次检索软件测试的关键词，不作为医学知识。", encoding="utf-8")
            with patch.dict(os.environ, {"MEDIGRAPH_DATA_DIR": str(root / "runtime")}):
                self.assertEqual(len(self.invoke(["import-documents", str(source), "--dry-run"])["files"]), 1)
                self.assertFalse((root / "runtime").exists())
                self.assertEqual(self.invoke(["status"])["documents"], 0)
                self.assertEqual(len(self.invoke(["import-documents", str(source)])["files"]), 1)
                self.assertEqual(self.invoke(["status"])["documents"], 1)
                self.assertEqual(len(self.invoke(["search", "糖尿病"])["items"]), 1)
