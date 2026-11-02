"""Read-only observability: project logs / tasks / application_runs into traces.

traceId mapping (MVP, no separate obs table):
- chat | retrieval  → log.id (== requestId); payload.traceId mirrors it
- application       → application_run.id; payload.traceId mirrors it
- import / build    → task.id; task.traceId and import log.traceId mirror it

Missing domains return empty arrays. Token/usage never fabricated.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from .db import db_session, get_entity, list_entities, put_entity
from .security import Actor, require_manager

router = APIRouter(prefix="/observability", tags=["observability"])

RootType = Literal["chat", "retrieval", "import", "application"]

BUILD_PIPELINE = (
    "upload_received",
    "parse",
    "chunk",
    "metadata_extract",
    "index",
    "publish",
)

# Import log step name → canonical pipeline stage
_STEP_STAGE = {
    "文档解析与图像理解": "parse",
    "元数据抽取": "metadata_extract",
    "向量索引": "index",
}

# Task.stage Chinese hints → how far the pipeline reached (best-effort)
_STAGE_HINTS = (
    ("排队", "upload_received"),
    ("读取", "upload_received"),
    ("等待", "upload_received"),
    ("解析", "parse"),
    ("切块", "chunk"),
    ("元数据", "metadata_extract"),
    ("抽取", "metadata_extract"),
    ("向量", "index"),
    ("索引", "index"),
    ("发布", "publish"),
    ("切换", "publish"),
    ("完成", "publish"),
)


def _visible_log(payload: dict, actor: Actor) -> bool:
    if actor.role == "admin":
        return True
    return payload.get("source") != "chat"


def _safe_tokens(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _status_norm(raw: str | None) -> str:
    if not raw:
        return "unknown"
    if raw in ("success", "succeeded", "ready"):
        return "success"
    if raw in ("failed", "error"):
        return "failed"
    if raw in ("cancelled", "canceled"):
        return "cancelled"
    if raw in ("running", "processing", "indexing"):
        return "running"
    if raw in ("review", "degraded"):
        return raw
    return raw


def _trace_summary(
    *,
    trace_id: str,
    root_type: str,
    root_id: str,
    title: str,
    status: str,
    tokens: int | None,
    duration: float | None,
    time_label: str,
    created_at: str | None,
    attrs: dict | None = None,
) -> dict:
    return {
        "traceId": trace_id,
        "rootType": root_type,
        "rootId": root_id,
        "title": title,
        "status": _status_norm(status),
        "tokens": _safe_tokens(tokens),
        "duration": duration if isinstance(duration, (int, float)) else None,
        "time": time_label or "",
        "createdAt": created_at,
        "attrs": attrs or {},
    }


def _log_as_trace(payload: dict) -> dict:
    source = payload.get("source") or "chat"
    root_type = "import" if source == "import" else source
    tid = payload.get("traceId") or payload.get("id")
    return _trace_summary(
        trace_id=tid,
        root_type=root_type,
        root_id=payload.get("id", tid),
        title=payload.get("question") or "",
        status=payload.get("status") or "unknown",
        tokens=payload.get("tokens"),
        duration=payload.get("duration"),
        time_label=payload.get("time") or "",
        created_at=payload.get("createdAt"),
        attrs={
            "kbName": payload.get("kbName"),
            "model": payload.get("model"),
            "source": source,
            "taskId": payload.get("taskId"),
            "documentId": payload.get("documentId"),
        },
    )


def _run_as_trace(payload: dict) -> dict:
    tid = payload.get("traceId") or payload.get("id") or payload.get("runId")
    return _trace_summary(
        trace_id=tid,
        root_type="application",
        root_id=payload.get("id") or payload.get("runId") or tid,
        title=payload.get("applicationName") or "应用运行",
        status=payload.get("status") or "unknown",
        tokens=payload.get("tokens"),
        duration=payload.get("duration"),
        time_label=(payload.get("createdAt") or "")[:16].replace("T", " "),
        created_at=payload.get("createdAt"),
        attrs={
            "applicationId": payload.get("applicationId"),
            "mode": payload.get("mode"),
            "revision": payload.get("revision"),
            "error": payload.get("error"),
        },
    )


def _task_as_trace(payload: dict, kb_name: str | None = None) -> dict:
    tid = payload.get("traceId") or payload.get("id")
    return _trace_summary(
        trace_id=tid,
        root_type="import",
        root_id=payload.get("id", tid),
        title=f"导入：{payload.get('name') or ''}",
        status=payload.get("status") or "unknown",
        tokens=None,  # tasks do not store tokens; import log may
        duration=None,
        time_label=payload.get("time") or "",
        created_at=payload.get("createdAt"),
        attrs={
            "kbId": payload.get("kbId"),
            "kbName": kb_name,
            "docId": payload.get("docId"),
            "stage": payload.get("stage"),
            "progress": payload.get("progress"),
            "operation": payload.get("operation"),
            "error": payload.get("error"),
        },
    )


def _steps_from_log(payload: dict) -> list[dict]:
    out = []
    for i, step in enumerate(payload.get("steps") or []):
        if not isinstance(step, dict):
            continue
        out.append(
            {
                "spanId": f"{payload.get('id', 'log')}:step:{i}",
                "name": step.get("name") or f"step_{i}",
                "kind": "internal",
                "status": step.get("status") or "unknown",
                "duration": step.get("duration") if isinstance(step.get("duration"), (int, float)) else None,
                "tokens": _safe_tokens(step.get("tokens")),
                "meter": step.get("meter"),
                "model": step.get("model"),
                "error": step.get("error"),
                "attrs": {k: v for k, v in step.items() if k not in {"name", "status", "duration", "tokens", "meter", "model", "error"}},
            }
        )
    return out


def _steps_from_run(payload: dict) -> list[dict]:
    out = []
    for i, step in enumerate(payload.get("steps") or []):
        if not isinstance(step, dict):
            continue
        out.append(
            {
                "spanId": step.get("nodeId") or f"{payload.get('id', 'run')}:step:{i}",
                "name": step.get("label") or step.get("kind") or f"node_{i}",
                "kind": step.get("kind") or "internal",
                "status": step.get("status") or "unknown",
                "duration": step.get("duration") if isinstance(step.get("duration"), (int, float)) else None,
                "tokens": _safe_tokens(step.get("tokens")),
                "meter": step.get("meter"),
                "model": None,
                "error": step.get("error"),
                "attrs": {
                    "nodeId": step.get("nodeId"),
                    "outputPreview": (step.get("output") or "")[:240] if step.get("output") else None,
                },
            }
        )
    return out


def _infer_reached_stage(task: dict) -> str | None:
    stage = str(task.get("stage") or "")
    status = task.get("status")
    if status == "success":
        return "publish"
    if status == "review":
        return "chunk"  # parse/chunk done, waiting publish
    for hint, name in _STAGE_HINTS:
        if hint in stage:
            return name
    if status == "processing":
        return "upload_received"
    if status == "failed":
        return "parse"
    return None


def _build_pipeline_stages(task: dict | None, import_log: dict | None) -> list[dict]:
    """Project upload→…→publish. Unknown fields stay null; never invent duration."""
    by_stage: dict[str, dict] = {
        name: {
            "stage": name,
            "status": "unknown",
            "duration": None,
            "tokens": None,
            "model": None,
            "error": None,
            "attrs": {},
        }
        for name in BUILD_PIPELINE
    }

    if import_log:
        for step in import_log.get("steps") or []:
            if not isinstance(step, dict):
                continue
            stage = _STEP_STAGE.get(step.get("name") or "")
            if not stage:
                continue
            row = by_stage[stage]
            raw_status = step.get("status") or ""
            if raw_status in ("成功", "success"):
                row["status"] = "success"
            elif "失败" in str(raw_status) or raw_status == "failed":
                row["status"] = "failed"
            elif "降级" in str(raw_status):
                row["status"] = "degraded"
            else:
                row["status"] = raw_status or "unknown"
            if isinstance(step.get("duration"), (int, float)):
                row["duration"] = step["duration"]
            row["tokens"] = _safe_tokens(step.get("tokens"))
            row["model"] = step.get("model")
        # Chunk is not a separate timed step today → mark success if parse succeeded
        if by_stage["parse"]["status"] == "success" and by_stage["chunk"]["status"] == "unknown":
            by_stage["chunk"]["status"] = "success"
            by_stage["chunk"]["attrs"] = {"note": "切块合并在解析步骤；无独立耗时"}
        # Publish inferred from task/log outcome
        log_status = import_log.get("status")
        if log_status == "success" and (not task or task.get("status") in ("success", "review")):
            if task and task.get("status") == "review":
                by_stage["publish"]["status"] = "pending"
                by_stage["publish"]["attrs"] = {"note": "解析完成，等待检查后发布"}
            else:
                by_stage["publish"]["status"] = "success"
        elif log_status == "failed":
            # leave publish unknown unless we know it failed there
            pass

    if task:
        by_stage["upload_received"]["status"] = "success"
        by_stage["upload_received"]["attrs"] = {
            "docId": task.get("docId"),
            "operation": task.get("operation"),
            "options": {k: v for k, v in (task.get("options") or {}).items() if k in (
                "parser", "chunkSize", "chunkStrategy", "parentSize", "autoPublish", "extractMetadata", "imageUnderstanding"
            )},
        }
        reached = _infer_reached_stage(task)
        if reached and not import_log:
            order = list(BUILD_PIPELINE)
            idx = order.index(reached)
            for i, name in enumerate(order):
                if i < idx and by_stage[name]["status"] == "unknown":
                    by_stage[name]["status"] = "success"
                elif i == idx:
                    if task.get("status") == "failed":
                        by_stage[name]["status"] = "failed"
                        by_stage[name]["error"] = task.get("error")
                    elif task.get("status") == "processing":
                        by_stage[name]["status"] = "running"
                    elif task.get("status") == "cancelled":
                        by_stage[name]["status"] = "cancelled"
                    elif by_stage[name]["status"] == "unknown":
                        by_stage[name]["status"] = _status_norm(task.get("status"))
        if task.get("status") == "failed" and import_log is None:
            # attach error on inferred stage
            for name in reversed(BUILD_PIPELINE):
                if by_stage[name]["status"] == "failed":
                    by_stage[name]["error"] = task.get("error")
                    break
        if task.get("status") == "success" and by_stage["publish"]["status"] == "unknown":
            by_stage["publish"]["status"] = "success"

    return [by_stage[name] for name in BUILD_PIPELINE]


def _collect_candidates(db, actor: Actor) -> list[dict]:
    """Merge log / application_run / task into a flat trace list (dedupe by traceId)."""
    by_id: dict[str, dict] = {}
    kb_names = {r.id: r.payload.get("name") for r in list_entities(db, "kb")}

    for row in list_entities(db, "log"):
        if not _visible_log(row.payload, actor):
            continue
        t = _log_as_trace(row.payload)
        by_id[t["traceId"]] = t

    for row in list_entities(db, "application_run"):
        if actor.role not in ("admin", "manager") and row.owner != actor.owner:
            continue
        if actor.role == "manager":
            pass  # managers see all runs in MVP (same as apps admin surface)
        t = _run_as_trace(row.payload)
        # Prefer run over nothing; logs of same id unlikely
        existing = by_id.get(t["traceId"])
        if not existing or existing.get("rootType") != "application":
            by_id[t["traceId"]] = t

    for row in list_entities(db, "task"):
        t = _task_as_trace(row.payload, kb_names.get(row.payload.get("kbId")))
        # Prefer import log if already present for same traceId (richer tokens)
        existing = by_id.get(t["traceId"])
        if not existing:
            by_id[t["traceId"]] = t
        elif existing.get("rootType") == "import" and existing.get("tokens") is None and t.get("attrs"):
            # merge task attrs into log-based import trace
            existing["attrs"] = {**t["attrs"], **(existing.get("attrs") or {})}
            existing["status"] = existing["status"] if existing["status"] != "unknown" else t["status"]
            by_id[t["traceId"]] = existing

    items = list(by_id.values())
    items.sort(key=lambda x: x.get("createdAt") or x.get("time") or "", reverse=True)
    return items


def _find_entities(db, trace_id: str) -> dict[str, Any]:
    log = get_entity(db, "log", trace_id, False)
    if log is None:
        for row in list_entities(db, "log"):
            if row.payload.get("traceId") == trace_id or row.payload.get("taskId") == trace_id:
                log = row
                break
    task = get_entity(db, "task", trace_id, False)
    if task is None:
        for row in list_entities(db, "task"):
            if row.payload.get("traceId") == trace_id:
                task = row
                break
    run = get_entity(db, "application_run", trace_id, False)
    if run is None:
        for row in list_entities(db, "application_run"):
            p = row.payload
            if p.get("traceId") == trace_id or p.get("runId") == trace_id:
                run = row
                break
    return {"log": log, "task": task, "run": run}


@router.get("/overview")
def overview(actor: Actor = Depends(require_manager)):
    with db_session() as db:
        traces = _collect_candidates(db, actor)
        failed = sum(1 for t in traces if t["status"] == "failed")
        tokens_known = 0
        tokens_unknown = 0
        for t in traces:
            if isinstance(t.get("tokens"), int):
                tokens_known += t["tokens"]
            else:
                tokens_unknown += 1
        builds_running = sum(
            1
            for r in list_entities(db, "task")
            if r.payload.get("status") == "processing"
        )
        by_type: dict[str, int] = {}
        for t in traces:
            by_type[t["rootType"]] = by_type.get(t["rootType"], 0) + 1
        return {
            "requests": len(traces),
            "failed": failed,
            "tokensKnown": tokens_known,
            "tokensUnknownCount": tokens_unknown,
            "buildsRunning": builds_running,
            "byRootType": by_type,
            "recent": traces[:20],
        }


@router.get("/traces")
def list_traces(
    rootType: str = "",
    status: str = "",
    q: str = "",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    actor: Actor = Depends(require_manager),
):
    with db_session() as db:
        items = _collect_candidates(db, actor)
        if rootType:
            items = [t for t in items if t["rootType"] == rootType]
        if status:
            items = [t for t in items if t["status"] == status]
        if q:
            needle = q.lower()
            items = [
                t
                for t in items
                if needle in (t.get("traceId") or "").lower()
                or needle in (t.get("title") or "").lower()
                or needle in str(t.get("attrs") or {}).lower()
            ]
        return {"items": items[offset : offset + limit], "total": len(items)}


@router.get("/traces/{trace_id}")
def get_trace(trace_id: str, actor: Actor = Depends(require_manager)):
    with db_session() as db:
        found = _find_entities(db, trace_id)
        log_row, task_row, run_row = found["log"], found["task"], found["run"]
        if not log_row and not task_row and not run_row:
            raise HTTPException(404, "追踪不存在")

        if log_row and not _visible_log(log_row.payload, actor):
            raise HTTPException(404, "追踪不存在")

        summary = None
        steps: list[dict] = []
        build_stages: list[dict] = []
        gaps: list[str] = []
        input_text = None
        output_text = None
        error = None
        sources: list = []
        tool_calls: list = []
        skill_calls: list = []
        harness_errors: list = []

        if run_row:
            p = run_row.payload
            summary = _run_as_trace(p)
            steps = _steps_from_run(p)
            input_text = p.get("input")
            output_text = p.get("output")
            error = p.get("error")
            sources = p.get("sources") or []
            gaps.extend(
                [
                    "toolCalls：后端无通用工具运行时",
                    "skillCalls：无 Skill 运行时",
                    "harnessErrors：无 Agent Harness",
                ]
            )

        if log_row:
            p = log_row.payload
            if not summary:
                summary = _log_as_trace(p)
            elif summary["rootType"] == "import":
                # enrich tokens from log
                if summary.get("tokens") is None:
                    summary["tokens"] = _safe_tokens(p.get("tokens"))
                if not summary.get("duration"):
                    summary["duration"] = p.get("duration") if isinstance(p.get("duration"), (int, float)) else None
            if not steps:
                steps = _steps_from_log(p)
            if p.get("source") in ("chat", "retrieval"):
                input_text = input_text or p.get("question")
                output_text = output_text or p.get("answer")
            if p.get("source") == "import" and not task_row:
                # still project pipeline from log alone
                build_stages = _build_pipeline_stages(None, p)

        if task_row:
            kb = get_entity(db, "kb", task_row.payload.get("kbId"), False)
            kb_name = kb.payload.get("name") if kb else None
            if not summary:
                summary = _task_as_trace(task_row.payload, kb_name)
            else:
                summary["attrs"] = {
                    **(summary.get("attrs") or {}),
                    **_task_as_trace(task_row.payload, kb_name)["attrs"],
                }
            import_log = log_row.payload if log_row and log_row.payload.get("source") == "import" else None
            if not import_log:
                for row in list_entities(db, "log"):
                    if row.payload.get("taskId") == task_row.id or row.payload.get("traceId") == (task_row.payload.get("traceId") or task_row.id):
                        if row.payload.get("source") == "import":
                            import_log = row.payload
                            if not steps:
                                steps = _steps_from_log(import_log)
                            break
            build_stages = _build_pipeline_stages(task_row.payload, import_log)
            error = error or task_row.payload.get("error")

        assert summary is not None
        return {
            "trace": summary,
            "steps": steps,
            "buildStages": build_stages,
            "input": input_text,
            "output": output_text,
            "error": error,
            "sources": sources,
            "toolCalls": tool_calls,
            "skillCalls": skill_calls,
            "harnessErrors": harness_errors,
            "gaps": gaps,
        }


class TraceToCaseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Literal["good", "bad"]
    kbId: str | None = Field(default=None, max_length=64)
    query: str | None = Field(default=None, max_length=2000)
    answer: str | None = Field(default=None, max_length=8000)
    expectedDocIds: list[str] = Field(default_factory=list, max_length=50)
    note: str | None = Field(default=None, max_length=500)


@router.post("/traces/{trace_id}/to-case")
def trace_to_case(trace_id: str, body: TraceToCaseBody, actor: Actor = Depends(require_manager)):
    """One-click Good/Bad eval case from an observability trace. Soft-fail: never 5xx for extract gaps."""
    try:
        with db_session() as db:
            found = _find_entities(db, trace_id)
            if not any(found.values()):
                return {"ok": False, "error": "追踪不存在", "case": None}
            log = found.get("log")
            run = found.get("run")
            query = (body.query or "").strip()
            answer = (body.answer or "").strip() or None
            sources = []
            root_type = "unknown"
            if log:
                root_type = log.payload.get("source") or "chat"
                query = query or (log.payload.get("question") or log.payload.get("retrievalQuery") or "")
                answer = answer or (log.payload.get("answer") or None)
                sources = log.payload.get("sources") or []
            elif run:
                root_type = "application"
                query = query or (run.payload.get("input") or "")
                answer = answer or (run.payload.get("output") or None)
                sources = run.payload.get("sources") or []
            if not query:
                return {"ok": False, "error": "无法从追踪提取问题/输入，请手动填写 query", "case": None}
            doc_ids = list(body.expectedDocIds)
            if not doc_ids:
                for s in sources:
                    if isinstance(s, dict) and s.get("docId"):
                        doc_ids.append(s["docId"])
            # de-dupe preserve order
            seen = set()
            expected = []
            for d in doc_ids:
                if d and d not in seen:
                    seen.add(d)
                    expected.append(d)
            case = {
                "id": "case-" + uuid.uuid4().hex,
                "traceId": trace_id,
                "label": body.label,
                "query": query[:2000],
                "answer": (answer[:8000] if isinstance(answer, str) else None),
                "expectedDocIds": expected[:50],
                "kbId": body.kbId,
                "rootType": root_type,
                "note": body.note,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "createdBy": actor.owner,
                # RagWorkbench-compatible importable shape
                "importable": {"query": query[:2000], "expectedDocIds": expected[:50], "answer": answer},
            }
            put_entity(db, "eval-case", case, owner=actor.owner, parent_id=body.kbId or trace_id)
            return {"ok": True, "case": case, "error": None}
    except Exception as exc:
        return {"ok": False, "error": f"生成 Case 失败：{type(exc).__name__}", "case": None}


@router.get("/eval-cases")
def list_eval_cases(
    kbId: str | None = Query(None),
    label: Literal["good", "bad"] | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    actor: Actor = Depends(require_manager),
):
    with db_session() as db:
        rows = list_entities(db, "eval-case")
        items = [r.payload for r in rows]
        if kbId:
            items = [c for c in items if c.get("kbId") == kbId]
        if label:
            items = [c for c in items if c.get("label") == label]
        items.sort(key=lambda c: c.get("createdAt") or "", reverse=True)
        return {"items": items[:limit], "total": len(items)}


@router.get("/billing")
def billing_rollup(actor: Actor = Depends(require_manager)):
    """Aggregate known tokens from logs by source. No fabricated currency."""
    with db_session() as db:
        buckets: dict[str, dict] = {}
        for row in list_entities(db, "log"):
            if not _visible_log(row.payload, actor):
                continue
            source = row.payload.get("source") or "unknown"
            b = buckets.setdefault(
                source,
                {"source": source, "calls": 0, "tokensKnown": 0, "tokensUnknownCount": 0},
            )
            b["calls"] += 1
            tok = row.payload.get("tokens")
            if isinstance(tok, int):
                b["tokensKnown"] += tok
            else:
                b["tokensUnknownCount"] += 1
        # application runs are not in log — add separate bucket from runs
        app_bucket = {"source": "application", "calls": 0, "tokensKnown": 0, "tokensUnknownCount": 0}
        for row in list_entities(db, "application_run"):
            app_bucket["calls"] += 1
            tok = row.payload.get("tokens")
            if isinstance(tok, int):
                app_bucket["tokensKnown"] += tok
            else:
                app_bucket["tokensUnknownCount"] += 1
        items = list(buckets.values())
        if app_bucket["calls"]:
            items.append(app_bucket)
        items.sort(key=lambda x: x["source"])
        return {
            "items": items,
            "pricingConfigured": False,
            "notice": "未配置模型单价，仅展示已知 token；缺失 usage 不计为 0。",
        }
