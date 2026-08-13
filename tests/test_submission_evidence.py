from __future__ import annotations

import hashlib
import io
import re
import struct
import unittest
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SUBMISSION_ROOT = REPO_ROOT / "submission"
EVIDENCE_ROOT = SUBMISSION_ROOT / "assets" / "evidence"
EXPECTED_EVIDENCE = {
    "qoder-local-memory-rag-operations.png": (
        "751cb9381e4508d4bca04202c79a550cb2968bc7ed78b46f68de7f514d43e9e7"
    ),
    "qoder-local-memory-rag-success.png": (
        "d3e843b02bc0eec89318bbca9f8108e4de417a084150aecf29bacb16aabf18f6"
    ),
}
FORBIDDEN_PERSON_IDENTIFIER_SHA256 = {
    "person-name": "fe672956d62c2de053986d1c1021b0787dde9cd3f16dd98c65aaba6ba705631b",
    "person-account": "0150fde5ce19785699480c46b7f3e470df71b27004e2569d489d3db2d97dae06",
}


class SubmissionEvidenceTests(unittest.TestCase):
    def test_public_submission_and_skill_archive_exclude_other_person_identifiers(self) -> None:
        public_roots = (
            REPO_ROOT / "README.md",
            REPO_ROOT / "LICENSE",
            REPO_ROOT / "skills" / "local-memory-rag",
            SUBMISSION_ROOT,
        )
        public_text = []
        for root in public_roots:
            paths = [root] if root.is_file() else root.rglob("*")
            for path in paths:
                if not path.is_file() or path.suffix.lower() in {".png", ".pyc"}:
                    continue
                public_text.append(path.read_text(encoding="utf-8", errors="ignore"))

        archive = REPO_ROOT / "dist" / "local-memory-rag.zip"
        with zipfile.ZipFile(io.BytesIO(archive.read_bytes())) as packaged:
            for name in packaged.namelist():
                public_text.append(packaged.read(name).decode("utf-8", errors="ignore"))

        tokens = set()
        for text in public_text:
            tokens.update(
                token.lower()
                for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", text)
            )
        token_hashes = {hashlib.sha256(token.encode()).hexdigest() for token in tokens}
        for label, forbidden_hash in FORBIDDEN_PERSON_IDENTIFIER_SHA256.items():
            with self.subTest(label=label):
                self.assertNotIn(forbidden_hash, token_hashes)

    def test_qoder_evidence_images_are_fixed_public_pngs(self) -> None:
        for name, expected_hash in EXPECTED_EVIDENCE.items():
            with self.subTest(name=name):
                path = EVIDENCE_ROOT / name
                data = path.read_bytes()
                self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
                self.assertEqual(hashlib.sha256(data).hexdigest(), expected_hash)
                width, height = struct.unpack(">II", data[16:24])
                self.assertEqual((width, height), (1152, 768))
                self.assertNotIn(b"/Users/", data)
                self.assertNotIn(b"LOCAL_MEMORY_RAG_TOKEN", data)

    def test_article_and_evidence_manifest_reference_both_images(self) -> None:
        article = (SUBMISSION_ROOT / "ARTICLE.md").read_text(encoding="utf-8")
        manifest = (SUBMISSION_ROOT / "HOST_EVIDENCE.md").read_text(encoding="utf-8")
        for name, expected_hash in EXPECTED_EVIDENCE.items():
            with self.subTest(name=name):
                self.assertIn(f"assets/evidence/{name}", article)
                self.assertIn(f"assets/evidence/{name}", manifest)
                self.assertIn(expected_hash, manifest)

    def test_submission_no_longer_claims_qoder_is_blocked(self) -> None:
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                SUBMISSION_ROOT / "ARTICLE.md",
                SUBMISSION_ROOT / "CONTEST_REQUIREMENTS.md",
                SUBMISSION_ROOT / "EVIDENCE_CHECKLIST.md",
            )
        )
        self.assertNotIn("未完成硬门槛", combined)
        self.assertNotIn("尚缺成功宿主截图", combined)
        self.assertNotIn("在取得成功截图前", combined)
        self.assertIn("chat_finish:success:200", combined)


if __name__ == "__main__":
    unittest.main()
