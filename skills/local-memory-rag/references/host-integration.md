# Host integration

The Skill uses the same self-contained directory in each host. Configure and start it through `scripts\\run.ps1` on Windows or `scripts/run.sh` on macOS/Linux; no separate repository clone is required. By default both client and server read the bearer token from `~/.config/local-memory-rag/token`, which must have mode `0600`. Keep it out of `SKILL.md`, screenshots, logs, and Git. Use `LOCAL_MEMORY_RAG_URL` only when changing the loopback port.

## Qoder

Copy or link `skills/local-memory-rag` into the Qoder Skills directory recognized by the installed Qoder version. Restart or refresh Skills, then ask:

> 从我的本地知识库检索“示例项目当前发布边界”，给出相对文件引用，不要使用云端搜索。

Verify that Qoder invokes the bundled client, the response reports `hybrid`, and every answer claim carries a relative Markdown citation.

## WorkBuddy

Import the same Skill directory through WorkBuddy's local Skill management surface. Keep the server running on `127.0.0.1`. Use the same verification prompt and record that the client command was called successfully.

## TRAE Work

Place the Skill directory in the workspace or user Skills location supported by TRAE Work. Reload the workspace, use the same verification prompt, and confirm that no browser or cloud search tool was called.

## Acceptance checklist for every host

1. `health` returns `runtime_ready=true` and `index_ready=true`.
2. A known note is returned with its relative `citation`.
3. A semantic paraphrase returns `mode=hybrid` when the local model and Zvec are ready.
4. Disconnect external networking and repeat the semantic query successfully.
5. Search an unknown fact and confirm the Agent says evidence is insufficient.
6. Confirm the transcript, screenshot, and output contain no token, absolute private path, or private source document beyond the minimal returned snippet.
