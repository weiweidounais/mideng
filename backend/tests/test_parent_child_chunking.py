"""Parent/child chunk strategy structure checks (no cloud / no forged tokens)."""
from __future__ import annotations

from pathlib import Path

from app.db import get_entity
from app.parsers import _split, normalize_chunk_options, parse_file


def test_normalize_defaults_keep_recursive():
    opts = normalize_chunk_options({})
    assert opts["chunkStrategy"] == "recursive"
    assert opts["chunkSize"] == 600
    assert opts["parentSize"] == 2000
    assert opts["chunkOverlap"] == min(80, 600 // 8)


def test_parent_child_split_links_children_to_parents():
    paragraphs = [f"第{i}段。" + ("内容" * 40) for i in range(1, 13)]
    text = "\n\n".join(paragraphs)
    chunks = _split(text, "制度", "正文", 120, overlap=20, strategy="parent_child", parent_size=400)
    parents = [c for c in chunks if c.get("role") == "parent"]
    children = [c for c in chunks if c.get("role") == "child"]
    assert parents, "expected parent chunks"
    assert children, "expected child chunks"
    parent_ids = {p["id"] for p in parents}
    assert all(c.get("parentId") in parent_ids for c in children)
    assert all(c.get("parentExcerpt") for c in children)
    assert all(c.get("splitter") == "parent_child" for c in chunks)
    assert sum(1 for c in children if c["parentId"] == parents[0]["id"]) >= 1


def test_recursive_split_has_no_parent_fields():
    chunks = _split("甲。" * 80 + "\n\n" + "乙。" * 80, "t", "loc", 100)
    assert chunks
    assert all(c.get("role") is None for c in chunks)
    assert all(c.get("parentId") is None for c in chunks)


def test_parse_file_parent_child_markdown(tmp_path: Path):
    body = "\n\n".join(f"## 章节{i}\n\n" + ("条款说明。" * 30) for i in range(1, 6))
    path = tmp_path / "policy.md"
    path.write_text(body, encoding="utf-8")
    result = parse_file(path, path.name, "doc-1", {
        "chunkStrategy": "parent_child",
        "chunkSize": 150,
        "parentSize": 500,
        "chunkOverlap": 20,
        "imageUnderstanding": False,
    }, None)
    roles = {c.get("role") for c in result.chunks}
    assert "parent" in roles and "child" in roles
    children = [c for c in result.chunks if c.get("role") == "child"]
    parents = {c["id"]: c for c in result.chunks if c.get("role") == "parent"}
    assert children and all(c["parentId"] in parents for c in children)


def test_source_expands_parent_context():
    from app.rag import _source
    parent = {"id": "p1", "title": "父", "content": "父段完整上下文内容", "location": "父", "kind": "text", "role": "parent"}
    child = {"id": "c1", "title": "子", "content": "子段命中", "location": "子", "kind": "text", "role": "child", "parentId": "p1"}
    doc = {"id": "d1", "name": "制度.md", "version": 1, "chunks": [parent, child]}
    source = _source(doc, child)
    assert source["parentId"] == "p1"
    assert "父段完整上下文内容" in source["parentContext"]
    assert "所属父段" in source["content"]
    assert "子段命中" in source["content"]

