# Setup

The release zip is self-contained: it includes the SQLite indexer, hybrid search runtime, Zvec adapter, HTTP server, client, and fixed Windows entry point. A separate `agent-memory-vault` clone is not required. Private Markdown, bearer tokens, SQLite state, vectors, and model weights stay outside the Skill directory and are never packaged.

The verified contest path is macOS with Python 3.12. The same runtime includes a Windows-compatible lock backend and `scripts\run.ps1`; real Windows hardware remains a declared verification gap. OpenVINO is not claimed by this version. The verified semantic backend is SentenceTransformers/PyTorch on CPU.

## Prerequisites

- Python 3.11 or 3.12
- An extracted `local-memory-rag` Skill directory
- A private Markdown or Obsidian vault
- About 3.5 GB free memory for semantic mode

Use the fixed entry on Windows:

```powershell
scripts\run.ps1 --help
```

On macOS/Linux, use:

```bash
scripts/run.sh --help
```

The examples below use PowerShell. Replace `scripts\run.ps1` with `scripts/run.sh` on macOS/Linux.

## 1. Configure private state

Keyword search uses only the Python standard library and is available before installing the semantic dependencies:

```powershell
scripts\run.ps1 configure `
  --vault-root "D:\Private\MarkdownVault" `
  --state-root "$HOME\.config\local-memory-rag" `
  --json
```

Configuration creates a private `service.json` and bearer-token file. Existing files are preserved unless `--replace-config` is explicit. The token value is never printed.

## 2. Build the SQLite index

```powershell
scripts\run.ps1 index `
  --state-root "$HOME\.config\local-memory-rag" `
  --json
```

This scans local Markdown into a derived SQLite/FTS index. The Markdown files remain the source of truth. Re-run the same command after notes change.

## 3. Optional semantic mode

Create an isolated Python environment, then install the pinned critical dependencies:

```powershell
python -m venv "$HOME\.config\local-memory-rag\.venv"
& "$HOME\.config\local-memory-rag\.venv\Scripts\python.exe" -m pip install -r requirements.txt
```

Download and verify the pinned ModelScope snapshot once. This network action is explicit and separate from search:

```powershell
& "$HOME\.config\local-memory-rag\.venv\Scripts\python.exe" scripts\download_model.py --json
```

Downloading the complete snapshot requires accepting and complying with the [Gemma Terms of Use](https://ai.google.dev/gemma/terms). The downloader pins revision `480ee9b0e4761c35cf4f8295236b7b01b256b8cf`, verifies every file with SHA-256, resumes `.partial` files, atomically promotes verified downloads, and writes a private `model-manifest.json`.

Reconfigure with the managed local model and semantic Python, then build vectors:

```powershell
scripts\run.ps1 configure `
  --vault-root "D:\Private\MarkdownVault" `
  --state-root "$HOME\.config\local-memory-rag" `
  --semantic-python "$HOME\.config\local-memory-rag\.venv\Scripts\python.exe" `
  --managed-model "$HOME\.config\local-memory-rag\models\embeddinggemma-300m" `
  --model-manifest "$HOME\.config\local-memory-rag\models\embeddinggemma-300m\model-manifest.json" `
  --replace-config --json

scripts\run.ps1 index `
  --state-root "$HOME\.config\local-memory-rag" `
  --semantic --json
```

## 4. Start and query

Start the loopback-only service in one terminal:

```powershell
scripts\run.ps1 start --state-root "$HOME\.config\local-memory-rag"
```

Use another terminal to verify and search:

```powershell
scripts\run.ps1 health --state-root "$HOME\.config\local-memory-rag" --json
scripts\run.ps1 search "示例项目当前状态" --state-root "$HOME\.config\local-memory-rag" --json
```

Interpret `mode` honestly:

- `hybrid`: at least one returned result used the local Zvec semantic index.
- `keyword_fallback`: SQLite worked but semantic retrieval was unavailable or did not contribute.

Every service bind is validated as loopback-only. Search subprocesses remove proxy variables and force Hugging Face/Transformers offline mode. Public results include bounded evidence and relative citations, never absolute vault paths.

## Acceptance check

The packaged unit test can run without a private vault:

```powershell
tests\test.ps1
```

Repository CI additionally extracts the release zip into a temporary directory, configures a temporary Markdown vault, builds SQLite, starts the loopback service, and performs a keyword search without an external repository. A semantic acceptance run additionally requires the locally downloaded model and Zvec index.
