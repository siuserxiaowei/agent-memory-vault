from __future__ import annotations

import hashlib
import http.server
import http.client
import importlib.util
import io
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from types import SimpleNamespace
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "local-memory-rag"
SERVER_PATH = SKILL_ROOT / "scripts" / "server.py"
CLIENT_PATH = SKILL_ROOT / "scripts" / "client.py"
CONFIGURE_PATH = SKILL_ROOT / "scripts" / "configure.py"
DOWNLOAD_MODEL_PATH = SKILL_ROOT / "scripts" / "download_model.py"
MANAGE_PATH = SKILL_ROOT / "scripts" / "manage.py"
SEARCH_PATH = REPO_ROOT / "scripts" / "agent_memory_search.py"
ZVEC_INDEX_PATH = REPO_ROOT / "scripts" / "agent_memory_zvec_index.py"
CHECK_PATH = REPO_ROOT / "scripts" / "agent_memory_check.py"
PACKAGE_PATH = REPO_ROOT / "scripts" / "package_contest_skill.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class LocalMemoryRagContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = load_module("local_memory_rag_server_test", SERVER_PATH)

    def test_server_rejects_non_loopback_bind_addresses(self) -> None:
        for host in ("0.0.0.0", "192.168.1.20", "example.com"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                self.server.validate_loopback_host(host)
        for host in ("127.0.0.1", "localhost", "::1"):
            with self.subTest(host=host):
                self.assertEqual(self.server.validate_loopback_host(host), host)

    def test_server_rejects_invalid_tokens_configs_and_request_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            token_file = root / "token"
            self.assertEqual(self.server.load_token("", token_file), "")
            self.assertEqual(self.server.load_token(" explicit-token ", token_file), "explicit-token")
            token_file.write_text("\n", encoding="utf-8")
            token_file.chmod(0o600)
            with self.assertRaises(ValueError):
                self.server.load_token("", token_file)

            config = root / "service.json"
            self.assertEqual(self.server._private_json(config), {})
            config.write_text("{}", encoding="utf-8")
            config.chmod(0o644)
            with self.assertRaises(ValueError):
                self.server._private_json(config)
            config.chmod(0o600)
            for invalid in ("not-json", "[]"):
                config.write_text(invalid, encoding="utf-8")
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    self.server._private_json(config)

        invalid_payloads = (
            [],
            {"query": "ok", "limit": True},
            {"query": "ok", "limit": 0},
            {"query": "ok", "filters": []},
            {"query": "ok", "filters": {"has_open_loop": "yes"}},
            {"query": "ok", "filters": {"track": ""}},
            {"query": "ok", "filters": {"agent_scope": "other"}},
            {"query": "x" * 2001},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.server.validate_search_request(payload)

    def test_brief_request_validation_adds_time_aware_protocol_fields(self) -> None:
        request = self.server.validate_brief_request(
            {"query": "发布边界", "as_of": "2026-08-13", "max_age_days": 30}
        )
        self.assertEqual(request.as_of, "2026-08-13")
        self.assertEqual(request.max_age_days, 30)
        for payload in (
            {"query": "x", "as_of": "yesterday"},
            {"query": "x", "max_age_days": -1},
            {"query": "x", "max_age_days": True},
            {"query": "x", "unknown": 1},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.server.validate_brief_request(payload)

    def test_service_config_rejects_unknown_or_mistyped_fields(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            config = Path(raw_root) / "service.json"
            cases = (
                {"runtime_root": raw_root, "unknown": True},
                {"runtime_root": 3},
                {"runtime_root": raw_root, "embedding_model": 3},
                {"runtime_root": raw_root, "require_local_model": "yes"},
            )
            for payload in cases:
                config.write_text(json.dumps(payload), encoding="utf-8")
                config.chmod(0o600)
                with self.subTest(payload=payload), self.assertRaises(ValueError):
                    self.server.load_service_config(config)

    def test_server_sanitizes_environment_warnings_and_public_results(self) -> None:
        runtime = REPO_ROOT / "private-runtime"
        with mock.patch.dict(
            os.environ,
            {"HTTP_PROXY": "proxy", "http_proxy": "proxy", "KEEP_ME": "yes"},
            clear=True,
        ):
            environment = self.server.offline_environment()
        self.assertNotIn("HTTP_PROXY", environment)
        self.assertNotIn("http_proxy", environment)
        self.assertEqual(environment["KEEP_ME"], "yes")
        self.assertEqual(environment["HF_HUB_OFFLINE"], "1")

        warning = self.server._safe_warning(
            f"failed under {runtime} and {Path.home()}" + "x" * 600,
            runtime,
        )
        self.assertIn("$AGENT_MEMORY_RUNTIME_ROOT", warning)
        self.assertIn("$HOME", warning)
        self.assertLessEqual(len(warning), 500)

        invalid_rows = (
            None,
            {},
            {"rel_path": "/private.md"},
            {"rel_path": "../private.md"},
        )
        for row in invalid_rows:
            with self.subTest(row=row):
                self.assertIsNone(self.server._public_result(row))
        public = self.server._public_result(
            {
                "rel_path": "项目/公开.md",
                "hit": "命中",
                "sources": "invalid",
                "score": "invalid",
                "memory_type": "decision",
            }
        )
        self.assertEqual(public["sources"], [])
        self.assertEqual(public["score"], 0.0)
        self.assertEqual(public["memory_type"], "decision")

    def test_backend_health_command_and_failure_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            backend = self.server.SearchBackend(root, timeout=0)
            self.assertEqual(backend.timeout, 1)
            self.assertEqual(backend.health()["status"], "degraded")
            request = self.server.SearchRequest(
                query="test",
                limit=2,
                filters={"has_open_loop": True, "track": "project"},
            )
            command = backend._command(request)
            self.assertIn("--has-open-loop", command)
            self.assertIn("--track", command)
            with self.assertRaises(self.server.BackendError):
                backend.search(request)

            (root / "scripts").mkdir()
            (root / "scripts" / "agent_memory_search.py").touch()
            state = root / "state.sqlite"
            state.touch()
            vector = root / "vectors"
            vector.mkdir()
            with mock.patch.dict(
                os.environ,
                {
                    "AGENT_MEMORY_STATE_DB": str(state),
                    "AGENT_MEMORY_VECTOR_DIR": str(vector),
                    "AGENT_MEMORY_PYTHON": "custom-python",
                },
                clear=True,
            ):
                self.assertEqual(backend.health()["status"], "ok")
                self.assertEqual(backend._command(request)[0], "custom-python")

            failures = (
                subprocess.TimeoutExpired(cmd="search", timeout=1),
                OSError("cannot start"),
                subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout="not-json", stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout="[]", stderr=""),
            )
            for failure in failures:
                if isinstance(failure, BaseException):
                    patcher = mock.patch.object(self.server.subprocess, "run", side_effect=failure)
                else:
                    patcher = mock.patch.object(self.server.subprocess, "run", return_value=failure)
                with self.subTest(failure=type(failure).__name__), patcher, self.assertRaises(
                    self.server.BackendError
                ):
                    backend.search(request)

    def test_server_creation_and_main_error_paths(self) -> None:
        backend = self.server.SearchBackend(REPO_ROOT)
        with self.assertRaises(ValueError):
            self.server.create_server("127.0.0.1", 1, backend, "")
        for port in (-1, 65536):
            with self.subTest(port=port), self.assertRaises(ValueError):
                self.server.create_server("127.0.0.1", port, backend, "token")

        args = SimpleNamespace(
            runtime_root=REPO_ROOT,
            config=Path("/does/not/exist"),
            token="token",
            token_file=Path("/does/not/exist"),
            host="0.0.0.0",
            port=8765,
            timeout=1,
        )
        with mock.patch.object(self.server, "parse_args", return_value=args), mock.patch(
            "sys.stderr", new_callable=io.StringIO
        ) as stderr:
            self.assertEqual(self.server.main(), 2)
        self.assertIn("loopback", stderr.getvalue())

    def test_request_validation_limits_scope_and_rejects_unknown_fields(self) -> None:
        request = self.server.validate_search_request(
            {
                "query": "项目现在的发布边界是什么？",
                "limit": 50,
                "filters": {"track": "project", "status": "active"},
            }
        )
        self.assertEqual(request.query, "项目现在的发布边界是什么？")
        self.assertEqual(request.limit, 20)
        self.assertEqual(request.filters, {"track": "project", "status": "active"})

        invalid_payloads = (
            {},
            {"query": "   "},
            {"query": "ok", "filters": {"private_path": "/tmp"}},
            {"query": "ok", "unexpected": True},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.server.validate_search_request(payload)

    def test_backend_enforces_offline_execution_and_redacts_absolute_paths(self) -> None:
        fake_payload = {
            "query": "隐私边界",
            "results": [
                {
                    "rel_path": "用户记忆/偏好与边界.md",
                    "title": "偏好与边界",
                    "summary": "私人资料必须留在本地。",
                    "hit": "隐私边界：资料不上传云端。",
                    "sources": ["sqlite", "zvec"],
                    "score": 4.2,
                    "path": "/" + "Users/private/Agent记忆/用户记忆/偏好与边界.md",
                    "source_details": {"sqlite_rank": 1},
                }
            ],
            "warnings": [],
        }
        completed = subprocess.CompletedProcess(
            args=["python"], returncode=0, stdout=json.dumps(fake_payload), stderr=""
        )
        with tempfile.TemporaryDirectory() as raw_runtime:
            runtime = Path(raw_runtime)
            (runtime / "scripts").mkdir()
            (runtime / "scripts" / "agent_memory_search.py").touch()
            with mock.patch.object(self.server.subprocess, "run", return_value=completed) as run_mock:
                result = self.server.SearchBackend(runtime_root=runtime).search(
                    self.server.validate_search_request({"query": "隐私边界", "limit": 5})
                )

        command = run_mock.call_args.args[0]
        environment = run_mock.call_args.kwargs["env"]
        self.assertIn(str((runtime / "scripts" / "agent_memory_search.py").resolve()), command)
        self.assertNotIn("隐私边界", command)
        self.assertIn("--query-stdin", command)
        self.assertEqual(run_mock.call_args.kwargs["input"], "隐私边界")
        self.assertEqual(environment["HF_HUB_OFFLINE"], "1")
        self.assertEqual(environment["TRANSFORMERS_OFFLINE"], "1")
        self.assertEqual(result["mode"], "hybrid")
        self.assertNotIn("path", result["results"][0])
        self.assertNotIn("source_details", result["results"][0])
        self.assertEqual(result["results"][0]["citation"], "用户记忆/偏好与边界.md")

    def test_backend_reports_degraded_keyword_mode_without_claiming_hybrid(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["python"],
            returncode=0,
            stdout=json.dumps(
                {
                    "query": "发布",
                    "results": [
                        {
                            "rel_path": "项目/发布.md",
                            "title": "发布",
                            "summary": "",
                            "hit": "先检查再发布",
                            "sources": ["sqlite"],
                            "score": 1.0,
                            "path": "/private/project.md",
                        }
                    ],
                    "warnings": ["zvec search failed: model unavailable"],
                }
            ),
            stderr="",
        )
        with tempfile.TemporaryDirectory() as raw_runtime:
            runtime = Path(raw_runtime)
            (runtime / "scripts").mkdir()
            (runtime / "scripts" / "agent_memory_search.py").touch()
            with mock.patch.object(self.server.subprocess, "run", return_value=completed):
                result = self.server.SearchBackend(runtime_root=runtime).search(
                    self.server.validate_search_request({"query": "发布"})
                )
        self.assertEqual(result["mode"], "keyword_fallback")
        self.assertTrue(result["degraded"])

    def test_nested_zvec_search_keeps_private_query_out_of_process_arguments(self) -> None:
        with mock.patch.object(sys, "path", [str(REPO_ROOT / "scripts"), *sys.path]):
            search = load_module("agent_memory_search_private_query_test", SEARCH_PATH)
        args = SimpleNamespace(
            no_zvec=False,
            query="PRIVATE_QUERY_SHOULD_USE_STDIN",
            limit=3,
            zvec_timeout=45,
            zvec_max_distance=0.72,
        )
        completed = subprocess.CompletedProcess(
            args=["python"],
            returncode=0,
            stdout=json.dumps({"query": "PRIVATE_QUERY_SHOULD_USE_STDIN", "results": []}),
            stderr="",
        )
        with mock.patch.object(search.subprocess, "run", return_value=completed) as run_mock:
            rows, warnings = search.zvec_search(args)
        command = run_mock.call_args.args[0]
        self.assertNotIn(args.query, command)
        self.assertIn("--query-stdin", command)
        self.assertEqual(run_mock.call_args.kwargs["input"], args.query)
        self.assertEqual(rows, [])
        self.assertEqual(warnings, [])

    def test_zvec_search_uses_an_exclusive_process_lock(self) -> None:
        with mock.patch.object(sys, "path", [str(REPO_ROOT / "scripts"), *sys.path]):
            zvec_index = load_module("agent_memory_zvec_exclusive_search_test", ZVEC_INDEX_PATH)
        args = SimpleNamespace(
            init=False,
            scan=False,
            prune=False,
            changed_file=[],
            search="PRIVATE_QUERY",
        )
        self.assertTrue(zvec_index.requires_exclusive_lock(args))

    def test_zvec_lock_has_a_windows_compatible_backend(self) -> None:
        with mock.patch.object(sys, "path", [str(REPO_ROOT / "scripts"), *sys.path]):
            zvec_index = load_module("agent_memory_zvec_windows_lock_test", ZVEC_INDEX_PATH)

        class FakeMsvcrt:
            LK_NBLCK = 1
            LK_UNLCK = 2

            def __init__(self) -> None:
                self.operations = []

            def locking(self, descriptor, operation, size) -> None:
                self.operations.append((descriptor, operation, size))

        fake = FakeMsvcrt()
        with tempfile.TemporaryDirectory() as raw_root, mock.patch.object(
            zvec_index, "DEFAULT_LOCK_PATH", Path(raw_root) / "zvec.lock"
        ), mock.patch.object(zvec_index, "_FCNTL", None), mock.patch.object(
            zvec_index, "_MSVCRT", fake
        ):
            with zvec_index.zvec_lock(exclusive=True, timeout=0.1):
                pass
        self.assertEqual([operation for _, operation, _ in fake.operations], [1, 2])

    def test_service_private_file_contract_is_portable_to_windows(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            public_on_posix = Path(raw_root) / "service.json"
            public_on_posix.write_text("{}", encoding="utf-8")
            public_on_posix.chmod(0o644)
            self.assertTrue(
                self.server.private_file_is_exposed(public_on_posix, platform="posix")
            )
            self.assertFalse(
                self.server.private_file_is_exposed(public_on_posix, platform="nt")
            )

    def test_public_repo_check_ignores_local_runtime_artifacts(self) -> None:
        with mock.patch.object(sys, "path", [str(REPO_ROOT / "scripts"), *sys.path]):
            checker = load_module("agent_memory_public_artifact_test", CHECK_PATH)
        with tempfile.TemporaryDirectory(dir=REPO_ROOT, prefix=".contest-venv-test-") as raw_root:
            local_root = Path(raw_root)
            (local_root / "state.sqlite").write_bytes(b"private derived fixture")
            (local_root / "launcher").write_text(
                f"#!{REPO_ROOT}/.contest-venv/bin/python\n", encoding="utf-8"
            )
            self.assertTrue(checker.is_ignored_repo_path(local_root / "state.sqlite"))
            self.assertTrue(checker.is_ignored_repo_path(REPO_ROOT / ".coverage"))
            self.assertEqual(
                checker.scan_for_secrets([REPO_ROOT], include_private_paths=True), []
            )
            self.assertNotIn(
                str(local_root / "state.sqlite"), "\n".join(checker.check_public_repo_files())
            )

    def test_token_file_must_be_private_and_is_used_without_cli_secret(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            token_file = Path(raw_root) / "token"
            token_file.write_text("file-token\n", encoding="utf-8")
            token_file.chmod(0o600)
            self.assertEqual(self.server.load_token("", token_file), "file-token")
            token_file.chmod(0o644)
            with self.assertRaises(ValueError):
                self.server.load_token("", token_file)

    def test_client_token_loader_matches_server_private_file_contract(self) -> None:
        client = load_module("local_memory_rag_client_contract_test", CLIENT_PATH)
        with tempfile.TemporaryDirectory() as raw_root:
            token_file = Path(raw_root) / "token"
            token_file.write_text("client-token\n", encoding="utf-8")
            token_file.chmod(0o600)
            self.assertEqual(client.load_token("", token_file), "client-token")
        with tempfile.TemporaryDirectory() as raw_root:
            public_on_posix = Path(raw_root) / "token"
            public_on_posix.write_text("token", encoding="utf-8")
            public_on_posix.chmod(0o644)
            self.assertTrue(client.private_file_is_exposed(public_on_posix, platform="posix"))
            self.assertFalse(client.private_file_is_exposed(public_on_posix, platform="nt"))

    def test_client_rejects_non_loopback_or_ambiguous_service_urls(self) -> None:
        client = load_module("local_memory_rag_client_url_test", CLIENT_PATH)
        for url in (
            "https://127.0.0.1:8765",
            "http://192.168.1.10:8765",
            "http://example.com:8765",
            "http://user:password@127.0.0.1:8765",
            "http://127.0.0.1:8765/path",
            "http://127.0.0.1:99999",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                client.validate_base_url(url)
        for url in (
            "http://127.0.0.1:8765",
            "http://localhost:8765/",
            "http://[::1]:8765",
        ):
            with self.subTest(url=url):
                self.assertTrue(client.validate_base_url(url).startswith("http://"))

    def test_service_config_sets_private_runtime_environment(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            runtime = root / "runtime"
            vault = root / "vault"
            state = root / "state"
            semantic_python = root / "semantic" / "python"
            for path in (runtime, vault, state, semantic_python.parent):
                path.mkdir(parents=True, exist_ok=True)
            semantic_python.touch()
            config = root / "service.json"
            config.write_text(
                json.dumps(
                    {
                        "runtime_root": str(runtime),
                        "vault_root": str(vault),
                        "state_db": str(state / "state.sqlite"),
                        "vector_dir": str(state / "zvec"),
                        "semantic_python": str(semantic_python),
                    }
                ),
                encoding="utf-8",
            )
            config.chmod(0o600)
            with mock.patch.dict(os.environ, {}, clear=True):
                loaded = self.server.load_service_config(config)
                self.assertEqual(loaded, runtime.absolute())
                self.assertEqual(os.environ["AGENT_MEMORY_ROOT"], str(vault.absolute()))
                self.assertEqual(
                    os.environ["AGENT_MEMORY_STATE_DB"], str((state / "state.sqlite").absolute())
                )
                self.assertEqual(
                    os.environ["AGENT_MEMORY_ZVEC_PYTHON"], str(semantic_python.absolute())
                )


class LocalMemoryRagHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server_module = load_module("local_memory_rag_server_http_test", SERVER_PATH)

    def setUp(self) -> None:
        class FakeBackend:
            def health(self):
                return {"status": "ok", "runtime_ready": True, "semantic_ready": True}

            def search(self, request):
                return {
                    "query": request.query,
                    "mode": "hybrid",
                    "degraded": False,
                    "results": [
                        {
                            "citation": "项目/测试.md",
                            "title": "测试",
                            "snippet": "本地检索成功",
                            "sources": ["sqlite", "zvec"],
                            "score": 2.5,
                        }
                    ],
                    "warnings": [],
                }

            def brief(self, request):
                return {
                    "query": request.query,
                    "summary": "找到本地证据",
                    "confidence": "high",
                    "evidence": [{"citation": "项目/测试.md"}],
                    "uncertainties": [], "conflicts": [], "open_loops": [], "next_steps": [],
                }

        self.httpd = self.server_module.create_server(
            "127.0.0.1", 0, FakeBackend(), token="test-token"
        )
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.httpd.server_port}"

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    def request(self, path: str, *, data=None, token="test-token"):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body = None if data is None else json.dumps(data).encode("utf-8")
        return urllib.request.urlopen(
            urllib.request.Request(self.base_url + path, data=body, headers=headers),
            timeout=5,
        )

    def test_health_and_search_form_a_complete_local_agent_flow(self) -> None:
        with self.request("/health") as response:
            health = json.load(response)
        self.assertEqual(health["status"], "ok")
        self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))

        with self.request("/v1/search", data={"query": "测试怎么做？"}) as response:
            result = json.load(response)
        self.assertEqual(result["results"][0]["citation"], "项目/测试.md")
        self.assertEqual(result["results"][0]["snippet"], "本地检索成功")

    def test_search_requires_token_and_valid_json(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as missing_token:
            self.request("/v1/search", data={"query": "test"}, token="")
        self.assertEqual(missing_token.exception.code, 401)

        request = urllib.request.Request(
            self.base_url + "/v1/search",
            data=b"not-json",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer test-token",
            },
        )
        with self.assertRaises(urllib.error.HTTPError) as invalid_json:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(invalid_json.exception.code, 400)

    def test_brief_endpoint_returns_agent_ready_packet(self) -> None:
        with self.request("/v1/brief", data={"query": "测试", "as_of": "2026-08-13"}) as response:
            packet = json.load(response)
        self.assertEqual(packet["confidence"], "high")
        self.assertEqual(packet["evidence"][0]["citation"], "项目/测试.md")

    def test_http_rejects_unknown_routes_types_and_body_sizes(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as missing:
            self.request("/missing")
        self.assertEqual(missing.exception.code, 404)

        wrong_type = urllib.request.Request(
            self.base_url + "/v1/search",
            data=b"{}",
            headers={"Authorization": "Bearer test-token"},
        )
        with self.assertRaises(urllib.error.HTTPError) as unsupported:
            urllib.request.urlopen(wrong_type, timeout=5)
        self.assertEqual(unsupported.exception.code, 415)

        connection = http.client.HTTPConnection(
            "127.0.0.1", self.httpd.server_port, timeout=5
        )
        connection.putrequest("POST", "/v1/search")
        connection.putheader("Authorization", "Bearer test-token")
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", str(self.server_module.MAX_BODY_BYTES + 1))
        connection.endheaders()
        response = connection.getresponse()
        self.assertEqual(response.status, 413)
        response.read()
        connection.close()

    def test_cli_client_calls_service_and_prints_machine_readable_json(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(CLIENT_PATH),
                "search",
                "本地测试",
                "--base-url",
                self.base_url,
                "--token",
                "test-token",
                "--json",
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["query"], "本地测试")
        self.assertEqual(payload["results"][0]["citation"], "项目/测试.md")


class LocalMemoryRagSkillPackageTests(unittest.TestCase):
    def test_manage_helpers_keep_state_private_and_apply_semantic_config(self) -> None:
        manage = load_module("local_memory_rag_manage_helpers_test", MANAGE_PATH)
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            paths = manage.state_paths(root)
            state_root = root.resolve()
            self.assertEqual(paths["config"], state_root / "service.json")
            self.assertEqual(paths["lock"], state_root / "locks" / "zvec.lock")

            environment = manage.private_environment(root)
            self.assertEqual(
                environment["AGENT_MEMORY_STATE_DB"], str(state_root / "state.sqlite")
            )
            configured = manage.configured_environment(
                root,
                {
                    "vault_root": str(root / "vault"),
                    "semantic_python": str(root / "venv" / "python"),
                    "embedding_model": str(root / "model"),
                    "require_local_model": True,
                },
            )
            self.assertEqual(configured["AGENT_MEMORY_ROOT"], str(root / "vault"))
            self.assertEqual(configured["AGENT_MEMORY_REQUIRE_LOCAL_MODEL"], "true")

            with self.assertRaises(ValueError):
                manage.load_config(root)
            paths["config"].write_text("[]", encoding="utf-8")
            paths["config"].chmod(0o600)
            with self.assertRaises(ValueError):
                manage.load_config(root)
            paths["config"].write_text('{"vault_root": "/vault"}', encoding="utf-8")
            self.assertEqual(manage.load_config(root)["vault_root"], "/vault")
            paths["config"].chmod(0o644)
            self.assertTrue(manage.private_file_is_exposed(paths["config"], platform="posix"))
            self.assertFalse(manage.private_file_is_exposed(paths["config"], platform="nt"))

    def test_manage_dispatches_all_self_contained_operations(self) -> None:
        manage = load_module("local_memory_rag_manage_dispatch_test", MANAGE_PATH)
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            vault = root / "vault"
            vault.mkdir()
            configure_args = SimpleNamespace(
                vault_root=vault,
                state_root=root,
                semantic_python=root / "venv" / "python",
                managed_model=root / "model",
                model_manifest=root / "manifest.json",
                embedding_model="model-id",
                host_skill_root=[root / "host"],
                replace_config=True,
                json=True,
            )
            with mock.patch.object(manage, "run", return_value=0) as run_mock:
                self.assertEqual(manage.configure(configure_args), 0)
            configure_command = run_mock.call_args.args[0]
            self.assertIn(str(SKILL_ROOT), configure_command)
            self.assertIn("--replace-config", configure_command)

            config = {
                "vault_root": str(vault),
                "semantic_python": sys.executable,
                "embedding_model": "model-id",
                "require_local_model": False,
            }
            config_path = root / "service.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            config_path.chmod(0o600)
            index_args = SimpleNamespace(state_root=root, semantic=True, json=True)
            with mock.patch.object(manage, "run", side_effect=[0, 0]) as run_mock:
                self.assertEqual(manage.index(index_args), 0)
            self.assertEqual(run_mock.call_count, 2)
            self.assertIn("--scan", run_mock.call_args_list[1].args[0])

            start_args = SimpleNamespace(state_root=root, host="127.0.0.1", port=9876)
            with mock.patch.object(manage, "run", return_value=0) as run_mock:
                self.assertEqual(manage.start(start_args), 0)
            self.assertIn("9876", run_mock.call_args.args[0])

            for command in ("health", "search"):
                args = SimpleNamespace(
                    command=command,
                    query="本地证据",
                    limit=3,
                    state_root=root,
                    base_url="http://127.0.0.1:8765",
                    json=True,
                )
                with self.subTest(command=command), mock.patch.object(
                    manage, "run", return_value=0
                ) as run_mock:
                    self.assertEqual(manage.client(args), 0)
                    if command == "search":
                        self.assertIn("本地证据", run_mock.call_args.args[0])

    def test_packaged_runtime_matches_the_reviewed_repository_sources(self) -> None:
        for name in (
            "agent_memory_env.py",
            "agent_memory_index.py",
            "agent_memory_search.py",
            "agent_memory_zvec_index.py",
        ):
            with self.subTest(name=name):
                self.assertEqual(
                    (SKILL_ROOT / "scripts" / name).read_bytes(),
                    (REPO_ROOT / "scripts" / name).read_bytes(),
                )

    def test_release_archive_is_deterministic_private_and_smoke_tested(self) -> None:
        packager = load_module("local_memory_rag_packager_test", PACKAGE_PATH)
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            first = root / "first.zip"
            second = root / "second.zip"
            first_result = packager.build_archive(first)
            second_result = packager.build_archive(second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(first_result["sha256"], second_result["sha256"])
            self.assertEqual(first_result["file_count"], len(packager.PUBLIC_FILES))

            with zipfile.ZipFile(first) as archive:
                names = set(archive.namelist())
                self.assertEqual(
                    names,
                    {
                        f"local-memory-rag/{path.as_posix()}"
                        for path in packager.PUBLIC_FILES
                    },
                )
                for info in archive.infolist():
                    data = archive.read(info)
                    self.assertNotRegex(data, rb"/Users/[A-Za-z0-9._-]+/")
                    tokens = re.findall(rb"[a-z][a-z0-9_-]{3,}", data.lower())
                    token_hashes = {hashlib.sha256(token).hexdigest() for token in tokens}
                    self.assertNotIn(
                        "fe672956d62c2de053986d1c1021b0787dde9cd3f16dd98c65aaba6ba705631b",
                        token_hashes,
                    )
                    self.assertNotIn(
                        "0150fde5ce19785699480c46b7f3e470df71b27004e2569d489d3db2d97dae06",
                        token_hashes,
                    )
                    self.assertNotIn(Path(info.filename).name, packager.FORBIDDEN_NAMES)
                    self.assertNotIn(Path(info.filename).suffix, packager.FORBIDDEN_SUFFIXES)
                archive.extractall(root / "extracted")

            extracted = root / "extracted" / "local-memory-rag"
            for script in (
                "agent_memory_env.py",
                "agent_memory_index.py",
                "agent_memory_search.py",
                "agent_memory_zvec_index.py",
                "client.py",
                "configure.py",
                "download_model.py",
                "manage.py",
                "server.py",
            ):
                source = (extracted / "scripts" / script).read_text(encoding="utf-8")
                compile(source, script, "exec")
            completed = subprocess.run(
                [sys.executable, str(extracted / "scripts" / "client.py"), "--help"],
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn("health", completed.stdout)

            server = load_module(
                "local_memory_rag_extracted_server_test",
                extracted / "scripts" / "server.py",
            )
            self.assertEqual(server.default_runtime_root(), extracted.resolve())

    def test_extracted_archive_indexes_and_searches_without_an_external_repo(self) -> None:
        packager = load_module("local_memory_rag_standalone_packager_test", PACKAGE_PATH)
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            archive_path = root / "skill.zip"
            packager.build_archive(archive_path)
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(root / "extracted")
            skill = root / "extracted" / "local-memory-rag"
            vault = root / "private-vault"
            state = root / "private-state"
            vault.mkdir()
            (vault / "发布决策.md").write_text(
                "# 发布决策\n\n当前有效结论：提交前必须先完成独立压缩包验收。\n",
                encoding="utf-8",
            )

            configured = subprocess.run(
                [
                    sys.executable,
                    str(skill / "scripts" / "manage.py"),
                    "configure",
                    "--vault-root",
                    str(vault),
                    "--state-root",
                    str(state),
                    "--json",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                timeout=20,
                check=False,
            )
            self.assertEqual(configured.returncode, 0, configured.stdout + configured.stderr)

            indexed = subprocess.run(
                [
                    sys.executable,
                    str(skill / "scripts" / "manage.py"),
                    "index",
                    "--state-root",
                    str(state),
                    "--json",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(indexed.returncode, 0, indexed.stdout + indexed.stderr)
            self.assertTrue((state / "state.sqlite").is_file())

            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(skill / "scripts" / "manage.py"),
                    "start",
                    "--state-root",
                    str(state),
                    "--port",
                    str(port),
                ],
                cwd=root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                health_command = [
                    sys.executable,
                    str(skill / "scripts" / "manage.py"),
                    "health",
                    "--state-root",
                    str(state),
                    "--base-url",
                    f"http://127.0.0.1:{port}",
                    "--json",
                ]
                deadline = time.monotonic() + 10
                health = None
                while time.monotonic() < deadline:
                    health = subprocess.run(
                        health_command,
                        cwd=root,
                        text=True,
                        capture_output=True,
                        timeout=5,
                        check=False,
                    )
                    if health.returncode == 0:
                        break
                    time.sleep(0.1)
                self.assertIsNotNone(health)
                self.assertEqual(health.returncode, 0, health.stdout + health.stderr)

                searched = subprocess.run(
                    [
                        sys.executable,
                        str(skill / "scripts" / "manage.py"),
                        "search",
                        "独立压缩包验收",
                        "--state-root",
                        str(state),
                        "--base-url",
                        f"http://127.0.0.1:{port}",
                        "--json",
                    ],
                    cwd=root,
                    text=True,
                    capture_output=True,
                    timeout=20,
                    check=False,
                )
                self.assertEqual(searched.returncode, 0, searched.stdout + searched.stderr)
                payload = json.loads(searched.stdout)
                self.assertEqual(payload["mode"], "keyword_fallback")
                self.assertEqual(payload["results"][0]["citation"], "发布决策.md")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                if process.stdout is not None:
                    process.stdout.close()
                if process.stderr is not None:
                    process.stderr.close()

    def test_skill_package_contains_only_portable_public_paths(self) -> None:
        required = (
            SKILL_ROOT / "SKILL.md",
            SKILL_ROOT / "OPEN_SOURCE_NOTICE.md",
            SKILL_ROOT / "info.json",
            SKILL_ROOT / "meta.json",
            SKILL_ROOT / "agents" / "openai.yaml",
            SERVER_PATH,
            CLIENT_PATH,
            CONFIGURE_PATH,
            DOWNLOAD_MODEL_PATH,
            MANAGE_PATH,
            SKILL_ROOT / "requirements.txt",
            SKILL_ROOT / "scripts" / "run.ps1",
            SKILL_ROOT / "scripts" / "run.sh",
            SKILL_ROOT / "tests" / "test_skill.py",
            SKILL_ROOT / "references" / "setup.md",
            SKILL_ROOT / "references" / "host-integration.md",
        )
        for path in required:
            with self.subTest(path=path):
                self.assertTrue(path.is_file())
        for path in SKILL_ROOT.rglob("*"):
            if (
                not path.is_file()
                or path.suffix == ".pyc"
                or "__pycache__" in path.parts
            ):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            self.assertNotRegex(text, r"/" + r"Users/[A-Za-z0-9._-]+/")

    def test_store_metadata_declares_the_local_model_and_private_rag_use_cases(self) -> None:
        info = json.loads((SKILL_ROOT / "info.json").read_text(encoding="utf-8"))
        meta = json.loads((SKILL_ROOT / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(info["models"][0]["model_id"], "google/embeddinggemma-300m")
        self.assertIn("model.safetensors", info["models"][0]["required_files"])
        self.assertEqual(meta["name"], "local-memory-rag")
        self.assertGreaterEqual(len(meta["use_cases"]), 2)

    def test_search_cli_accepts_query_from_stdin_without_echoing_it(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "agent_memory_search.py"),
                "--query-stdin",
                "--limit",
                "1",
                "--no-zvec",
                "--json",
            ],
            cwd=REPO_ROOT,
            input="字段规范",
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["query"], "字段规范")

    def test_configure_creates_private_config_token_and_host_links(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            runtime = root / "runtime"
            vault = root / "vault"
            state = root / "state"
            host = root / "qoder-skills"
            (runtime / "scripts").mkdir(parents=True)
            (runtime / "scripts" / "agent_memory_search.py").touch()
            vault.mkdir()
            completed = subprocess.run(
                [
                    sys.executable,
                    str(CONFIGURE_PATH),
                    "--runtime-root",
                    str(runtime),
                    "--vault-root",
                    str(vault),
                    "--state-root",
                    str(state),
                    "--host-skill-root",
                    str(host),
                    "--json",
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                timeout=20,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            payload = json.loads(completed.stdout)
            token_file = Path(payload["token_file"])
            config_file = Path(payload["config_file"])
            self.assertEqual(token_file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(config_file.stat().st_mode & 0o777, 0o600)
            self.assertNotIn(token_file.read_text(encoding="utf-8").strip(), completed.stdout)
            installed = host / "local-memory-rag"
            self.assertTrue(installed.is_symlink())
            self.assertEqual(installed.resolve(), SKILL_ROOT.resolve())

    def test_configure_helpers_preserve_private_files_and_refuse_overwrites(self) -> None:
        configure = load_module("local_memory_rag_configure_helpers_test", CONFIGURE_PATH)
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            private = root / "state" / "token"
            self.assertTrue(configure.write_private(private, "first"))
            self.assertFalse(configure.write_private(private, "second"))
            self.assertEqual(private.read_text(encoding="utf-8"), "first")
            self.assertTrue(configure.write_private(private, "third", replace=True))
            self.assertEqual(private.read_text(encoding="utf-8"), "third")
            self.assertEqual(private.stat().st_mode & 0o777, 0o600)

            host = root / "host"
            link = configure.install_host_link(host)
            self.assertEqual(configure.install_host_link(host), link)
            link.unlink()
            link.mkdir()
            with self.assertRaises(FileExistsError):
                configure.install_host_link(host)

    def test_configure_main_rejects_missing_runtime_and_vault(self) -> None:
        configure = load_module("local_memory_rag_configure_errors_test", CONFIGURE_PATH)
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            cases = (
                SimpleNamespace(runtime_root=root / "missing", vault_root=root, state_root=root),
                SimpleNamespace(runtime_root=root, vault_root=root / "missing", state_root=root),
            )
            (root / "scripts").mkdir()
            (root / "scripts" / "agent_memory_search.py").touch()
            for partial in cases:
                args = SimpleNamespace(
                    **vars(partial),
                    semantic_python=None,
                    embedding_model="model",
                    managed_model=None,
                    model_manifest=None,
                    host_skill_root=[],
                    replace_config=False,
                    json=False,
                )
                with self.subTest(runtime=args.runtime_root, vault=args.vault_root), mock.patch.object(
                    configure, "parse_args", return_value=args
                ), mock.patch("sys.stderr", new_callable=io.StringIO):
                    self.assertEqual(configure.main(), 2)

    def test_model_downloader_resumes_and_writes_verified_manifest(self) -> None:
        downloader = load_module("local_memory_rag_model_downloader_test", DOWNLOAD_MODEL_PATH)
        content = b"verified local model fixture"
        expected = {
            "fixture.bin": {
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        }

        class FixtureHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def do_GET(self):
                start = 0
                raw_range = self.headers.get("Range", "")
                if raw_range.startswith("bytes="):
                    start = int(raw_range[6:].split("-", 1)[0])
                body = content[start:]
                self.send_response(206 if start else 200)
                self.send_header("Content-Length", str(len(body)))
                if start:
                    self.send_header(
                        "Content-Range", f"bytes {start}-{len(content) - 1}/{len(content)}"
                    )
                self.end_headers()
                self.wfile.write(body)

        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as raw_root:
                root = Path(raw_root)
                partial = root / "fixture.bin.partial"
                partial.write_bytes(content[:8])
                manifest = downloader.download_snapshot(
                    root,
                    base_url=f"http://127.0.0.1:{httpd.server_port}",
                    revision="test-revision",
                    files=expected,
                    model_id="test/model",
                    license_name="test-license",
                    terms_url="https://example.invalid/terms",
                )
                self.assertEqual((root / "fixture.bin").read_bytes(), content)
                self.assertFalse(partial.exists())
                payload = json.loads(manifest.read_text(encoding="utf-8"))
                self.assertEqual(payload["revision"], "test-revision")
                self.assertEqual(payload["files"], expected)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)

    def test_model_downloader_detects_bad_content_and_main_errors(self) -> None:
        downloader = load_module("local_memory_rag_model_downloader_errors_test", DOWNLOAD_MODEL_PATH)

        class Response:
            status = 200

            def __init__(self, content: bytes):
                self.stream = io.BytesIO(content)

            def getcode(self):
                return self.status

            def read(self, size=-1):
                return self.stream.read(size)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            target = root / "fixture.bin"
            partial = root / "fixture.bin.partial"
            partial.write_bytes(b"too-large")
            expected = {"size": 3, "sha256": hashlib.sha256(b"good").hexdigest()}
            with mock.patch.object(
                downloader.urllib.request, "urlopen", return_value=Response(b"bad")
            ), self.assertRaises(RuntimeError):
                downloader._download_file("https://example.invalid/file", target, expected)
            self.assertEqual(partial.read_bytes(), b"bad")

        args = SimpleNamespace(destination=Path("/tmp/model"), json=True)
        manifest = Path("/tmp/model/model-manifest.json")
        with mock.patch.object(downloader, "parse_args", return_value=args), mock.patch.object(
            downloader, "download_snapshot", return_value=manifest
        ), mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.assertEqual(downloader.main(), 0)
        self.assertEqual(json.loads(stdout.getvalue())["revision"], downloader.REVISION)

        with mock.patch.object(downloader, "parse_args", return_value=args), mock.patch.object(
            downloader, "download_snapshot", side_effect=RuntimeError("bad model")
        ), mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            self.assertEqual(downloader.main(), 2)
        self.assertIn("bad model", stderr.getvalue())

    def test_client_helpers_and_main_cover_human_and_error_flows(self) -> None:
        client = load_module("local_memory_rag_client_helpers_test", CLIENT_PATH)
        with tempfile.TemporaryDirectory() as raw_root:
            token_file = Path(raw_root) / "token"
            self.assertEqual(client.load_token("", token_file), "")
            token_file.write_text("\n", encoding="utf-8")
            token_file.chmod(0o600)
            with self.assertRaises(ValueError):
                client.load_token("", token_file)
            token_file.write_text("secret", encoding="utf-8")
            token_file.chmod(0o644)
            with self.assertRaises(ValueError):
                client.load_token("", token_file)

        with self.assertRaises(ValueError):
            client.request_json("http://127.0.0.1", "/health", "")
        with mock.patch.object(
            client.LOCAL_OPENER,
            "open",
            side_effect=urllib.error.URLError("offline"),
        ), self.assertRaises(RuntimeError):
            client.request_json("http://127.0.0.1:1", "/health", "token")

        health = {
            "service": "local-memory-rag",
            "status": "ok",
            "runtime_ready": True,
            "index_ready": True,
            "semantic_ready": True,
        }
        search = {
            "query": "test",
            "mode": "hybrid",
            "results": [
                {
                    "citation": "项目/test.md",
                    "title": "Test",
                    "snippet": "Found",
                    "sources": ["zvec"],
                    "score": 1,
                }
            ],
            "warnings": ["warning"],
        }
        with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            client.print_human(health)
            client.print_human(search)
        self.assertIn("semantic=True", stdout.getvalue())
        self.assertIn("mode=hybrid", stdout.getvalue())
        self.assertIn("warning: warning", stdout.getvalue())

        args = SimpleNamespace(
            command="search",
            token="token",
            token_file=Path("missing"),
            base_url="http://local",
            query="test",
            limit=3,
            track="project",
            memory_type="",
            project_id="",
            user_id="",
            agent_id="",
            agent_scope="",
            app_id="",
            session_id="",
            status="",
            has_open_loop=True,
            include_inactive=False,
            include_supporting=False,
            json=False,
        )
        with mock.patch.object(client, "parse_args", return_value=args), mock.patch.object(
            client, "request_json", return_value=search
        ) as request_mock, mock.patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(client.main(), 0)
        self.assertEqual(
            request_mock.call_args.args[3]["filters"],
            {"track": "project", "has_open_loop": True},
        )

        args.command = "health"
        args.json = True
        with mock.patch.object(client, "parse_args", return_value=args), mock.patch.object(
            client, "request_json", side_effect=RuntimeError("unavailable")
        ), mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            self.assertEqual(client.main(), 2)
        self.assertIn("unavailable", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
