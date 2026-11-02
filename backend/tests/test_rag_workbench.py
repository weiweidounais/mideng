"""Real SQLite and parsers; no user data or cloud credentials are used."""
from contextlib import contextmanager
import io
import json
import math
import zipfile

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import rag_workbench as w, rag
from app.db import Base, get_entity, put_entity
from app.parsers import parse_file
from app.security import Actor, current_session


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    @contextmanager
    def session():
        with factory() as db:
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
    monkeypatch.setattr(w, 'db_session', session)
    monkeypatch.setattr(rag, 'db_session', session)
    monkeypatch.setattr(w.config, 'data_dir', tmp_path)
    # A pure keyword run must never initialize a cloud embedding provider.
    monkeypatch.setattr(rag.providers, 'get_model', lambda *a: (_ for _ in ()).throw(AssertionError('unexpected model access')))
    rag._lexical_cache.clear()
    original = tmp_path / 'originals/source.md'
    original.parent.mkdir()
    original.write_text('# 差旅\n报销需要发票和审批单。')
    with session() as db:
        put_entity(db, 'kb', {'id': 'kb', 'name': '验收库'})
        put_entity(db, 'kb', {'id': 'other', 'name': '其他库'})
        for id, status in [('doc', 'ready'), ('disabled', 'disabled')]:
            put_entity(db, 'doc', {'id': id, 'kbId': 'kb', 'name': '../../差旅.md', 'status': status, 'version': 1,
                'originalPath': str(original), 'sha256': id, 'chunks': [{'id': id+'-chunk', 'title': '差旅',
                'content': '报销需要发票和审批单。', 'location': '第一章'}]}, parent_id='kb')
    actor = {'role': 'manager'}
    app = FastAPI()
    app.include_router(w.router, prefix='/api')
    app.dependency_overrides[current_session] = lambda: Actor('tester', actor['role'], 'csrf')
    with TestClient(app) as client:
        yield client, session, actor
    engine.dispose()


def test_metrics_penalize_duplicate_chunks_and_misses():
    score = w.metrics([{'docId': 'a'}, {'docId': 'a'}, {'docId': 'b'}], ['a', 'b'], 3)
    assert score['recall'] == 1
    assert score['mrr'] == 1
    assert score['ndcg'] == pytest.approx(1.5 / (1+1/math.log2(3)))
    assert w.metrics([], ['a'], 5) == dict(hit=0, recall=0, mrr=0, ndcg=0)


def test_keyword_evaluation_and_original_nvidia_bundle(env):
    client, _, _ = env
    result = client.post('/api/rag-workbench/knowledge-bases/kb/evaluations', json={
        'cases': [{'query': '报销发票', 'expectedDocIds': ['doc'], 'answer': '发票和审批单'}], 'mode': 'keyword'})
    assert result.status_code == 200, result.text
    report = result.json()
    assert report['summary']['recall'] == 1 and report['completed'] == 1
    assert report['rows'][0]['retrievedDocIds'] == ['doc']
    assert client.get('/api/rag-workbench/knowledge-bases/kb/evaluations').json()[0]['id'] == report['id']
    response = client.get(f"/api/rag-workbench/knowledge-bases/kb/evaluations/{report['id']}/nvidia.zip")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        train = json.loads(archive.read('train.json'))
        assert train[0]['answer'] == '发票和审批单' and train[0]['id'] == 0
        assert archive.read('corpus/'+train[0]['contexts'][0]['filename']).decode().startswith('# 差旅')
    assert client.get(f"/api/rag-workbench/knowledge-bases/other/evaluations/{report['id']}/nvidia.zip").status_code == 404


def test_export_has_safe_paths_and_published_content_only(env):
    client, _, _ = env
    response = client.get('/api/rag-workbench/knowledge-bases/kb/vault.zip')
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        files = [n for n in archive.namelist() if n.startswith('documents/')]
        assert len(files) == 1 and not any('..' in n for n in archive.namelist())
        text = archive.read(files[0]).decode()
        assert 'doc_id: "doc"' in text and 'version=1' in text


def test_role_and_reference_validation(env):
    client, _, actor = env
    response = client.post('/api/rag-workbench/knowledge-bases/kb/evaluations', json={
        'cases': [{'query': '问题', 'expectedDocIds': ['disabled']}]})
    assert response.status_code == 422
    actor['role'] = 'user'
    assert client.get('/api/rag-workbench/capabilities').status_code == 403
    assert client.get('/api/rag-workbench/knowledge-bases/kb/vault.zip').status_code == 403


