#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict


DEFAULT_BASE_URL = "http://127.0.0.1:8765"
DEFAULT_TOKEN_FILE = Path("~/.config/local-memory-rag/token").expanduser()
LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def private_file_is_exposed(path: Path, *, platform: str = os.name) -> bool:
    """POSIX mode bits are meaningful on POSIX; Windows ACLs are host-managed."""
    return platform != "nt" and bool(path.stat().st_mode & 0o077)


def validate_base_url(base_url: str) -> str:
    parsed = urllib.parse.urlsplit(base_url.strip())
    if parsed.scheme != "http" or not parsed.hostname:
        raise ValueError("base URL must use HTTP on a loopback address")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("base URL must not contain credentials, query, or fragment")
    if parsed.path not in ("", "/"):
        raise ValueError("base URL must not contain a path")
    if parsed.hostname != "localhost":
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError as exc:
            raise ValueError("base URL must use a loopback address") from exc
        if not address.is_loopback:
            raise ValueError("base URL must use a loopback address")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("base URL contains an invalid port") from exc
    return base_url.strip().rstrip("/")


def load_token(explicit: str, token_file: Path) -> str:
    if explicit:
        return explicit.strip()
    path = token_file.expanduser().resolve()
    if not path.is_file():
        return ""
    if private_file_is_exposed(path):
        raise ValueError(f"token file permissions must be 0600: {path}")
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError(f"token file is empty: {path}")
    return token


def request_json(base_url: str, path: str, token: str, payload=None):
    if not token:
        raise ValueError("token is required; set LOCAL_MEMORY_RAG_TOKEN or pass --token")
    base_url = validate_base_url(base_url)
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        base_url + path,
        data=body,
        headers=headers,
    )
    try:
        with LOCAL_OPENER.open(request, timeout=70) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("detail")
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            detail = None
        raise RuntimeError(detail or f"service returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("cannot reach the local memory service") from exc


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--base-url",
        default=os.environ.get("LOCAL_MEMORY_RAG_URL", DEFAULT_BASE_URL),
    )
    parser.add_argument("--token", default=os.environ.get("LOCAL_MEMORY_RAG_TOKEN", ""))
    parser.add_argument(
        "--token-file",
        type=Path,
        default=Path(os.environ.get("LOCAL_MEMORY_RAG_TOKEN_FILE", str(DEFAULT_TOKEN_FILE))),
    )
    parser.add_argument("--json", action="store_true")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Client for the Local Memory RAG service.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    health = subparsers.add_parser("health", help="Check local service readiness.")
    add_common_arguments(health)

    search = subparsers.add_parser("search", help="Search the private local vault.")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=5)
    for name in (
        "track",
        "memory-type",
        "project-id",
        "user-id",
        "agent-id",
        "agent-scope",
        "app-id",
        "session-id",
        "status",
    ):
        search.add_argument("--" + name, default="")
    search.add_argument("--has-open-loop", action="store_true")
    search.add_argument("--include-inactive", action="store_true")
    search.add_argument("--include-supporting", action="store_true")
    add_common_arguments(search)

    brief = subparsers.add_parser("brief", help="Build an evidence-first Agent work brief.")
    brief.add_argument("query")
    brief.add_argument("--limit", type=int, default=5)
    brief.add_argument("--as-of", default="")
    brief.add_argument("--max-age-days", type=int, default=180)
    for name in ("track", "memory-type", "project-id", "user-id", "agent-id", "agent-scope", "app-id", "session-id", "status"):
        brief.add_argument("--" + name, default="")
    brief.add_argument("--has-open-loop", action="store_true")
    brief.add_argument("--include-inactive", action="store_true")
    brief.add_argument("--include-supporting", action="store_true")
    add_common_arguments(brief)
    return parser.parse_args()


def print_human(payload) -> None:
    if payload.get("service") == "local-memory-rag":
        print(
            f"status={payload.get('status')} runtime={payload.get('runtime_ready')} "
            f"index={payload.get('index_ready')} semantic={payload.get('semantic_ready')}"
        )
        return
    print(f"query={payload.get('query', '')}")
    if "confidence" in payload:
        print(f"confidence={payload.get('confidence')} summary={payload.get('summary', '')}")
        print(f"evidence={len(payload.get('evidence', []))} conflicts={len(payload.get('conflicts', []))} open_loops={len(payload.get('open_loops', []))}")
        for item in payload.get("next_steps", []):
            print(f"next: {item}")
        return
    print(f"mode={payload.get('mode', '')} results={len(payload.get('results', []))}")
    for index, row in enumerate(payload.get("results", []), 1):
        print(f"{index}. [{row.get('citation', '')}] {row.get('title', '')}")
        print(f"   {row.get('snippet', '')}")
        print(f"   sources={','.join(row.get('sources', []))} score={row.get('score', 0)}")
    for warning in payload.get("warnings", []):
        print(f"warning: {warning}")


def main() -> int:
    args = parse_args()
    try:
        token = load_token(args.token, args.token_file)
        if args.command == "health":
            payload = request_json(args.base_url, "/health", token)
        else:
            filters: Dict[str, object] = {}
            for name in (
                "track",
                "memory_type",
                "project_id",
                "user_id",
                "agent_id",
                "agent_scope",
                "app_id",
                "session_id",
                "status",
            ):
                value = getattr(args, name)
                if value:
                    filters[name] = value
            for name in ("has_open_loop", "include_inactive", "include_supporting"):
                if getattr(args, name):
                    filters[name] = True
            endpoint = "/v1/brief" if args.command == "brief" else "/v1/search"
            request_payload = {"query": args.query, "limit": args.limit, "filters": filters}
            if args.command == "brief":
                request_payload.update({"as_of": args.as_of, "max_age_days": args.max_age_days})
            payload = request_json(
                args.base_url,
                endpoint,
                token,
                request_payload,
            )
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_human(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
