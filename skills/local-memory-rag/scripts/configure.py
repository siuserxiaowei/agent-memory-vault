#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE_ROOT = Path("~/.config/local-memory-rag").expanduser()


def write_private(path: Path, text: str, *, replace: bool = False) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not replace:
        if os.name != "nt":
            path.chmod(0o600)
        return False
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
    finally:
        if os.name != "nt":
            path.chmod(0o600)
    return True


def install_host_link(host_root: Path) -> Path:
    root = host_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / "local-memory-rag"
    if target.is_symlink() and target.resolve() == SKILL_ROOT.resolve():
        return target
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"refusing to replace existing host skill: {target}")
    target.symlink_to(SKILL_ROOT.resolve(), target_is_directory=True)
    return target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Configure Local Memory RAG privately on this machine.")
    parser.add_argument("--runtime-root", type=Path, default=SKILL_ROOT)
    parser.add_argument("--vault-root", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    parser.add_argument("--semantic-python", type=Path)
    parser.add_argument("--embedding-model", default="google/embeddinggemma-300m")
    parser.add_argument("--managed-model", type=Path)
    parser.add_argument("--model-manifest", type=Path)
    parser.add_argument("--host-skill-root", type=Path, action="append", default=[])
    parser.add_argument("--replace-config", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runtime = args.runtime_root.expanduser().resolve()
    vault = args.vault_root.expanduser().resolve()
    state = args.state_root.expanduser().resolve()
    if not (runtime / "scripts" / "agent_memory_search.py").is_file():
        print("error: runtime root does not contain scripts/agent_memory_search.py", file=sys.stderr)
        return 2
    if not vault.is_dir():
        print("error: vault root is not a directory", file=sys.stderr)
        return 2

    semantic_python = (
        args.semantic_python.expanduser().absolute()
        if args.semantic_python
        else Path(sys.executable).absolute()
    )
    embedding_model = (
        str(args.managed_model.expanduser().resolve())
        if args.managed_model
        else args.embedding_model
    )
    config = {
        "runtime_root": str(runtime),
        "vault_root": str(vault),
        "state_db": str(state / "state.sqlite"),
        "vector_dir": str(state / "zvec" / "memory_chunks_embeddinggemma_768"),
        "semantic_python": str(semantic_python),
        "embedding_model": embedding_model,
        "require_local_model": bool(args.managed_model),
    }
    if args.model_manifest:
        config["model_manifest"] = str(args.model_manifest.expanduser().resolve())

    config_file = state / "service.json"
    token_file = state / "token"
    config_changed = write_private(
        config_file,
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        replace=args.replace_config,
    )
    token_changed = write_private(token_file, secrets.token_urlsafe(32) + "\n")
    installed = [str(install_host_link(root)) for root in args.host_skill_root]
    payload = {
        "ok": True,
        "config_file": str(config_file),
        "token_file": str(token_file),
        "config_changed": config_changed,
        "token_changed": token_changed,
        "host_skills": installed,
        "next": [
            "run scripts/run.ps1 index --semantic after installing requirements.txt",
            "run scripts/run.ps1 start",
            "run scripts/run.ps1 health --json in another terminal",
        ],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"config={config_file}")
        print(f"token={token_file} (secret not displayed)")
        for path in installed:
            print(f"installed={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
