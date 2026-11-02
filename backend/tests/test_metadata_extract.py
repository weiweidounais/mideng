"""Heuristic document metadata extraction (no LLM / no forged usage)."""
from __future__ import annotations

from app.metadata_extract import (
    empty_metadata,
    extract_document_metadata,
    extract_heuristic,
    payload_for_qdrant,
    sanitize_metadata_patch,
)


SAMPLE_MD = """---
date: 2024-03-15
version: V2.1
author: 张三
subject: 行政人事部
---

# 出差住宿报销制度

适用组织：集团总部及分子公司
负责人：李四
生效日期：2024年03月15日
版本：V2.1

## 住宿标准

出差住宿费用标准为每晚500元。

## 审批流程

部门经理审批后提交财务。
"""


def test_extract_heuristic_frontmatter_and_body():
    meta = extract_heuristic("出差报销制度_V2.1.md", SAMPLE_MD)
    assert meta["docDate"] == "2024-03-15"
    assert meta["bizVersion"] in ("V2.1", "v2.1") or "2.1" in (meta["bizVersion"] or "")
    assert meta["ownerPerson"]
    assert meta["subject"]
    assert meta["keywords"]
    assert meta["likelyQuestions"]
    assert meta["extractor"]["mode"] == "rules"
    assert meta["status"] == "ok"
    assert meta["confidence"] is not None and meta["confidence"] > 0


def test_extract_heuristic_from_filename_and_regex():
    text = "修订日期：2023年11月08日\n版本：Rev A\n编制人：王五\n适用对象：产品线 Alpha\n"
    meta = extract_heuristic("产品手册_RevA.md", text)
    assert meta["docDate"] == "2023-11-08"
    assert meta["bizVersion"]
    assert meta["ownerPerson"] and "王五" in meta["ownerPerson"]
    assert meta["subject"]
    assert any("产品" in k or "手册" in k or "alpha" in k.lower() for k in meta["keywords"]) or meta["keywords"]


def test_extract_mode_off_skips():
    meta, warnings, usage = extract_document_metadata("x.md", SAMPLE_MD, mode="off")
    assert meta["status"] == "skipped"
    assert meta["extractor"]["mode"] == "off"
    assert warnings == []
    assert usage == {}


def test_extract_rules_never_calls_llm_without_db():
    meta, warnings, usage = extract_document_metadata("制度.md", SAMPLE_MD, mode="auto", db=None)
    assert meta["extractor"]["mode"] == "rules"
    assert usage == {}
    assert warnings == []


def test_sanitize_metadata_patch_validates_date():
    out = sanitize_metadata_patch({"docDate": "2025-01-02", "keywords": ["a", "b"], "likelyQuestions": ["q1"]})
    assert out["docDate"] == "2025-01-02"
    assert out["keywords"] == ["a", "b"]
    try:
        sanitize_metadata_patch({"docDate": "2025/01/02"})
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_payload_for_qdrant_short_fields():
    payload = payload_for_qdrant({
        "docDate": "2024-03-15",
        "bizVersion": "V2.1",
        "subject": "行政",
        "ownerPerson": "张三",
        "keywords": ["出差", "报销"],
        "likelyQuestions": ["住宿标准？"],
    })
    assert payload["docDate"] == "2024-03-15"
    assert payload["keywords"] == ["出差", "报销"]
    assert "likelyQuestions" not in payload  # long text stays lexical-only


def test_empty_metadata_shape():
    meta = empty_metadata(status="empty", mode="off")
    for key in ("docDate", "bizVersion", "subject", "ownerPerson", "keywords", "likelyQuestions", "extractedAt", "extractor", "confidence", "status"):
        assert key in meta
    assert meta["keywords"] == []
    assert meta["status"] == "empty"
