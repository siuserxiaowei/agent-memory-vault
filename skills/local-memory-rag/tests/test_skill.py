from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]


class PackagedSkillTests(unittest.TestCase):
    def test_self_contained_runtime_and_fixed_entry_exist(self) -> None:
        required = (
            "requirements.txt",
            "scripts/run.ps1",
            "scripts/manage.py",
            "scripts/server.py",
            "scripts/client.py",
            "scripts/agent_memory_env.py",
            "scripts/agent_memory_index.py",
            "scripts/agent_memory_search.py",
            "scripts/agent_memory_zvec_index.py",
        )
        for relative in required:
            with self.subTest(relative=relative):
                self.assertTrue((SKILL_ROOT / relative).is_file())

    def test_standalone_server_selects_the_skill_as_runtime_root(self) -> None:
        path = SKILL_ROOT / "scripts" / "server.py"
        spec = importlib.util.spec_from_file_location("packaged_server_test", path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules["packaged_server_test"] = module
        spec.loader.exec_module(module)
        self.assertEqual(module.default_runtime_root(), SKILL_ROOT.resolve())


if __name__ == "__main__":
    unittest.main()
