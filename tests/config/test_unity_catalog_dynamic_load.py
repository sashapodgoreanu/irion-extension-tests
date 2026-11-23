"""Check that Unity Catalog's runtime adaptation never changes SQL assertions."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/prepare-unity-catalog-dv-test.py"

spec = importlib.util.spec_from_file_location("unity_dv_loader", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class UnityCatalogDynamicLoadTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.test = Path(self.temporary.name) / "dv_decode.test"
        self.original = (
            "# Dynamic signed extension compatibility\n"
            "require unity_catalog\n"
            "require-env DV_TRAILING_SIZE\n"
            "\n"
            "# SQL assertions must be preserved verbatim.\n"
            "query I\n"
            "SELECT count(*) FROM uc_read_deletion_vector('some-file.dv');\n"
            "----\n0\n"
        )
        self.test.write_text(self.original, encoding="utf-8")

    def test_load_is_inserted_without_changing_assertions(self) -> None:
        self.assertTrue(module.adapt(self.test))
        actual = self.test.read_text(encoding="utf-8")
        self.assertIn("statement ok\nLOAD unity_catalog;\n", actual)
        self.assertIn("query I\nSELECT count(*) FROM uc_read_deletion_vector('some-file.dv');\n----\n0\n", actual)
        self.assertEqual(actual.count("LOAD unity_catalog;"), 1)
        self.assertFalse(module.adapt(self.test))
        self.assertEqual(actual, self.test.read_text(encoding="utf-8"))

    def test_fails_closed_when_expected_requirement_is_missing(self) -> None:
        self.test.write_text(self.original.replace("require-env DV_TRAILING_SIZE\n", ""), encoding="utf-8")
        with self.assertRaisesRegex(module.AdaptationError, "DV_TRAILING_SIZE"):
            module.adapt(self.test)


if __name__ == "__main__":
    unittest.main()
