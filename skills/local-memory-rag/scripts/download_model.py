#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Mapping


MODEL_ID = "google/embeddinggemma-300m"
REVISION = "480ee9b0e4761c35cf4f8295236b7b01b256b8cf"
BASE_URL = "https://www.modelscope.cn/models/google/embeddinggemma-300m/resolve"
LICENSE_NAME = "Gemma Terms of Use"
TERMS_URL = "https://ai.google.dev/gemma/terms"
DEFAULT_DESTINATION = Path("~/.config/local-memory-rag/models/embeddinggemma-300m").expanduser()
CHUNK_SIZE = 1024 * 1024

# File sizes and hashes come from the public ModelScope repository at REVISION.
FILES: dict[str, dict[str, object]] = {
    "1_Pooling/config.json": {
        "size": 312,
        "sha256": "35bbd47d7fdf1e378db6130bcc668b09d1aa67a7bbf7c8f89a9c71f4cc8ebcc6",
    },
    "2_Dense/config.json": {
        "size": 134,
        "sha256": "0661e5e0b67b8f8408ab31ab5d073a78972fc1dc24a49992a64796557e4f9e53",
    },
    "2_Dense/model.safetensors": {
        "size": 9437272,
        "sha256": "c327f2acb00149676ade24a75e11eb6ebbd367f9ee050267ba56829d2979f702",
    },
    "3_Dense/config.json": {
        "size": 134,
        "sha256": "8c4575c49353d63fb907878856ba94384635c3b2711fd5b7439e7f71888c66fc",
    },
    "3_Dense/model.safetensors": {
        "size": 9437272,
        "sha256": "ffb6cc5162e11e2ce6bc2367e121ee3bbbc4e82e1ee26826bd7573d4948d81b8",
    },
    "added_tokens.json": {
        "size": 35,
        "sha256": "50b2f405ba56a26d4913fd772089992252d7f942123cc0a034d96424221ba946",
    },
    "config.json": {
        "size": 1488,
        "sha256": "8f863f76e2d9c710cc833dc92efa898c9adfd41031c786507cc6b0e49c2e3e68",
    },
    "config_sentence_transformers.json": {
        "size": 997,
        "sha256": "8eadac15526f83d8950aa8d962a7f4f6e3d678bea71689960194561f33a5f64f",
    },
    "configuration.json": {
        "size": 77,
        "sha256": "007c616ed9187f4f3d6096ed2d55cece33c3f48866dbd7bc6afefcb9645a37c1",
    },
    "generation_config.json": {
        "size": 133,
        "sha256": "1fb1efd221c1ca88a736d1b36cb47d754c177677e222acb3b1e5424c5d664870",
    },
    "model.safetensors": {
        "size": 1211486072,
        "sha256": "cbf5a78393b6a033e0b8a63a57549964f7ed5c6fbeb4ba0694214f36123f2fd2",
    },
    "modules.json": {
        "size": 573,
        "sha256": "5b5649645fb756dad1a8e2efe7872d3bb32bc00b93c95f276dd17f474eedccdc",
    },
    "sentence_bert_config.json": {
        "size": 58,
        "sha256": "5ea26221ce733ace29a3897360e7c6ac8816b2ca0f7306657d69e594fece7325",
    },
    "special_tokens_map.json": {
        "size": 662,
        "sha256": "2f7b0adf4fb469770bb1490e3e35df87b1dc578246c5e7e6fc76ecf33213a397",
    },
    "tokenizer.json": {
        "size": 33385008,
        "sha256": "6852f8d561078cc0cebe70ca03c5bfdd0d60a45f9d2e0e1e4cc05b68e9ec329e",
    },
    "tokenizer.model": {
        "size": 4689074,
        "sha256": "1299c11d7cf632ef3b4e11937501358ada021bbdf7c47638d13c0ee982f2e79c",
    },
    "tokenizer_config.json": {
        "size": 1155346,
        "sha256": "9076840490613047bc9115963ee96b7702018b0d26ba644240bf856efda93118",
    },
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


def is_verified(path: Path, expected: Mapping[str, object]) -> bool:
    return (
        path.is_file()
        and path.stat().st_size == int(expected["size"])
        and sha256_file(path) == str(expected["sha256"])
    )


def _download_file(url: str, target: Path, expected: Mapping[str, object]) -> None:
    partial = target.with_name(target.name + ".partial")
    target.parent.mkdir(parents=True, exist_ok=True)
    expected_size = int(expected["size"])
    if partial.is_file() and partial.stat().st_size > expected_size:
        partial.unlink()
    start = partial.stat().st_size if partial.is_file() else 0
    headers = {"User-Agent": "local-memory-rag/1.0"}
    if start:
        headers["Range"] = f"bytes={start}-"
    request = urllib.request.Request(url, headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=120)
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and start:
            partial.unlink(missing_ok=True)
            return _download_file(url, target, expected)
        raise RuntimeError(f"model download failed with HTTP {exc.code}: {target.name}") from exc
    with response:
        status = getattr(response, "status", response.getcode())
        append = bool(start and status == 206)
        mode = "ab" if append else "wb"
        with partial.open(mode) as handle:
            while True:
                block = response.read(CHUNK_SIZE)
                if not block:
                    break
                handle.write(block)
    if not is_verified(partial, expected):
        raise RuntimeError(f"model file failed size/hash verification: {target.name}")
    os.replace(partial, target)


def download_snapshot(
    destination: Path,
    *,
    base_url: str,
    revision: str,
    files: Mapping[str, Mapping[str, object]],
    model_id: str,
    license_name: str,
    terms_url: str,
) -> Path:
    root = destination.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    for index, (rel_path, expected) in enumerate(files.items(), 1):
        target = root / rel_path
        if is_verified(target, expected):
            print(f"[{index}/{len(files)}] verified {rel_path}", file=sys.stderr)
            continue
        quoted_path = "/".join(urllib.parse.quote(part) for part in rel_path.split("/"))
        url = f"{base_url.rstrip('/')}/{urllib.parse.quote(revision)}/{quoted_path}"
        print(f"[{index}/{len(files)}] downloading {rel_path}", file=sys.stderr)
        _download_file(url, target, expected)
    manifest = root / "model-manifest.json"
    payload = {
        "schema_version": 1,
        "model_id": model_id,
        "source": "ModelScope",
        "source_url": base_url,
        "revision": revision,
        "root": str(root),
        "embedding_dim": 768,
        "license": license_name,
        "terms_url": terms_url,
        "files": files,
    }
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest.chmod(0o600)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download and verify the pinned public ModelScope EmbeddingGemma snapshot."
    )
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        manifest = download_snapshot(
            args.destination,
            base_url=BASE_URL,
            revision=REVISION,
            files=FILES,
            model_id=MODEL_ID,
            license_name=LICENSE_NAME,
            terms_url=TERMS_URL,
        )
    except (OSError, RuntimeError, urllib.error.URLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    payload = {
        "ok": True,
        "model_root": str(manifest.parent),
        "model_manifest": str(manifest),
        "model_id": MODEL_ID,
        "revision": REVISION,
        "license": LICENSE_NAME,
        "terms_url": TERMS_URL,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for key, value in payload.items():
            print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
