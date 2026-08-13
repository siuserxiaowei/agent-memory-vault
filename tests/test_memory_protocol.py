from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "skills/local-memory-rag/scripts/protocol.py"


def load_protocol():
    spec = importlib.util.spec_from_file_location("memory_protocol_test", PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MemoryProtocolTests(unittest.TestCase):
    def test_packet_marks_stale_and_conflicting_evidence(self):
        protocol = load_protocol()
        packet = protocol.build_answer_packet(
            "发布边界",
            {
                "mode": "hybrid",
                "degraded": False,
                "results": [
                    {"citation": "项目/决策旧.md", "title": "发布边界", "snippet": "只允许内测", "project_id": "demo", "status": "active", "verified_at": "2025-01-01", "has_open_loop": True, "sources": ["sqlite"]},
                    {"citation": "项目/决策新.md", "title": "发布边界", "snippet": "允许公开发布", "project_id": "demo", "status": "active", "verified_at": "2026-08-10", "sources": ["sqlite", "zvec"]},
                ],
                "warnings": [],
            },
            as_of="2026-08-13",
            max_age_days=30,
        )
        self.assertEqual(packet["confidence"], "medium")
        self.assertEqual(packet["protocol"]["version"], "1.1")
        self.assertEqual(packet["recommended_action"], "verify_conflicts")
        self.assertEqual(packet["evidence"][1]["evidence_grade"], "A")
        self.assertEqual(len(packet["conflicts"]), 1)
        self.assertEqual(len(packet["stale_evidence"]), 1)
        self.assertEqual(len(packet["open_loops"]), 1)
        self.assertIn("冲突", " ".join(packet["uncertainties"]))
        self.assertIn("先解决冲突", packet["next_steps"][0])

    def test_packet_is_explicit_when_nothing_was_found(self):
        protocol = load_protocol()
        packet = protocol.build_answer_packet("不存在的事实", {"results": [], "mode": "keyword_fallback", "degraded": True})
        self.assertEqual(packet["confidence"], "low")
        self.assertEqual(packet["recommended_action"], "refine_query")
        self.assertEqual(packet["evidence"], [])
        self.assertIn("不能据此下结论", packet["uncertainties"][0])
        self.assertEqual(packet["next_steps"], ["补充更具体的项目名、日期或决策关键词后重新检索。"])


if __name__ == "__main__":
    unittest.main()
