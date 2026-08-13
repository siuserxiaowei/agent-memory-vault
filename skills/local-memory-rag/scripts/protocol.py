"""Deterministic production-memory protocol built on top of local retrieval.

This module deliberately does not call an LLM.  It turns private retrieval
rows into an auditable packet an Agent can consume without guessing what is
known, stale, contradictory, or still open.
"""
from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from typing import Any, Mapping, Sequence


def _date(value: object) -> dt.date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        return None


def _key(row: Mapping[str, object]) -> str:
    project = str(row.get("project_id") or "").strip().lower()
    title = str(row.get("title") or row.get("citation") or "").strip().lower()
    # A stable key lets us detect multiple memories about one decision without
    # exposing their private absolute paths.
    return re.sub(r"\s+", " ", f"{project}|{title}").strip("|")


def build_answer_packet(
    query: str,
    search_payload: Mapping[str, object],
    *,
    as_of: str = "",
    max_age_days: int = 180,
) -> dict[str, object]:
    """Create an evidence-first work brief from the public search response."""
    raw_results = search_payload.get("results", [])
    rows = [row for row in raw_results if isinstance(row, dict)] if isinstance(raw_results, list) else []
    evidence: list[dict[str, object]] = []
    stale: list[dict[str, object]] = []
    open_loops: list[dict[str, object]] = []
    reference_date = _date(as_of) or dt.date.today()
    for row in rows:
        item = {
            "citation": str(row.get("citation") or ""),
            "title": str(row.get("title") or ""),
            "snippet": str(row.get("snippet") or "")[:800],
            "sources": list(row.get("sources", [])) if isinstance(row.get("sources", []), list) else [],
            "score": row.get("score", 0),
        }
        for field in ("memory_type", "track", "project_id", "status", "verified_at"):
            if str(row.get(field) or "").strip():
                item[field] = str(row[field])
        evidence.append(item)
        verified = _date(row.get("verified_at"))
        if verified and (reference_date - verified).days > max_age_days:
            stale.append({"citation": item["citation"], "verified_at": item["verified_at"], "age_days": (reference_date - verified).days})
        if bool(row.get("has_open_loop")):
            open_loops.append({"citation": item["citation"], "title": item["title"], "next_step": item["snippet"]})

    groups: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        key = _key(row)
        if key:
            groups[key].append(row)
    conflicts: list[dict[str, object]] = []
    for key, group in groups.items():
        snippets = {str(row.get("snippet") or "").strip() for row in group if str(row.get("snippet") or "").strip()}
        statuses = {str(row.get("status") or "").strip() for row in group if str(row.get("status") or "").strip()}
        if len(group) > 1 and (len(snippets) > 1 or len(statuses) > 1):
            conflicts.append({
                "topic": key,
                "citations": [str(row.get("citation") or "") for row in group],
                "statuses": sorted(statuses),
                "detail": "同一主题存在不同证据或状态，回答前需要核对原文。",
            })

    warnings = [str(value) for value in search_payload.get("warnings", [])] if isinstance(search_payload.get("warnings", []), list) else []
    uncertainties: list[str] = []
    if not evidence:
        uncertainties.append("本地记忆中没有足够证据，不能据此下结论。")
    if search_payload.get("degraded"):
        uncertainties.append("语义索引不可用，本次结果只来自关键词检索，召回可能不完整。")
    if stale:
        uncertainties.append(f"{len(stale)} 条证据超过 {max_age_days} 天未核验。")
    if conflicts:
        uncertainties.append("检索结果存在冲突，不能把任一版本当作当前事实。")

    if not evidence:
        confidence = "low"
    elif conflicts or stale or search_payload.get("degraded"):
        confidence = "medium"
    elif len(evidence) >= 2:
        confidence = "high"
    else:
        confidence = "medium"

    if evidence:
        lead = evidence[0]
        summary = f"找到 {len(evidence)} 条本地证据；首条为“{lead['title'] or lead['citation']}” [{lead['citation']}]。"
    else:
        summary = "没有找到可引用的本地证据。"
    next_steps = ["核对引用文件中的原文和核验日期。"]
    if open_loops:
        next_steps.insert(0, f"处理 {len(open_loops)} 个未闭环事项，并回写新的核验结果。")
    if conflicts:
        next_steps.insert(0, "先解决冲突证据，再决定采用哪个版本。")
    if not evidence:
        next_steps = ["补充更具体的项目名、日期或决策关键词后重新检索。"]

    return {
        "query": query,
        "summary": summary,
        "confidence": confidence,
        "evidence": evidence,
        "uncertainties": uncertainties,
        "conflicts": conflicts,
        "open_loops": open_loops,
        "next_steps": next_steps,
        "stale_evidence": stale,
        "retrieval": {
            "mode": search_payload.get("mode", ""),
            "degraded": bool(search_payload.get("degraded")),
            "result_count": len(evidence),
            "as_of": as_of or reference_date.isoformat(),
            "warnings": warnings,
        },
    }
