import tempfile
import unittest
from pathlib import Path

from scripts.core import runtime_config
from scripts.ctfd import opencode_adapter


class RuntimePortabilityTests(unittest.TestCase):
    def test_repo_root_matches_workspace(self):
        root = runtime_config.repo_root()
        self.assertTrue((root / "scripts").exists())
        self.assertTrue((root / "docs").exists())

    def test_default_opencode_config_is_repo_relative(self):
        cfg = runtime_config.default_opencode_config_path()
        self.assertEqual(cfg, runtime_config.repo_root() / ".opencode" / "opencode.json")

    def test_default_vlm_base_is_localhost(self):
        value = runtime_config.default_vlm_base_url()
        self.assertTrue(value.startswith("http://"))
        self.assertTrue(value.endswith("/v1"))

    def test_find_session_record_returns_none_for_missing_db(self):
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "missing.db"
            hit = opencode_adapter.find_opencode_session_record(title="x", db_path=missing)
            self.assertIsNone(hit)


if __name__ == "__main__":
    unittest.main()
