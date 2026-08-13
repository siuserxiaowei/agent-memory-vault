#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hmac
import ipaddress
import json
import os
import secrets
import subprocess
import sys
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

try:
    from protocol import build_answer_packet
except ImportError:  # pragma: no cover - direct spec loading
    import importlib.util
    _protocol_path = Path(__file__).with_name("protocol.py")
    _protocol_spec = importlib.util.spec_from_file_location("local_memory_rag_protocol", _protocol_path)
    if _protocol_spec is None or _protocol_spec.loader is None:
        raise
    _protocol_module = importlib.util.module_from_spec(_protocol_spec)
    _protocol_spec.loader.exec_module(_protocol_module)
    build_answer_packet = _protocol_module.build_answer_packet


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_LIMIT = 5
MAX_LIMIT = 20
MAX_BODY_BYTES = 32 * 1024
DEFAULT_TIMEOUT = 60
DEFAULT_TOKEN_FILE = Path("~/.config/local-memory-rag/token").expanduser()
DEFAULT_CONFIG_FILE = Path("~/.config/local-memory-rag/service.json").expanduser()

ALLOWED_FILTERS = {
    "track",
    "memory_type",
    "project_id",
    "user_id",
    "agent_id",
    "agent_scope",
    "app_id",
    "session_id",
    "status",
    "has_open_loop",
    "include_inactive",
    "include_supporting",
}
BOOLEAN_FILTERS = {"has_open_loop", "include_inactive", "include_supporting"}


def private_file_is_exposed(path: Path, *, platform: str = os.name) -> bool:
    """POSIX mode bits are meaningful on POSIX; Windows ACLs are host-managed."""
    return platform != "nt" and bool(path.stat().st_mode & 0o077)


class BackendError(RuntimeError):
    pass


@dataclass(frozen=True)
class SearchRequest:
    query: str
    limit: int = DEFAULT_LIMIT
    filters: Mapping[str, object] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.filters is None:
            object.__setattr__(self, "filters", {})


@dataclass(frozen=True)
class BriefRequest:
    query: str
    limit: int = DEFAULT_LIMIT
    filters: Mapping[str, object] = None  # type: ignore[assignment]
    as_of: str = ""
    max_age_days: int = 180

    def __post_init__(self) -> None:
        if self.filters is None:
            object.__setattr__(self, "filters", {})


def validate_loopback_host(host: str) -> str:
    candidate = host.strip()
    if candidate == "localhost":
        return candidate
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError as exc:
        raise ValueError("host must be a loopback address") from exc
    if not address.is_loopback:
        raise ValueError("host must be a loopback address")
    return candidate


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


def _private_json(path: Path) -> Dict[str, object]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        return {}
    if private_file_is_exposed(resolved):
        raise ValueError(f"config file permissions must be 0600: {resolved}")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid service config: {resolved}") from exc
    if not isinstance(payload, dict):
        raise ValueError("service config must be a JSON object")
    return payload


def _config_path(payload: Mapping[str, object], key: str, *, required: bool = False) -> str:
    value = payload.get(key, "")
    if value in (None, "") and not required:
        return ""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"service config field {key} must be a path string")
    path = Path(os.path.expandvars(value)).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return str(path.absolute())


