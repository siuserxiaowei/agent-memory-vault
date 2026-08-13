#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "local-memory-rag"
PACKAGE_ROOT = "local-memory-rag"
PUBLIC_FILES = (
    Path("SKILL.md"),
    Path("LICENSE"),
    Path("OPEN_SOURCE_NOTICE.md"),
    Path("info.json"),
    Path("meta.json"),
    Path("requirements.txt"),
    Path("agents/openai.yaml"),
    Path("scripts/agent_memory_env.py"),
    Path("scripts/agent_memory_index.py"),
    Path("scripts/agent_memory_search.py"),
    Path("scripts/agent_memory_zvec_index.py"),
    Path("scripts/client.py"),
    Path("scripts/protocol.py"),
    Path("scripts/configure.py"),
    Path("scripts/download_model.py"),
    Path("scripts/manage.py"),
    Path("scripts/run.ps1"),
    Path("scripts/run.sh"),
    Path("scripts/server.py"),
    Path("tests/test.ps1"),
    Path("tests/test_skill.py"),
    Path("references/host-integration.md"),
    Path("references/setup.md"),
)
IGNORED_SOURCE_PARTS = {"__pycache__"}
IGNORED_SOURCE_SUFFIXES = {".pyc"}
PRIVATE_PATH_PATTERN = re.compile(rb"/Users/[A-Za-z0-9._-]+/")
CREDENTIAL_PATTERNS = (
    re.compile(rb"sk-[A-Za-z0-9][A-Za-z0-9_-]{16,}"),
    re.compile(rb"ghp_[A-Za-z0-9_]{20,}"),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
FORBIDDEN_PERSON_IDENTIFIER_SHA256 = (
    "fe672956d62c2de053986d1c1021b0787dde9cd3f16dd98c65aaba6ba705631b",
    "0150fde5ce19785699480c46b7f3e470df71b27004e2569d489d3db2d97dae06",
)
FORBIDDEN_NAMES = {
    ".env",
    "model-manifest.json",
    "service.json",
    "state.sqlite",
    "token",
}
FORBIDDEN_SUFFIXES = {".db", ".key", ".pem", ".sqlite"}


def source_files() -> set[Path]:
    files: set[Path] = set()
    for path in SKILL_ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(SKILL_ROOT)
        if any(part in IGNORED_SOURCE_PARTS for part in relative.parts):
            continue
        if path.suffix in IGNORED_SOURCE_SUFFIXES:
            continue
        files.add(relative)
    return files


def validate_sources() -> None:
    expected = set(PUBLIC_FILES)
    actual = source_files()
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing:
        raise ValueError("missing public Skill files: " + ", ".join(map(str, missing)))
    if unexpected:
        raise ValueError("unexpected Skill files: " + ", ".join(map(str, unexpected)))

    for relative in PUBLIC_FILES:
        if relative.name in FORBIDDEN_NAMES or relative.suffix in FORBIDDEN_SUFFIXES:
            raise ValueError(f"forbidden public file: {relative}")
        path = SKILL_ROOT / relative
        if path.is_symlink():
            raise ValueError(f"public Skill file must not be a symlink: {relative}")
        data = path.read_bytes()
        if PRIVATE_PATH_PATTERN.search(data):
            raise ValueError(f"private absolute path found in {relative}")
        if any(pattern.search(data) for pattern in CREDENTIAL_PATTERNS):
            raise ValueError(f"credential-like value found in {relative}")
        lowered = data.lower()
        for forbidden_digest in FORBIDDEN_PERSON_IDENTIFIER_SHA256:
            for token in re.findall(rb"[a-z][a-z0-9_-]{3,}", lowered):
                if hashlib.sha256(token).hexdigest() == forbidden_digest:
                    raise ValueError(f"forbidden person identifier found in {relative}")


def build_archive(output: Path) -> dict[str, object]:
    validate_sources()
    destination = output.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in PUBLIC_FILES:
            source = SKILL_ROOT / relative
            info = zipfile.ZipInfo(f"{PACKAGE_ROOT}/{relative.as_posix()}")
            info.date_time = (2026, 8, 11, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if relative.parts[0] == "scripts" else 0o644
            info.external_attr = (mode & 0xFFFF) << 16
            archive.writestr(info, source.read_bytes())
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    return {
        "ok": True,
        "archive": str(destination),
        "sha256": digest,
        "file_count": len(PUBLIC_FILES),
        "package_root": PACKAGE_ROOT,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a deterministic, privacy-checked Local Memory RAG Skill archive."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "dist" / "local-memory-rag.zip",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        payload = build_archive(args.output)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for key, value in payload.items():
            print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
