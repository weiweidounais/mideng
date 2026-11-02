"""Semantic LLM chunk strategy: degrade without LLM; mock LLM yields valid chunks."""
from __future__ import annotations

from pathlib import Path

from app.parsers import (
    _split,
    _split_semantic,
    normalize_chunk_options,
    parse_file,
)


def test_normalize_accepts_semantic_aliases():
    for alias in ("semantic", "llm_semantic", "semantic_llm"):
        opts = normalize_chunk_options({"chunkStrategy": alias, "chunkSize": 400})
        assert opts["chunkStrategy"] == "semantic"
        assert opts["chunkSize"] == 400
        assert opts["maxSemanticCallsPerDoc"] == 40


def test_normalize_default_still_recursive():
    assert normalize_chunk_options({})["chunkStrategy"] == "recursive"


def test_semantic_without_llm_falls_back_to_recursive():
    paragraphs = [f"主题{i}。" + ("说明文字" * 30) for i in range(1, 8)]
    text = "\n\n".join(paragraphs)
    state = {"calls": 0, "max_calls": 40, "warnings": [], "usage": {}}
    chunks = _split(
        text, "规章", "正文", 200, overlap=20, strategy="semantic",
        semantic_invoke=None, semantic_state=state,
    )
    assert chunks
    assert all(c.get("splitter") == "recursive" for c in chunks)
    assert any(c.get("semanticFallback") for c in chunks)
    assert state["warnings"]
    assert "降级" in state["warnings"][0] or "LLM" in state["warnings"][0]
    assert state.get("usage") in ({}, None) or state["usage"] == {}


def test_semantic_with_mock_llm_produces_legal_chunks():
    text = (
        "第一章 总则\n\n本制度适用于全体员工的差旅报销。\n\n"
        "第二章 住宿标准\n\n一线城市每晚不超过八百元，其他城市不超过六百元。\n\n"
        "第三章 审批流程\n\n部门经理审批后提交财务，超标需分管领导加签。"
    )

    def fake_invoke(prompt: str):
        payload = (
            '{"paragraphs":['
            '{"text":"第一章 总则\\n\\n本制度适用于全体员工的差旅报销。","reason":"总则"},'
            '{"text":"第二章 住宿标准\\n\\n一线城市每晚不超过八百元，其他城市不超过六百元。","reason":"住宿"},'
            '{"text":"第三章 审批流程\\n\\n部门经理审批后提交财务，超标需分管领导加签。","reason":"审批"}'
            "]}"
        )
        # Provider-reported usage only — simulate known total.
        return payload, {"llmTokens": 42}

    state = {"calls": 0, "max_calls": 40, "warnings": [], "usage": {}}
    chunks = _split_semantic(
        text, "差旅", "正文", 80, 10,
        semantic_invoke=fake_invoke, semantic_state=state,
    )
    assert len(chunks) == 3
    assert all(c.get("splitter") == "semantic" for c in chunks)
    assert all(c.get("content") for c in chunks)
    assert chunks[0].get("semanticBoundary") == "总则"
    assert state["calls"] == 1
    assert state["usage"].get("llmTokens") == 42
    assert not state["warnings"]


def test_semantic_mock_invalid_json_falls_back():
    def bad_invoke(prompt: str):
        return "not-json", {}

    state = {"calls": 0, "max_calls": 40, "warnings": [], "usage": {}}
    chunks = _split("甲。" * 100 + "\n\n" + "乙。" * 100, "t", "loc", 120, strategy="semantic",
                    semantic_invoke=bad_invoke, semantic_state=state)
    assert chunks
    assert any(c.get("semanticFallback") for c in chunks)
    assert any("降级" in w for w in state["warnings"])


def test_semantic_usage_unknown_when_provider_silent():
    def silent_invoke(prompt: str):
        return '{"paragraphs":[{"text":"完整的一段语义内容，足够长所以会触发调用。' + ("字" * 80) + '","reason":"一段"}]}', {}

    state = {"calls": 0, "max_calls": 40, "warnings": [], "usage": {}}
    chunks = _split_semantic(
        "完整的一段语义内容，足够长所以会触发调用。" + ("字" * 80),
        "t", "loc", 80, 10,
        semantic_invoke=silent_invoke, semantic_state=state,
    )
    assert chunks
    assert state["calls"] == 1  # size=80 forces LLM path
    # No forged tokens when provider omitted usage.
    assert state["usage"] == {} or state["usage"].get("llmTokens") is None


def test_parse_file_semantic_without_db_degrades(tmp_path: Path):
    body = "\n\n".join(f"## 节{i}\n\n" + ("条款。" * 40) for i in range(1, 5))
    path = tmp_path / "policy.md"
    path.write_text(body, encoding="utf-8")
    result = parse_file(path, path.name, "doc-sem-1", {
        "chunkStrategy": "semantic",
        "chunkSize": 200,
        "chunkOverlap": 20,
        "imageUnderstanding": False,
    }, None)
    assert result.chunks
    assert result.warnings
    assert any("降级" in w or "LLM" in w for w in result.warnings)
