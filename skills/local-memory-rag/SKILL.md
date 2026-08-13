---
name: local-memory-rag
description: Search or recall a private local Markdown/Obsidian knowledge vault through a loopback-only hybrid RAG service and return source-cited evidence without uploading files or exposing absolute paths. Use when the user asks Qoder, WorkBuddy, TRAE Work, Claude Code, Codex, or another Agent to 检索/查找/回忆本地笔记、项目决策、工作流、偏好、会议纪要或私人知识，or to search/recall/query private local notes, a personal knowledge base, or a local second brain with citations. Prefer this Skill whenever the answer should come from private on-device knowledge rather than cloud search.
---

# Local Memory RAG

Use this Skill only through the bundled client for ordinary retrieval. Keep the model and vault on the local machine. On Windows, the fixed installation and management entry is `scripts\run.ps1`; on macOS/Linux the equivalent entry is `scripts/run.sh`. Do not call `server.py`, `download_model.py`, or the runtime indexing scripts directly for an ordinary search request.

## Search workflow

1. Check the service before the first search:

```bash
python3 {{SKILL_DIR}}/scripts/client.py health --json
```

2. Turn the user's request into a focused retrieval query. Preserve distinctive names, dates, and decision terms.
3. Search the private vault:

```bash
python3 {{SKILL_DIR}}/scripts/client.py search "<query>" --limit 5 --json
```

4. Read `mode` before answering:
   - `hybrid`: SQLite keyword retrieval and local Zvec semantic retrieval contributed.
   - `keyword_fallback`: semantic retrieval was unavailable; disclose the fallback when it could affect recall.
5. Answer only from returned evidence. Cite every material claim as `[relative/path.md]`.
6. If evidence is weak or contradictory, narrow the query and search again. Do not invent missing facts.

If `health` fails, stop and tell the user that the local service must be started. Never replace a failed local lookup with cloud search.

Use filters only when the request establishes them. Example:

```bash
python3 {{SKILL_DIR}}/scripts/client.py search "当前发布边界" \
  --track project --status active --limit 8 --json
```

## Privacy boundaries

- Never send vault text, queries, model inputs, or results to a cloud API as part of this Skill.
- Never bind the service to a LAN or public address. Only loopback addresses are accepted.
- Never reveal or reconstruct absolute file paths; cite the returned relative `citation` value.
- Never expose `LOCAL_MEMORY_RAG_TOKEN` in the answer, logs, screenshots, or committed files.
- Treat every hit as a candidate. Conflicting current facts require the user to choose or the underlying Markdown to be verified.
- This Skill is read-only. Do not edit, delete, index, or publish vault content unless the user separately asks for that action.

For installation and local model setup, read [references/setup.md](references/setup.md). For Qoder, WorkBuddy, and TRAE Work placement and verification, read [references/host-integration.md](references/host-integration.md). Project-level provenance and the boundary of the contest modifications are documented in [OPEN_SOURCE_NOTICE.md](OPEN_SOURCE_NOTICE.md).