def test_local_snapshot_cannot_return_disabled_or_changed_docs(env, monkeypatch):
    client, session, _ = env
    async def fake_bridge(path, body=None):
        if path == '/sync':
            return {'indexedDocuments': len(body['documents'])}
        with session() as db:
            row = get_entity(db, 'doc', 'doc')
            row.payload = {**row.payload, 'status': 'disabled'}
        return {'results': [{'source': '/some/old.md', 'content': 'stale'}]}
    monkeypatch.setattr(w, 'bridge', fake_bridge)
    assert client.post('/api/rag-workbench/knowledge-bases/kb/local-search', json={'query': '报销'}).status_code == 409
    assert client.post('/api/rag-workbench/knowledge-bases/kb/local-index').status_code == 200
    assert client.post('/api/rag-workbench/knowledge-bases/kb/local-search', json={'query': '报销'}).status_code == 409


def test_failures_are_not_scored_as_success(env, monkeypatch):
    client, _, _ = env
    def fail(*args):
        raise HTTPException(502, '模型不可用')
    monkeypatch.setattr(w, 'retrieve_sync', fail)
    report = client.post('/api/rag-workbench/knowledge-bases/kb/evaluations', json={
        'cases': [{'query': '问题', 'expectedDocIds': ['doc']}]}).json()
    assert report['status'] == 'incomplete' and report['summary']['recall'] is None
    assert report['completed'] == 0
    assert client.get(f"/api/rag-workbench/knowledge-bases/kb/evaluations/{report['id']}/nvidia.zip").status_code == 422


def test_explicit_draft_testing_does_not_publish_to_business_store(env, monkeypatch):
    import hashlib
    client, session, _ = env
    with session() as db:
        put_entity(db, 'doc', {'id': 'draft', 'kbId': 'kb', 'name': '草稿.md', 'status': 'review',
                              'draftChunks': [{'id': 'draft-c', 'content': '测试草稿', 'location': '第一段'}]}, parent_id='kb')
    async def fake_bridge(path, body=None):
        if path == '/sync':
            assert len(body['documents']) == 2  # ready + explicitly selected review, no disabled
            return {'indexedDocuments': 2}
        return {'results': [{'source': '/local/'+hashlib.sha256(b'draft').hexdigest()+'.md', 'content': '测试草稿'}]}
    monkeypatch.setattr(w, 'bridge', fake_bridge)
    assert client.post('/api/rag-workbench/knowledge-bases/kb/local-index?include_drafts=true').status_code == 200
    report = client.post('/api/rag-workbench/knowledge-bases/kb/evaluations', json={
        'engine': 'local', 'includeDrafts': True, 'cases': [{'query': '草稿', 'expectedDocIds': ['draft']}]}).json()
    assert report['summary']['recall'] == 1 and report['status'] == 'success'
    with session() as db:
        assert get_entity(db, 'doc', 'draft').payload['status'] == 'review'
    assert client.post('/api/rag-workbench/knowledge-bases/kb/local-search', json={'query': '草稿'}).status_code == 409


def test_added_formats_do_not_execute_or_import_notebook_output(tmp_path):
    path = tmp_path / 'test.html'
    path.write_text('<h1>标题</h1><p>正文</p><script>secretScript()</script>')
    parsed = parse_file(path, path.name, 'id', {}, None)
    assert '正文' in parsed.chunks[0]['content'] and 'secretScript' not in parsed.chunks[0]['content']
    path = tmp_path / 'test.ipynb'
    path.write_text(json.dumps({'cells': [{'source': ['print(1)'], 'outputs': ['do not index me']}]}))
    parsed = parse_file(path, path.name, 'id', {}, None)
    assert parsed.chunks[0]['content'] == 'print(1)'
    path = tmp_path / 'slides.pptx'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('ppt/slides/slide1.xml', '<p xmlns:a="urn:a"><a:t>测试幻灯片</a:t></p>')
    parsed = parse_file(path, path.name, 'id', {}, None)
    assert parsed.chunks[0]['page'] == 1 and '测试幻灯片' in parsed.chunks[0]['content']
    assert parsed.warnings
