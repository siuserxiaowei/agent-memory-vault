#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = SKILL_ROOT / "scripts"
DEFAULT_STATE_ROOT = Path("~/.config/local-memory-rag").expanduser()


def private_file_is_exposed(path: Path, *, platform: str = os.name) -> bool:
    """POSIX mode bits are meaningful on POSIX; Windows ACLs are host-managed."""
    return platform != "nt" and bool(path.stat().st_mode & 0o077)


def state_paths(state_root: Path) -> dict[str, Path]:
    root = state_root.expanduser().resolve()
    return {
        "root": root,
        "config": root / "service.json",
        "token": root / "token",
        "state_db": root / "state.sqlite",
        "vector_dir": root / "zvec" / "memory_chunks_embeddinggemma_768",
        "lock": root / "locks" / "zvec.lock",
    }


def private_environment(state_root: Path) -> dict[str, str]:
    paths = state_paths(state_root)
    environment = os.environ.copy()
    environment.update(
        {
            "LOCAL_MEMORY_RAG_CONFIG": str(paths["config"]),
            "LOCAL_MEMORY_RAG_TOKEN_FILE": str(paths["token"]),
            "AGENT_MEMORY_STATE_DB": str(paths["state_db"]),
            "AGENT_MEMORY_VECTOR_DIR": str(paths["vector_dir"]),
            "AGENT_MEMORY_ZVEC_LOCK": str(paths["lock"]),
        }
    )
    return environment


def configured_environment(state_root: Path, payload: dict[str, object]) -> dict[str, str]:
    environment = private_environment(state_root)
    mappings = {
        "vault_root": "AGENT_MEMORY_ROOT",
        "state_db": "AGENT_MEMORY_STATE_DB",
        "vector_dir": "AGENT_MEMORY_VECTOR_DIR",
        "semantic_python": "AGENT_MEMORY_ZVEC_PYTHON",
        "embedding_model": "AGENT_MEMORY_EMBEDDING_MODEL",
        "model_manifest": "AGENT_MEMORY_MODEL_MANIFEST",
    }
    for field, name in mappings.items():
        value = payload.get(field)
        if isinstance(value, str) and value:
            environment[name] = value
    require_local = payload.get("require_local_model")
    if isinstance(require_local, bool):
        environment["AGENT_MEMORY_REQUIRE_LOCAL_MODEL"] = (
            "true" if require_local else "false"
        )
    return environment


def load_config(state_root: Path) -> dict[str, object]:
    path = state_paths(state_root)["config"]
    if not path.is_file():
        raise ValueError(f"configuration is missing; run configure first: {path}")
    if private_file_is_exposed(path):
        raise ValueError(f"config file permissions must be 0600: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid configuration: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("configuration must be a JSON object")
    return payload


def run(command: list[str], *, environment: dict[str, str] | None = None) -> int:
    try:
        completed = subprocess.run(command, env=environment, check=False)
    except OSError as exc:
        print(f"error: could not start local command: {exc}", file=sys.stderr)
        return 2
    return completed.returncode


def configure(args: argparse.Namespace) -> int:
    command = [
        sys.executable,
        str(SCRIPT_ROOT / "configure.py"),
        "--runtime-root",
        str(SKILL_ROOT),
        "--vault-root",
        str(args.vault_root),
        "--state-root",
        str(args.state_root),
    ]
    if args.semantic_python:
        command.extend(["--semantic-python", str(args.semantic_python)])
    if args.managed_model:
        command.extend(["--managed-model", str(args.managed_model)])
    if args.model_manifest:
        command.extend(["--model-manifest", str(args.model_manifest)])
    if args.embedding_model:
        command.extend(["--embedding-model", args.embedding_model])
    for host_root in args.host_skill_root:
        command.extend(["--host-skill-root", str(host_root)])
    if args.replace_config:
        command.append("--replace-config")
    if args.json:
        command.append("--json")
    return run(command)


def index(args: argparse.Namespace) -> int:
    try:
        payload = load_config(args.state_root)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    vault_root = payload.get("vault_root")
    if not isinstance(vault_root, str) or not vault_root:
        print("error: configured vault_root is missing", file=sys.stderr)
        return 2
    environment = configured_environment(args.state_root, payload)
    command = [
        sys.executable,
        str(SCRIPT_ROOT / "agent_memory_index.py"),
        "--init",
        "--scan",
        "--report",
    ]
    exit_code = run(command, environment=environment)
    if exit_code != 0 or not args.semantic:
        return exit_code
    semantic_python = str(payload.get("semantic_python") or sys.executable)
    vector_command = [
        semantic_python,
        str(SCRIPT_ROOT / "agent_memory_zvec_index.py"),
        "--init",
        "--scan",
        "--prune",
    ]
    if args.json:
        vector_command.append("--json")
    return run(vector_command, environment=environment)


def start(args: argparse.Namespace) -> int:
    command = [
        sys.executable,
        str(SCRIPT_ROOT / "server.py"),
        "--config",
        str(state_paths(args.state_root)["config"]),
        "--token-file",
        str(state_paths(args.state_root)["token"]),
        "--host",
        args.host,
        "--port",
        str(args.port),
    ]
    return run(command, environment=private_environment(args.state_root))


def client(args: argparse.Namespace) -> int:
    command = [
        sys.executable,
        str(SCRIPT_ROOT / "client.py"),
        args.command,
    ]
    if args.command == "search":
        command.extend([args.query, "--limit", str(args.limit)])
    command.extend(
        [
            "--base-url",
            args.base_url,
            "--token-file",
            str(state_paths(args.state_root)["token"]),
        ]
    )
    if args.json:
        command.append("--json")
    return run(command, environment=private_environment(args.state_root))


def add_state_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install, index, start, and query the self-contained Local Memory RAG Skill."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    configure_parser = commands.add_parser("configure", help="Create private local configuration.")
    configure_parser.add_argument("--vault-root", type=Path, required=True)
    add_state_root(configure_parser)
    configure_parser.add_argument("--semantic-python", type=Path)
    configure_parser.add_argument("--embedding-model", default="google/embeddinggemma-300m")
    configure_parser.add_argument("--managed-model", type=Path)
    configure_parser.add_argument("--model-manifest", type=Path)
    configure_parser.add_argument("--host-skill-root", type=Path, action="append", default=[])
    configure_parser.add_argument("--replace-config", action="store_true")
    configure_parser.add_argument("--json", action="store_true")

    index_parser = commands.add_parser("index", help="Build the private Markdown index.")
    add_state_root(index_parser)
    index_parser.add_argument(
        "--semantic",
        action="store_true",
        help="Also build the local EmbeddingGemma + Zvec index.",
    )
    index_parser.add_argument("--json", action="store_true")

    start_parser = commands.add_parser("start", help="Run the loopback-only service.")
    add_state_root(start_parser)
    start_parser.add_argument("--host", default="127.0.0.1")
    start_parser.add_argument("--port", type=int, default=8765)

    for name in ("health", "search"):
        client_parser = commands.add_parser(name, help=f"Run local service {name}.")
        if name == "search":
            client_parser.add_argument("query")
            client_parser.add_argument("--limit", type=int, default=5)
        add_state_root(client_parser)
        client_parser.add_argument("--base-url", default="http://127.0.0.1:8765")
        client_parser.add_argument("--json", action="store_true")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "configure":
        return configure(args)
    if args.command == "index":
        return index(args)
    if args.command == "start":
        return start(args)
    return client(args)


if __name__ == "__main__":
    raise SystemExit(main())
