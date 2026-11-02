"""Document-level metadata extraction for import indexing.

Heuristic (regex / titles / frontmatter / table-like fields) first.
Optional LLM only when a connected LLM is configured; never invent usage.
Failures never block ingest — callers merge warnings.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import jieba

logger = logging.getLogger(__name__)
_SHANGHAI = ZoneInfo("Asia/Shanghai")

# Fixed schema keys (doc.metadata)
META_KEYS = (
    "docDate",
    "bizVersion",
    "subject",
    "ownerPerson",
    "keywords",
    "likelyQuestions",
    "extractedAt",
    "extractor",
    "confidence",
    "status",
)

_DATE_PATTERNS = [
    re.compile(r"(?:生效|修订|发布|印发|施行|更新日期|日期)[:：\s]*([12]\d{3})[年./-](\d{1,2})[月./-](\d{1,2})"),
    re.compile(r"([12]\d{3})[年./-](\d{1,2})[月./-](\d{1,2})日?"),
    re.compile(r"(?:date|updated|effective)[:：\s]*([12]\d{3})[-/](\d{1,2})[-/](\d{1,2})", re.I),
]
_VERSION_PATTERNS = [
    re.compile(r"(?:版本|版次|文号|Version)[:：\s]*([Vv]?\d+(?:\.\d+)*(?:[A-Za-z])?|[Rr]ev\.?\s*[A-Z0-9.]+|[甲乙丙丁戊己庚辛]|[一二三四五六七八九十]+版)"),
    re.compile(r"(?:Rev(?:ision)?)[:：\s]*([A-Z0-9.]+)", re.I),
    re.compile(r"\b([Vv]\d+(?:\.\d+)*)\b"),
    re.compile(r"[（(]([Rr]ev\s*[A-Z0-9.]+)[）)]"),
    re.compile(r"\b([Rr]ev\.?\s*[A-Z0-9.]+)\b"),
]
_OWNER_PATTERNS = [
    re.compile(r"(?:负责人|责任人|编制人|拟稿人|审核人|批准人|作者|Author)[:：\s]*([^\n,，;；|/]{2,40})"),
]
_SUBJECT_PATTERNS = [
    re.compile(r"(?:适用(?:范围|组织|对象)|业务主体|产品|所属(?:公司|部门|项目)|主体)[:：\s]*([^\n]{2,60})"),
]
_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
_FM_LINE = re.compile(r"^([A-Za-z_\u4e00-\u9fff][\w\u4e00-\u9fff]*)\s*[:：]\s*(.+)$", re.M)
_HEADING = re.compile(r"^#{1,3}\s+(.+)$", re.M)
_STOP = {
    "的", "了", "和", "是", "有", "在", "与", "及", "等", "为", "对", "中", "及", "或",
    "文档", "制度", "规定", "办法", "通知", "说明", "内容", "相关", "本", "其", "该",
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _label_now() -> str:
    return datetime.now(_SHANGHAI).strftime("%Y-%m-%d %H:%M")


def empty_metadata(*, status: str = "empty", mode: str = "off") -> dict[str, Any]:
    return {
        "docDate": None,
        "bizVersion": None,
        "subject": None,
        "ownerPerson": None,
        "keywords": [],
        "likelyQuestions": [],
        "extractedAt": _iso_now(),
        "extractor": {"mode": mode},
        "confidence": None,
        "status": status,
    }


def _norm_date(y: str, m: str, d: str) -> str | None:
    try:
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    except ValueError:
        return None


def _parse_frontmatter(text: str) -> dict[str, str]:
    match = _FRONTMATTER.match(text)
    if not match:
        return {}
    out: dict[str, str] = {}
    for key, value in _FM_LINE.findall(match.group(1)):
        out[key.strip().lower()] = value.strip().strip("\"'")
    return out


def _first_match(patterns: list[re.Pattern[str]], text: str) -> str | None:
    for pattern in patterns:
        found = pattern.search(text)
        if found:
            value = found.group(1).strip() if found.lastindex else found.group(0).strip()
            if value:
                return value[:80]
    return None


def _first_date(text: str) -> str | None:
    for pattern in _DATE_PATTERNS:
        found = pattern.search(text)
        if found and found.lastindex and found.lastindex >= 3:
            date = _norm_date(found.group(1), found.group(2), found.group(3))
            if date:
                return date
    return None


def _filename_stem(name: str) -> str:
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", name or "")
    return stem.replace("_", " ").replace("-", " ").strip()


def _keyword_candidates(name: str, text: str, limit: int = 12) -> list[str]:
    bag: list[str] = []
    seen: set[str] = set()

    def add(token: str):
        token = token.strip().lower() if re.search(r"[A-Za-z]", token) else token.strip()
        if not token or len(token) < 2 or token in _STOP or token in seen:
            return
        if not re.search(r"[\w\u4e00-\u9fff]", token):
            return
        seen.add(token)
        bag.append(token)

    for part in re.split(r"[\s_\-./（）()【】\[\]·]+", _filename_stem(name)):
        add(part)
    for heading in _HEADING.findall(text)[:8]:
        for part in jieba.lcut(heading):
            add(part)
    # Prefer early body tokens for short docs
    for part in jieba.lcut(text[:2000]):
        if len(bag) >= limit:
            break
        if len(part) >= 2:
            add(part)
    return bag[:limit]


def _heuristic_questions(name: str, subject: str | None, keywords: list[str], headings: list[str]) -> list[str]:
    questions: list[str] = []
    stem = _filename_stem(name)
    topic = subject or stem or (keywords[0] if keywords else "本文件")
    templates = [
        f"{topic}的适用范围是什么？",
        f"{topic}由谁负责？",
        f"{topic}何时生效或修订？",
        f"{topic}的关键要求有哪些？",
    ]
    for item in templates:
        if item not in questions:
            questions.append(item)
    for heading in headings[:6]:
        q = f"关于「{heading.strip()}」有哪些规定？"
        if q not in questions:
            questions.append(q)
    for word in keywords[:4]:
        q = f"什么是{word}？"
        if q not in questions and len(q) <= 40:
            questions.append(q)
    return questions[:12]


def extract_heuristic(name: str, text: str, *, chunks: list[dict] | None = None) -> dict[str, Any]:
    """Pure heuristic extraction. Never calls external services."""
    body = text or ""
    if not body and chunks:
        body = "\n\n".join(f"{c.get('title', '')}\n{c.get('content', '')}" for c in chunks[:40])
    sample = body[:12000]
    fm = _parse_frontmatter(sample)
    headings = [h.strip() for h in _HEADING.findall(sample) if h.strip()][:12]

    doc_date = None
    for key in ("date", "docdate", "updated", "effective", "生效日期", "修订日期", "发布日期"):
        if key in fm:
            raw = fm[key]
            m = re.search(r"([12]\d{3})[年./-](\d{1,2})[月./-](\d{1,2})", raw)
            if m:
                doc_date = _norm_date(m.group(1), m.group(2), m.group(3))
                break
    if not doc_date:
        doc_date = _first_date(sample)

    biz_version = None
    for key in ("version", "bizversion", "版本", "版次"):
        if key in fm and fm[key]:
            biz_version = fm[key][:40]
            break
    if not biz_version:
        biz_version = _first_match(_VERSION_PATTERNS, sample)
    if not biz_version:
        m = re.search(r"(?:[Vv]\d+(?:\.\d+)+|[Rr]ev\.?\s*[A-Za-z0-9.]+)", name or "")
        if m:
            biz_version = m.group(0).replace(" ", "")

    owner = None
    for key in ("owner", "author", "负责人", "编制人", "责任人"):
        if key in fm and fm[key]:
            owner = fm[key][:40]
            break
    if not owner:
        owner = _first_match(_OWNER_PATTERNS, sample)
        if owner:
            owner = re.split(r"[\s|/｜]", owner)[0].strip()[:40]

    subject = None
    for key in ("subject", "product", "org", "主体", "适用组织", "产品"):
        if key in fm and fm[key]:
            subject = fm[key][:60]
            break
    if not subject:
        subject = _first_match(_SUBJECT_PATTERNS, sample)
    if not subject and headings:
        subject = headings[0][:60]
    if not subject:
        subject = _filename_stem(name)[:60] or None

    keywords = _keyword_candidates(name, sample)
    questions = _heuristic_questions(name, subject, keywords, headings)

    filled = sum(
        1
        for value in (doc_date, biz_version, subject, owner)
        if value
    ) + (1 if keywords else 0) + (1 if questions else 0)
    confidence = round(min(0.85, 0.25 + filled * 0.1), 2)

    return {
        "docDate": doc_date,
        "bizVersion": biz_version,
        "subject": subject,
        "ownerPerson": owner,
        "keywords": keywords,
        "likelyQuestions": questions,
        "extractedAt": _iso_now(),
        "extractor": {"mode": "rules"},
        "confidence": confidence,
        "status": "ok" if (keywords or doc_date or biz_version or owner or subject) else "empty",
    }


def _merge_llm_json(base: dict[str, Any], payload: dict[str, Any], model_id: str) -> dict[str, Any]:
    out = dict(base)
    if isinstance(payload.get("docDate"), str) and re.match(r"^\d{4}-\d{2}-\d{2}$", payload["docDate"]):
        out["docDate"] = payload["docDate"]
    if isinstance(payload.get("bizVersion"), str) and payload["bizVersion"].strip():
        out["bizVersion"] = payload["bizVersion"].strip()[:40]
    if isinstance(payload.get("subject"), str) and payload["subject"].strip():
        out["subject"] = payload["subject"].strip()[:60]
    if isinstance(payload.get("ownerPerson"), str) and payload["ownerPerson"].strip():
        out["ownerPerson"] = payload["ownerPerson"].strip()[:40]
    if isinstance(payload.get("keywords"), list):
        merged = list(out.get("keywords") or [])
        for item in payload["keywords"]:
            if isinstance(item, str) and item.strip() and item.strip() not in merged:
                merged.append(item.strip()[:40])
        out["keywords"] = merged[:20]
    if isinstance(payload.get("likelyQuestions"), list):
        merged = list(out.get("likelyQuestions") or [])
        for item in payload["likelyQuestions"]:
            if isinstance(item, str) and item.strip() and item.strip() not in merged:
                merged.append(item.strip()[:120])
        out["likelyQuestions"] = merged[:15]
    out["extractor"] = {"mode": "llm", "modelConfigId": model_id}
    out["status"] = "ok"
    out["extractedAt"] = _iso_now()
    if isinstance(payload.get("confidence"), (int, float)):
        out["confidence"] = max(0.0, min(1.0, float(payload["confidence"])))
    else:
        out["confidence"] = max(out.get("confidence") or 0.5, 0.6)
    return out


def try_llm_enrich(db, base: dict[str, Any], name: str, text: str, model_config_id: str | None = None) -> tuple[dict[str, Any], list[str], dict]:
    """Optionally enrich with LLM. Returns (meta, warnings, usage). Never forges usage."""
    warnings: list[str] = []
    usage: dict = {}
    from fastapi import HTTPException

    from . import providers

    try:
        model = providers.get_model(db, "LLM", model_config_id)
    except HTTPException:
        warnings.append("未配置可用 LLM，元数据仅使用启发式抽取")
        return base, warnings, usage

    sample = (text or "")[:6000]
    prompt = (
        "从企业文档摘录中抽取 JSON 元数据，字段："
        "docDate(YYYY-MM-DD或null), bizVersion, subject, ownerPerson, "
        "keywords(字符串数组), likelyQuestions(5-10个中文问题), confidence(0-1)。"
        "只输出 JSON，不要编造文中没有依据的事实。\n"
        f"文件名：{name}\n正文：\n{sample}"
    )
    llm = None
    try:
        llm = providers.make_chat(db, model, streaming=False)
        result = llm.invoke(prompt)
        raw = result.content if hasattr(result, "content") else str(result)
        if isinstance(raw, list):
            raw = "".join(str(part) for part in raw)
        raw = str(raw).strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("LLM 未返回对象")
        meta = _merge_llm_json(base, payload, model["id"])
        # Usage only when provider reports it — never invent.
        meta_usage = getattr(result, "usage_metadata", None) or getattr(llm, "last_usage", None)
        if isinstance(meta_usage, dict) and meta_usage:
            usage = {"llmTokens": meta_usage.get("total_tokens") or meta_usage.get("totalTokens")}
            if usage["llmTokens"] is None and (
                meta_usage.get("input_tokens") is not None or meta_usage.get("output_tokens") is not None
            ):
                usage["llmTokens"] = int(meta_usage.get("input_tokens") or 0) + int(meta_usage.get("output_tokens") or 0)
        return meta, warnings, usage
    except Exception as exc:
        logger.warning("LLM metadata enrich failed: %s", type(exc).__name__)
        warnings.append(f"LLM 元数据抽取失败，已保留启发式结果：{type(exc).__name__}")
        failed = dict(base)
        failed["status"] = "partial" if base.get("status") == "ok" else "failed"
        failed["extractor"] = {"mode": "rules", "llmAttempted": True}
        return failed, warnings, usage
    finally:
        if llm is not None:
            try:
                providers.close_chat(llm)
            except Exception:
                pass


def extract_document_metadata(
    name: str,
    text: str = "",
    *,
    chunks: list[dict] | None = None,
    db=None,
    mode: str = "auto",
    model_config_id: str | None = None,
) -> tuple[dict[str, Any], list[str], dict]:
    """Extract metadata.

    mode:
      - off: empty shell
      - rules: heuristic only
      - llm: heuristic + LLM if configured (else rules + warning)
      - auto: same as llm when db provided, else rules
    """
    warnings: list[str] = []
    usage: dict = {}
    if mode == "off":
        return empty_metadata(status="skipped", mode="off"), warnings, usage

    base = extract_heuristic(name, text, chunks=chunks)
    want_llm = mode in ("llm", "auto") and db is not None
    if not want_llm:
        return base, warnings, usage
    return try_llm_enrich(db, base, name, text or _chunks_text(chunks), model_config_id)


def _chunks_text(chunks: list[dict] | None) -> str:
    if not chunks:
        return ""
    return "\n\n".join(f"{c.get('title', '')}\n{c.get('content', '')}" for c in chunks[:40])


def sanitize_metadata_patch(body: dict[str, Any]) -> dict[str, Any]:
    """Validate user PATCH for editable fields."""
    out: dict[str, Any] = {}
    if "docDate" in body:
        value = body["docDate"]
        if value in (None, ""):
            out["docDate"] = None
        elif isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", value):
            out["docDate"] = value
        else:
            raise ValueError("docDate 须为 YYYY-MM-DD 或空")
    if "bizVersion" in body:
        value = body["bizVersion"]
        out["bizVersion"] = None if value in (None, "") else str(value)[:40]
    if "subject" in body:
        value = body["subject"]
        out["subject"] = None if value in (None, "") else str(value)[:60]
    if "ownerPerson" in body:
        value = body["ownerPerson"]
        out["ownerPerson"] = None if value in (None, "") else str(value)[:40]
    if "keywords" in body:
        if not isinstance(body["keywords"], list):
            raise ValueError("keywords 须为数组")
        out["keywords"] = [str(x).strip()[:40] for x in body["keywords"] if str(x).strip()][:20]
    if "likelyQuestions" in body:
        if not isinstance(body["likelyQuestions"], list):
            raise ValueError("likelyQuestions 须为数组")
        out["likelyQuestions"] = [str(x).strip()[:120] for x in body["likelyQuestions"] if str(x).strip()][:15]
    return out


def enhance_chunks_with_keywords(
    chunks: list[dict],
    doc_name: str = "",
    *,
    force: bool = False,
    skip_edited: bool = True,
) -> list[str]:
    """Rule-based keywords (+ light subject / likelyQuestions) into each chunk.metadata.

    Failures never block ingest. By default skips chunks that already have keywords,
    and skips chunks marked metadata.edited when skip_edited=True.
    force=True rewrites auto fields on non-edited chunks.
    """
    warnings: list[str] = []
    if not chunks:
        return warnings
    for index, chunk in enumerate(chunks):
        try:
            if not isinstance(chunk, dict):
                continue
            existing = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
            if skip_edited and existing.get("edited"):
                continue
            prior = existing.get("keywords") if isinstance(existing.get("keywords"), list) else []
            has_kw = any(str(x).strip() for x in prior)
            title = str(chunk.get("title") or "")
            content = str(chunk.get("content") or "")
            meta = dict(existing)
            if force or not has_kw:
                bag = _keyword_candidates(doc_name or title, f"{title}\n{content}", limit=8)
                meta["keywords"] = bag
            if force or not str(meta.get("subject") or "").strip():
                meta["subject"] = (title.strip()[:60] or None)
            if force or not (isinstance(meta.get("likelyQuestions"), list) and any(str(x).strip() for x in meta.get("likelyQuestions") or [])):
                topic = meta.get("subject") or title or "本片段"
                meta["likelyQuestions"] = [
                    f"关于「{topic}」有哪些规定？",
                    f"{topic}的关键要求是什么？",
                ][:4]
            if not meta.get("edited"):
                meta["extractor"] = "rules"
                meta["source"] = "auto"
            chunk["metadata"] = meta
        except Exception as exc:
            warnings.append(f"分块关键词增强跳过第 {index + 1} 段：{type(exc).__name__}")
            logger.warning("chunk keyword enhance failed at %s: %s", index, type(exc).__name__)
    return warnings


def merge_document_metadata(
    base: dict[str, Any] | None,
    draft: dict[str, Any] | None,
    *,
    fill_missing_only: bool = False,
    mark_edited: bool = False,
) -> dict[str, Any]:
    """Merge draft doc-level metadata into base. Reuses fixed schema keys only."""
    out = dict(base or empty_metadata(status="empty", mode="manual"))
    if not draft:
        if mark_edited:
            extractor = dict(out.get("extractor") or {})
            extractor["edited"] = True
            extractor.setdefault("mode", extractor.get("mode") or "manual")
            out["extractor"] = extractor
            if out.get("keywords") or out.get("docDate") or out.get("bizVersion") or out.get("subject") or out.get("ownerPerson") or out.get("likelyQuestions"):
                out["status"] = "ok"
        return out
    try:
        patch = sanitize_metadata_patch({k: v for k, v in draft.items() if k in (
            "docDate", "bizVersion", "subject", "ownerPerson", "keywords", "likelyQuestions"
        )})
    except ValueError:
        patch = {}
        for key in ("docDate", "bizVersion", "subject", "ownerPerson"):
            if key in draft and draft[key] not in (None, ""):
                if not fill_missing_only or not out.get(key):
                    out[key] = str(draft[key])[:80]
        for key in ("keywords", "likelyQuestions"):
            if isinstance(draft.get(key), list) and (not fill_missing_only or not out.get(key)):
                out[key] = [str(x).strip()[:120] for x in draft[key] if str(x).strip()][:20]
        patch = {}
    for key, value in patch.items():
        if fill_missing_only:
            cur = out.get(key)
            empty = cur in (None, "", []) or (isinstance(cur, list) and not any(str(x).strip() for x in cur))
            if not empty:
                continue
        out[key] = value
    out["extractedAt"] = _iso_now()
    extractor = dict(out.get("extractor") or {})
    if mark_edited:
        extractor["edited"] = True
        extractor.setdefault("mode", extractor.get("mode") or "manual")
    out["extractor"] = extractor
    if out.get("keywords") or out.get("docDate") or out.get("bizVersion") or out.get("subject") or out.get("ownerPerson") or out.get("likelyQuestions"):
        out["status"] = "ok"
    return out


def apply_chunk_metadata_drafts(chunks: list[dict], drafts: list[dict] | None) -> list[str]:
    """Apply import-time chunk metadata drafts by id or index. Manual fields win."""
    warnings: list[str] = []
    if not chunks or not drafts:
        return warnings
    by_id = {}
    by_index = {}
    for item in drafts:
        if not isinstance(item, dict):
            continue
        meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else None
        if meta is None:
            # allow flat draft shape {id, keywords, subject, ...}
            meta = {k: item[k] for k in ("keywords", "subject", "likelyQuestions", "tags") if k in item}
        if not meta:
            continue
        if item.get("id") is not None:
            by_id[str(item["id"])] = meta
        if item.get("index") is not None:
            try:
                by_index[int(item["index"])] = meta
            except (TypeError, ValueError):
                pass
    for index, chunk in enumerate(chunks):
        if not isinstance(chunk, dict):
            continue
        meta_draft = by_id.get(str(chunk.get("id"))) if chunk.get("id") is not None else None
        if meta_draft is None:
            meta_draft = by_index.get(index)
        if not meta_draft:
            continue
        try:
            existing = dict(chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {})
            if "keywords" in meta_draft and isinstance(meta_draft["keywords"], list):
                existing["keywords"] = [str(x).strip()[:40] for x in meta_draft["keywords"] if str(x).strip()][:20]
            elif "tags" in meta_draft and isinstance(meta_draft["tags"], list):
                existing["keywords"] = [str(x).strip()[:40] for x in meta_draft["tags"] if str(x).strip()][:20]
            if "subject" in meta_draft:
                value = meta_draft["subject"]
                existing["subject"] = None if value in (None, "") else str(value)[:60]
            if "likelyQuestions" in meta_draft and isinstance(meta_draft["likelyQuestions"], list):
                existing["likelyQuestions"] = [str(x).strip()[:120] for x in meta_draft["likelyQuestions"] if str(x).strip()][:15]
            existing["edited"] = True
            extractor = existing.get("extractor")
            if isinstance(extractor, dict):
                existing["extractor"] = {**extractor, "edited": True}
            else:
                existing["extractor"] = {"mode": "manual", "edited": True}
            existing["source"] = "manual"
            chunk["metadata"] = existing
        except Exception as exc:
            warnings.append(f"片段元数据草稿合并跳过第 {index + 1} 段：{type(exc).__name__}")
    return warnings


def payload_for_qdrant(meta: dict[str, Any] | None) -> dict[str, Any]:
    """Short fields for Qdrant point payload (filter / display)."""
    if not meta:
        return {}
    out: dict[str, Any] = {}
    for key in ("docDate", "bizVersion", "subject", "ownerPerson"):
        value = meta.get(key)
        if value:
            out[key] = str(value)[:80]
    keywords = meta.get("keywords") or []
    if isinstance(keywords, list) and keywords:
        out["keywords"] = [str(k)[:40] for k in keywords[:20] if k]
    return out