def load_service_config(path: Path) -> Path:
    payload = _private_json(path)
    if not payload:
        return default_runtime_root()
    allowed = {
        "runtime_root",
        "vault_root",
        "state_db",
        "vector_dir",
        "semantic_python",
        "embedding_model",
        "require_local_model",
        "model_manifest",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError("unknown service config fields: " + ", ".join(sorted(unknown)))
    runtime = Path(_config_path(payload, "runtime_root", required=True))
    environment_paths = {
        "vault_root": "AGENT_MEMORY_ROOT",
        "state_db": "AGENT_MEMORY_STATE_DB",
        "vector_dir": "AGENT_MEMORY_VECTOR_DIR",
        "semantic_python": "AGENT_MEMORY_ZVEC_PYTHON",
        "model_manifest": "AGENT_MEMORY_MODEL_MANIFEST",
    }
    for field, environment_name in environment_paths.items():
        value = _config_path(payload, field)
        if value:
            os.environ[environment_name] = value
    model = payload.get("embedding_model")
    if model not in (None, ""):
        if not isinstance(model, str):
            raise ValueError("embedding_model must be a string")
        os.environ["AGENT_MEMORY_EMBEDDING_MODEL"] = model
    require_local = payload.get("require_local_model")
    if require_local is not None:
        if not isinstance(require_local, bool):
            raise ValueError("require_local_model must be a boolean")
        os.environ["AGENT_MEMORY_REQUIRE_LOCAL_MODEL"] = "true" if require_local else "false"
    return runtime


def validate_search_request(payload: object) -> SearchRequest:
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    unknown = set(payload) - {"query", "limit", "filters"}
    if unknown:
        raise ValueError("unknown request fields: " + ", ".join(sorted(unknown)))

    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    query = query.strip()
    if len(query) > 2000:
        raise ValueError("query is too long")

    limit = payload.get("limit", DEFAULT_LIMIT)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")
    limit = min(limit, MAX_LIMIT)

    raw_filters = payload.get("filters", {})
    if not isinstance(raw_filters, dict):
        raise ValueError("filters must be a JSON object")
    unknown_filters = set(raw_filters) - ALLOWED_FILTERS
    if unknown_filters:
        raise ValueError("unknown filters: " + ", ".join(sorted(unknown_filters)))
    filters: Dict[str, object] = {}
    for key, value in raw_filters.items():
        if key in BOOLEAN_FILTERS:
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be a boolean")
            if value:
                filters[key] = True
            continue
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be a non-empty string")
        filters[key] = value.strip()
    if "agent_scope" in filters and filters["agent_scope"] not in {
        "codex",
        "claude",
        "shared",
    }:
        raise ValueError("agent_scope must be codex, claude, or shared")
    return SearchRequest(query=query, limit=limit, filters=filters)


def validate_brief_request(payload: object) -> BriefRequest:
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    unknown = set(payload) - {"query", "limit", "filters", "as_of", "max_age_days"}
    if unknown:
        raise ValueError("unknown request fields: " + ", ".join(sorted(unknown)))
    search = validate_search_request({key: payload[key] for key in ("query", "limit", "filters") if key in payload})
    as_of = payload.get("as_of", "")
    if not isinstance(as_of, str):
        raise ValueError("as_of must be an ISO date string")
    as_of = as_of.strip()
    if as_of:
        try:
            import datetime as dt
            dt.date.fromisoformat(as_of)
        except ValueError as exc:
            raise ValueError("as_of must be an ISO date string") from exc
    max_age_days = payload.get("max_age_days", 180)
    if isinstance(max_age_days, bool) or not isinstance(max_age_days, int) or not 0 <= max_age_days <= 3650:
        raise ValueError("max_age_days must be an integer between 0 and 3650")
    return BriefRequest(search.query, search.limit, search.filters, as_of, max_age_days)


def default_runtime_root() -> Path:
    configured = os.environ.get("AGENT_MEMORY_RUNTIME_ROOT", "").strip()
    if configured:
        return Path(os.path.expandvars(configured)).expanduser().resolve()
    skill_root = Path(__file__).resolve().parents[1]
    if (skill_root / "scripts" / "agent_memory_search.py").is_file():
        return skill_root
    return Path(__file__).resolve().parents[3]


def offline_environment() -> Dict[str, str]:
    environment = os.environ.copy()
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        environment.pop(key, None)
    environment["HF_HUB_OFFLINE"] = "1"
    environment["TRANSFORMERS_OFFLINE"] = "1"
    return environment


def _safe_warning(value: object, runtime_root: Path) -> str:
    warning = str(value)
    for private_path, replacement in (
        (str(runtime_root), "$AGENT_MEMORY_RUNTIME_ROOT"),
        (str(Path.home()), "$HOME"),
    ):
        if private_path:
            warning = warning.replace(private_path, replacement)
    return warning[:500]


def _public_result(row: object) -> Optional[Dict[str, object]]:
    if not isinstance(row, dict):
        return None
    citation = str(row.get("rel_path") or "").strip()
    if not citation or citation.startswith("/") or ".." in Path(citation).parts:
        return None
    sources = row.get("sources", [])
    if not isinstance(sources, list):
        sources = []
    try:
        score = round(float(row.get("score", 0.0)), 4)
    except (TypeError, ValueError):
        score = 0.0
    snippet = str(row.get("summary") or row.get("hit") or "").strip()
    result: Dict[str, object] = {
        "citation": citation,
        "title": str(row.get("title") or "").strip(),
        "snippet": snippet[:800],
        "sources": sorted({str(source) for source in sources if source}),
        "score": score,
    }
    for key in ("memory_type", "track", "project_id", "status", "verified_at"):
        value = str(row.get(key) or "").strip()
        if value:
            result[key] = value
    if row.get("has_open_loop"):
        result["has_open_loop"] = True
    return result


class SearchBackend:
    def __init__(self, runtime_root: Path, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.runtime_root = runtime_root.expanduser().resolve()
        self.timeout = max(int(timeout), 1)
        self.search_script = self.runtime_root / "scripts" / "agent_memory_search.py"

    def health(self) -> Dict[str, object]:
        state_db = os.environ.get("AGENT_MEMORY_STATE_DB", "").strip()
        state_path = (
            Path(os.path.expandvars(state_db)).expanduser()
            if state_db
            else self.runtime_root / ".agent-memory" / "state.sqlite"
        )
        vector_dir = os.environ.get("AGENT_MEMORY_VECTOR_DIR", "").strip()
        vector_path = (
            Path(os.path.expandvars(vector_dir)).expanduser()
            if vector_dir
            else self.runtime_root / ".agent-memory" / "zvec" / "memory_chunks_embeddinggemma_768"
        )
        runtime_ready = self.search_script.is_file()
        index_ready = state_path.is_file()
        semantic_ready = vector_path.exists()
        return {
            "status": "ok" if runtime_ready and index_ready else "degraded",
            "service": "local-memory-rag",
            "runtime_ready": runtime_ready,
            "index_ready": index_ready,
            "semantic_ready": semantic_ready,
            "network_scope": "loopback-only",
            "model_network": "offline-only",
        }

    def _command(self, request: SearchRequest) -> list[str]:
        python = os.environ.get("AGENT_MEMORY_PYTHON", "").strip() or sys.executable
        command = [
            python,
            str(self.search_script),
            "--query-stdin",
            "--limit",
            str(request.limit),
            "--json",
        ]
        for key, value in request.filters.items():
            option = "--" + key.replace("_", "-")
            if key in BOOLEAN_FILTERS:
                if value:
                    command.append(option)
            else:
                command.extend([option, str(value)])
        return command

    def search(self, request: SearchRequest) -> Dict[str, object]:
        if not self.search_script.is_file():
            raise BackendError("Agent Memory search runtime is not installed")
        try:
            completed = subprocess.run(
                self._command(request),
                cwd=self.runtime_root,
                env=offline_environment(),
                input=request.query,
                text=True,
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise BackendError("local search timed out") from exc
        except OSError as exc:
            raise BackendError("local search could not start") from exc
        if completed.returncode != 0:
            raise BackendError("local search failed")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise BackendError("local search returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise BackendError("local search returned an invalid response")

        results = []
        for row in payload.get("results", []):
            public = _public_result(row)
            if public is not None:
                results.append(public)
        warnings = [
            _safe_warning(value, self.runtime_root)
            for value in payload.get("warnings", [])
        ] if isinstance(payload.get("warnings", []), list) else []
        semantic_used = any("zvec" in result.get("sources", []) for result in results)
        mode = "hybrid" if semantic_used else "keyword_fallback"
        return {
            "query": request.query,
            "mode": mode,
            "degraded": not semantic_used,
            "results": results,
            "warnings": warnings,
            "privacy": {
                "network_scope": "loopback-only",
                "model_network": "offline-only",
                "absolute_paths_returned": False,
            },
        }

    def brief(self, request: BriefRequest) -> Dict[str, object]:
        search = self.search(SearchRequest(request.query, request.limit, request.filters))
        packet = build_answer_packet(
            request.query,
            search,
            as_of=request.as_of,
            max_age_days=request.max_age_days,
        )
        packet["privacy"] = search["privacy"]
        return packet


def _handler_factory(backend: SearchBackend, token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "LocalMemoryRAG/1.0"

        def log_message(self, format: str, *args: object) -> None:
            return

        def _authorized(self) -> bool:
            header = self.headers.get("Authorization", "")
            prefix = "Bearer "
            candidate = header[len(prefix):] if header.startswith(prefix) else ""
            return bool(candidate) and hmac.compare_digest(candidate, token)

        def _send(self, status: int, payload: Mapping[str, object]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _require_auth(self) -> bool:
            if self._authorized():
                return True
            self._send(401, {"error": "unauthorized"})
            return False

        def do_GET(self) -> None:
            if self.path != "/health":
                self._send(404, {"error": "not_found"})
                return
            if not self._require_auth():
                return
            self._send(200, backend.health())

        def do_POST(self) -> None:
            if self.path not in {"/v1/search", "/v1/brief"}:
                self._send(404, {"error": "not_found"})
                return
            if not self._require_auth():
                return
            content_type = self.headers.get_content_type()
            if content_type != "application/json":
                self._send(415, {"error": "content_type_must_be_application_json"})
                return
            raw_length = self.headers.get("Content-Length", "")
            try:
                length = int(raw_length)
            except ValueError:
                self._send(400, {"error": "invalid_content_length"})
                return
            if length < 1 or length > MAX_BODY_BYTES:
                self._send(413, {"error": "request_body_too_large_or_empty"})
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                request = (
                    validate_brief_request(payload)
                    if self.path == "/v1/brief"
                    else validate_search_request(payload)
                )
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                self._send(400, {"error": "invalid_request", "detail": str(exc)[:300]})
                return
            try:
                result = backend.brief(request) if self.path == "/v1/brief" else backend.search(request)
            except BackendError as exc:
                self._send(503, {"error": "search_unavailable", "detail": str(exc)})
                return
            self._send(200, result)

    return Handler


def create_server(
    host: str,
    port: int,
    backend: SearchBackend,
    token: str,
) -> ThreadingHTTPServer:
    validate_loopback_host(host)
    if not token:
        raise ValueError("token is required")
    if port < 0 or port > 65535:
        raise ValueError("port must be between 0 and 65535")
    return ThreadingHTTPServer((host, port), _handler_factory(backend, token))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Loopback-only HTTP service for Agent Memory hybrid retrieval."
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--runtime-root", type=Path, default=default_runtime_root())
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(os.environ.get("LOCAL_MEMORY_RAG_CONFIG", str(DEFAULT_CONFIG_FILE))),
        help="Private 0600 JSON service config.",
    )
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument(
        "--token",
        default=os.environ.get("LOCAL_MEMORY_RAG_TOKEN", ""),
        help="Bearer token; defaults to LOCAL_MEMORY_RAG_TOKEN.",
    )
    parser.add_argument(
        "--token-file",
        type=Path,
        default=Path(os.environ.get("LOCAL_MEMORY_RAG_TOKEN_FILE", str(DEFAULT_TOKEN_FILE))),
        help="Private 0600 token file used when --token and LOCAL_MEMORY_RAG_TOKEN are absent.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        runtime_root = args.runtime_root
        if args.config.is_file():
            runtime_root = load_service_config(args.config)
        token = load_token(args.token, args.token_file)
        if not token:
            token = secrets.token_urlsafe(32)
        server = create_server(
            args.host,
            args.port,
            SearchBackend(runtime_root, timeout=args.timeout),
            token,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Local Memory RAG listening on http://{args.host}:{server.server_port}")
    if not args.token and not args.token_file.is_file():
        print(f"LOCAL_MEMORY_RAG_TOKEN={token}")
        print("Save this token in the host environment; it is shown only at startup.")
    print("Network scope: loopback only. Model network: offline only.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
