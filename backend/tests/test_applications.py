"""Application graphs execute real SQL/LangChain; external model HTTP is controlled."""
import copy
import json
from contextlib import contextmanager

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import applications as apps, providers, rag, security
from app.config import config
from app.db import Base, Credential, get_entity, list_entities, put_entity
from app.security import Actor, current_session


@pytest.fixture
def env(monkeypatch, tmp_path):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine); factory = sessionmaker(engine, expire_on_commit=False)
    @contextmanager
    def session():
        with factory() as db:
            try: yield db; db.commit()
            except BaseException: db.rollback(); raise
    monkeypatch.setattr(apps, 'db_session', session)
    monkeypatch.setattr(providers, 'db_session', session)
    monkeypatch.setattr(config, 'data_dir', tmp_path)
    monkeypatch.setattr(config, 'secret_key', '')
    monkeypatch.setattr(config, 'allow_private_providers', True)
    actor = {'value': Actor('owner-a', 'admin', 'csrf')}
    app = FastAPI(); app.include_router(apps.router, prefix='/api')
    app.dependency_overrides[current_session] = lambda: actor['value']
    with session() as db: put_entity(db, 'setting', {'id': 'system', 'chatConcurrency': 10})
    with TestClient(app) as client: yield client, session, actor
    engine.dispose()


def node(id, kind, config=None):
    return {'id': id, 'kind': kind, 'label': id, 'position': {'x': 0, 'y': 0}, 'config': config or {}}


def edge(a, b, handle=None):
    return {'id': a+'-'+b+('-'+handle if handle else ''), 'source': a, 'target': b, **({'sourceHandle': handle} if handle else {})}


def simple(text='收到：{{input}}'):
    return {'name': '真实模板应用', 'description': '本地规则流程', 'nodes': [node('start', 'start'), node('text', 'template', {'template': text}), node('out', 'output', {'template': '{{previous.output}}'})], 'edges': [edge('start', 'text'), edge('text', 'out')]}


def branch():
    return {'name': '规则分流', 'nodes': [node('start', 'start'), node('gate', 'condition', {'source': '{{input}}', 'operator': 'contains', 'value': '报销'}), node('yes', 'template', {'template': '请提供有效发票'}), node('no', 'template', {'template': '请联系服务台'}), node('out', 'output', {'template': '{{previous.output}}'})], 'edges': [edge('start', 'gate'), edge('gate', 'yes', 'true'), edge('gate', 'no', 'false'), edge('yes', 'out'), edge('no', 'out')]}


def create(client, body=None):
    response = client.post('/api/applications', json=body or simple())
    assert response.status_code == 201, response.text
    return response.json()


def test_crud_draft_publish_and_published_snapshot_are_distinct(env):
    client, session, actor = env
    app = create(client)
    assert app['revision'] == 1 and app['status'] == 'draft'
    assert client.get('/api/applications').json()[0]['id'] == app['id']
    assert client.post(f"/api/applications/{app['id']}/validate").json() == {'valid': True, 'errors': []}
    published = client.post(f"/api/applications/{app['id']}/publish").json()
    assert published['publishedRevision'] == 1 and not published['hasUnpublishedChanges']
    changed = simple('新版：{{input}}'); changed['expectedRevision'] = 1
    saved = client.patch(f"/api/applications/{app['id']}", json=changed).json()
    assert saved['revision'] == 2 and saved['hasUnpublishedChanges']
    assert client.patch(f"/api/applications/{app['id']}", json=changed).status_code == 409
    for mode, expected in [('draft', '新版：问题'), ('published', '收到：问题')]:
        run = client.post(f"/api/applications/{app['id']}/run", json={'input': '问题', 'mode': mode})
        assert run.status_code == 200, run.text
        assert run.json()['output'] == expected and run.json()['status'] == 'success'
        assert run.json()['tokens'] is None
    assert len(client.get(f"/api/applications/{app['id']}/runs").json()) == 2
    assert client.post(f"/api/applications/{app['id']}/unpublish").json()['status'] == 'draft'
    assert client.post(f"/api/applications/{app['id']}/run", json={'input': '问题'}).status_code == 409
    assert client.delete(f"/api/applications/{app['id']}").status_code == 204
    with session() as db: assert not list_entities(db, 'application_run')


def test_user_only_runs_published_and_runs_are_owner_scoped(env):
    client, _, actor = env
    app = create(client)
    actor['value'] = Actor('reader-a', 'user', 'csrf')
    assert client.get('/api/applications').json() == []
    assert client.get(f"/api/applications/{app['id']}").status_code == 404
    assert client.post('/api/applications', json=simple()).status_code == 403
    actor['value'] = Actor('owner-a', 'manager', 'csrf')
    assert client.post(f"/api/applications/{app['id']}/publish").status_code == 200
    actor['value'] = Actor('reader-a', 'user', 'csrf')
    metadata = client.get('/api/applications').json()[0]
    assert 'nodes' not in metadata
    assert 'nodes' not in client.get(f"/api/applications/{app['id']}").json()
    assert client.post(f"/api/applications/{app['id']}/run", json={'input': '问题', 'mode': 'draft'}).status_code == 403
    assert client.post(f"/api/applications/{app['id']}/publish").status_code == 403
    assert client.post(f"/api/applications/{app['id']}/run", json={'input': '读者一问题'}).status_code == 200
    actor['value'] = Actor('reader-b', 'user', 'csrf')
    assert client.get(f"/api/applications/{app['id']}/runs").json() == []
    assert client.post(f"/api/applications/{app['id']}/run", json={'input': '读者二问题'}).status_code == 200
    assert len(client.get(f"/api/applications/{app['id']}/runs").json()) == 1
    actor['value'] = Actor('owner-a', 'manager', 'csrf')
    assert client.get(f"/api/applications/{app['id']}/runs").json() == []
    actor['value'] = Actor('admin-other', 'admin', 'csrf')
    assert len(client.get(f"/api/applications/{app['id']}/runs").json()) == 2


@pytest.mark.parametrize('question,expected,skipped', [('申请报销', '请提供有效发票', 'no'), ('查会议室', '请联系服务台', 'yes')])
def test_condition_routes_one_branch_and_merges_active_upstream(env, question, expected, skipped):
    client, _, _ = env
    app = create(client, branch())
    result = client.post(f"/api/applications/{app['id']}/run", json={'input': question, 'mode': 'draft'}).json()
    assert result['status'] == 'success' and result['output'] == expected
    assert next(s for s in result['steps'] if s['nodeId'] == skipped)['status'] == 'skipped'
    assert result['tokens'] is None
    assert not rag._active_chats


@pytest.mark.parametrize('mutation,message', [
    (lambda d: d['edges'].append(edge('out', 'start')), '环路'),
    (lambda d: d['nodes'].append(node('isolated', 'template', {'template': '断开'})), '上游'),
    (lambda d: d['nodes'].append(copy.deepcopy(d['nodes'][0])), 'ID 不能重复'),
    (lambda d: d['nodes'][1]['config'].update(template='{{missing.output}}'), '不是可用'),
    (lambda d: d['edges'].append(edge('gone', 'out')), '不存在'),
    (lambda d: d['nodes'][1]['config'].update(template='{{input}'), '括号'),
])
def test_invalid_graph_can_save_but_not_publish_or_run(env, mutation, message):
    client, _, _ = env
    definition = simple(); mutation(definition)
    app = create(client, definition)
    validation = client.post(f"/api/applications/{app['id']}/validate").json()
    assert not validation['valid'] and message in str(validation['errors'])
    assert client.post(f"/api/applications/{app['id']}/publish").status_code == 422
    assert client.post(f"/api/applications/{app['id']}/run", json={'input': '问题', 'mode': 'draft'}).status_code == 422


def test_condition_requires_explicit_true_and_false_and_no_hidden_branch_execution(env):
    client, _, _ = env
    definition = branch(); definition['edges'][1].pop('sourceHandle')
    app = create(client, definition)
    validation = client.post(f"/api/applications/{app['id']}/validate").json()
    assert not validation['valid'] and 'true 与 false' in str(validation['errors'])


def test_node_cannot_store_keys_or_execute_script(env):
    client, _, _ = env
    definition = simple(); definition['nodes'][1]['config']['api_key'] = 'sensitive'
    assert client.post('/api/applications', json=definition).status_code == 422
    definition = simple(); definition['nodes'][1]['kind'] = 'code'
    assert client.post('/api/applications', json=definition).status_code == 422


def test_concurrency_is_shared_with_chat_and_recovery_marks_interrupted_runs(env):
    client, session, _ = env
    app = create(client)
    with session() as db:
        row = get_entity(db, 'setting', 'system'); row.payload = {**row.payload, 'chatConcurrency': 1}
        put_entity(db, 'application_run', {'id': 'interrupted', 'applicationId': app['id'], 'status': 'running'}, owner='owner-a', parent_id=app['id'])
    with rag._chat_lock: rag._active_chats['existing-chat'] = None
    try: assert client.post(f"/api/applications/{app['id']}/run", json={'input': '问题', 'mode': 'draft'}).status_code == 429
    finally:
        with rag._chat_lock: rag._active_chats.pop('existing-chat')
    apps.recover_application_runs()
    with session() as db: assert get_entity(db, 'application_run', 'interrupted').payload['status'] == 'failed'


def add_llm(session):
    with session() as db:
        put_entity(db, 'connection', {'id': 'cloud', 'provider': 'AIHubMix', 'baseUrl': 'https://workflow-contract.example/v1', 'enabled': True, 'status': 'connected', 'keyConfigured': True})
        put_entity(db, 'model', {'id': 'chat-config', 'provider': 'AIHubMix', 'type': 'LLM', 'modelId': 'contract-model', 'connectionId': 'cloud', 'enabled': True, 'status': 'connected', 'context': 4096})
        db.add(Credential(id='cloud', encrypted=security.encrypt_secret({'apiKey': 'workflow-contract-key-not-real'})))


def llm_definition():
    return {'name': '真实模型链路', 'nodes': [node('start', 'start'), node('generate', 'llm', {'modelConfigId': 'chat-config', 'prompt': '请改写：{{input}}'}), node('out', 'output', {'template': '{{previous.output}}'})], 'edges': [edge('start', 'generate'), edge('generate', 'out')]}


def test_actual_langchain_http_contract_and_vendor_usage_persist(env):
    client, session, _ = env; add_llm(session)
    app = create(client, llm_definition())
    def response(request):
        payload = json.loads(request.content)
        assert payload['model'] == 'contract-model' and payload['stream'] is False
        assert '请改写：你好' in payload['messages'][-1]['content']
        assert payload['max_tokens'] <= 1024
        assert request.headers['authorization'] == 'Bearer workflow-contract-key-not-real'
        return httpx.Response(200, json={'id': 'contract', 'object': 'chat.completion', 'created': 1, 'model': 'contract-model', 'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': '您好，欢迎使用。'}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 15, 'completion_tokens': 6, 'total_tokens': 21}})
    with respx.mock(assert_all_called=True) as cloud:
        cloud.post('https://workflow-contract.example/v1/chat/completions').mock(side_effect=response)
        result = client.post(f"/api/applications/{app['id']}/run", json={'input': '你好', 'mode': 'draft'})
    assert result.status_code == 200, result.text
    assert result.json()['output'] == '您好，欢迎使用。' and result.json()['tokens'] == 21
    assert result.json()['steps'][1]['tokens'] == 21
    assert 'workflow-contract-key-not-real' not in result.text
    with session() as db: assert get_entity(db, 'application_run', result.json()['runId']).payload['tokens'] == 21


def test_unavailable_model_fails_validation_and_cloud_exception_is_sanitized(env):
    client, session, _ = env
    app = create(client, llm_definition())
    assert not client.post(f"/api/applications/{app['id']}/validate").json()['valid']
    add_llm(session)
    with respx.mock(assert_all_called=True) as cloud:
        cloud.post('https://workflow-contract.example/v1/chat/completions').mock(return_value=httpx.Response(401, json={'error': {'message': 'workflow-contract-key-not-real rejected'}}))
        result = client.post(f"/api/applications/{app['id']}/run", json={'input': '问题', 'mode': 'draft'})
    assert result.json()['status'] == 'failed'
    assert result.json()['steps'][1]['status'] == 'failed' and result.json()['steps'][2]['status'] == 'skipped'
    assert 'workflow-contract-key-not-real' not in result.text
    assert result.json()['tokens'] is None and not rag._active_chats


def test_knowledge_node_passes_real_options_and_scopes_context_to_ancestors(env, monkeypatch):
    client, session, _ = env
    with session() as db: put_entity(db, 'kb', {'id': 'knowledge', 'name': '企业制度', 'embeddingConfigId': 'vector'})
    called = []
    def retrieve(ids, query, options):
        called.append((ids, query, options.topK))
        return {'sources': [{'docId': 'doc', 'title': '制度.md', 'location': '第1页', 'content': '报销须发票', 'kind': 'text'}], 'steps': [{'name': '检索', 'tokens': 5, 'status': '成功'}]}
    monkeypatch.setattr(rag, 'retrieve_sync', retrieve)
    definition = {'name': '引用检索', 'nodes': [node('start', 'start'), node('search', 'knowledge', {'kbIds': ['knowledge'], 'query': '{{input}}', 'topK': 3}), node('out', 'output', {'template': '{{context}}'})], 'edges': [edge('start', 'search'), edge('search', 'out')]}
    app = create(client, definition)
    result = client.post(f"/api/applications/{app['id']}/run", json={'input': '报销要求', 'mode': 'draft'}).json()
    assert called == [(['knowledge'], '报销要求', 3)]
    assert result['status'] == 'success' and '报销须发票' in result['output']
    assert result['sources'][0]['docId'] == 'doc' and result['tokens'] == 5


@pytest.mark.parametrize('cfg,message', [({'query': []}, '模板必须'), ({'topK': 21}, '1 到 20'), ({'rerank': 'false'}, '布尔值'), ({'minScore': 'bad'}, '最低分数'), ({'apiEndpoint': 'https://example.com'}, '配置字段')])
def test_knowledge_configuration_types_and_fields_are_validated(env, cfg, message):
    client, session, _ = env
    with session() as db: put_entity(db, 'kb', {'id': 'kb', 'embeddingConfigId': 'e'})
    definition = {'name': '配置验证', 'nodes': [node('start', 'start'), node('search', 'knowledge', {'kbIds': ['kb'], **cfg}), node('out', 'output', {'template': '{{previous.output}}'})], 'edges': [edge('start', 'search'), edge('search', 'out')]}
    app = create(client, definition)
    result = client.post(f"/api/applications/{app['id']}/validate").json()
    assert not result['valid'] and message in str(result['errors'])


def test_sources_drop_internal_paths_and_empty_local_retrieval_does_not_fake_usage(env, monkeypatch):
    client, session, _ = env
    with session() as db: put_entity(db, 'kb', {'id': 'kb', 'embeddingConfigId': 'e'})
    definition = {'name': '来源安全', 'nodes': [node('start', 'start'), node('search', 'knowledge', {'kbIds': ['kb']}), node('out', 'output', {'template': '{{previous.output}}'})], 'edges': [edge('start', 'search'), edge('search', 'out')]}
    app = create(client, definition)
    monkeypatch.setattr(rag, 'retrieve_sync', lambda *_: {'sources': [{'docId': 'doc', 'title': '制度.md', 'content': '资料', 'kind': 'text', 'originalPath': '/private/file', 'storagePath': '/private/storage', 'assetUrl': 'https://private.example/token-secret'}], 'steps': [{'name': '知识库检索', 'model': '无已发布文档', 'duration': 0, 'status': '无结果', 'tokens': None}]})
    response = client.post(f"/api/applications/{app['id']}/run", json={'input': '问题', 'mode': 'draft'})
    assert response.json()['status'] == 'success' and response.json()['tokens'] is None
    assert response.json()['steps'][1]['meter'] == 'local'
    assert all(value not in response.text for value in ('/private/', 'token-secret', 'originalPath', 'storagePath'))


def test_nonfinite_configuration_and_invalid_model_id_type_are_rejected_cleanly(env):
    client, _, _ = env
    definition = llm_definition(); definition['nodes'][1]['config']['temperature'] = float('nan')
    response = client.post('/api/applications', content=json.dumps(definition), headers={'content-type': 'application/json'})
    assert response.status_code == 422
    definition = llm_definition(); definition['nodes'][1]['config']['modelConfigId'] = {'id': 'invalid'}
    app = create(client, definition)
    response = client.post(f"/api/applications/{app['id']}/validate")
    assert response.status_code == 200 and not response.json()['valid']


def test_model_context_budget_rejects_before_paid_model_call(env, monkeypatch):
    client, session, _ = env; add_llm(session)
    app = create(client, llm_definition())
    monkeypatch.setattr(providers, 'make_chat', lambda *_args, **_kwargs: pytest.fail('Oversized prompt must not call cloud model'))
    result = client.post(f"/api/applications/{app['id']}/run", json={'input': '很长的输入内容'*500, 'mode': 'draft'}).json()
    assert result['status'] == 'failed' and '上下文预算' in result['error']
    assert result['tokens'] is None and result['steps'][-1]['status'] == 'skipped'
    assert not rag._active_chats


def test_execution_deadline_is_persisted_and_releases_shared_slot(env, monkeypatch):
    client, session, _ = env
    app = create(client)
    monkeypatch.setattr(apps, 'MAX_SECONDS', 0)
    response = client.post(f"/api/applications/{app['id']}/run", json={'input': '问题', 'mode': 'draft'})
    result = response.json()
    assert result['status'] == 'failed' and '执行超时' in result['error']
    assert result['steps'][0]['status'] == 'failed' and all(s['status'] == 'skipped' for s in result['steps'][1:])
    with session() as db: assert get_entity(db, 'application_run', result['runId']).payload['status'] == 'failed'
    assert not rag._active_chats


def test_require_evidence_returns_local_answer_without_paid_model_call(env, monkeypatch):
    client, session, _ = env; add_llm(session)
    with session() as db: put_entity(db, 'kb', {'id': 'kb', 'embeddingConfigId': 'e'})
    definition = {'name': '无证据保护', 'nodes': [node('start', 'start'), node('search', 'knowledge', {'kbIds': ['kb']}), node('generate', 'llm', {'modelConfigId': 'chat-config', 'prompt': '{{context}}\n{{input}}', 'requireEvidence': True}), node('out', 'output', {'template': '{{previous.output}}'})], 'edges': [edge('start', 'search'), edge('search', 'generate'), edge('generate', 'out')]}
    app = create(client, definition)
    monkeypatch.setattr(rag, 'retrieve_sync', lambda *_: {'sources': [], 'steps': [{'name': '知识库检索', 'model': '无已发布文档', 'duration': 0, 'status': '无结果', 'tokens': None}]})
    monkeypatch.setattr(providers, 'make_chat', lambda *_args, **_kwargs: pytest.fail('No evidence must not call paid LLM'))
    response = client.post(f"/api/applications/{app['id']}/run", json={'input': '住宿标准是多少', 'mode': 'draft'})
    run = response.json()
    assert run['status'] == 'success' and run['output'] == '当前知识库未找到足够依据，请补充资料或调整问题。'
    assert run['steps'][2]['meter'] == 'local' and run['steps'][2]['tokens'] is None
    assert run['sources'] == [] and run['tokens'] is None
    definition['nodes'][2]['config']['requireEvidence'] = 'true'
    saved = client.patch(f"/api/applications/{app['id']}", json=definition)
    assert saved.status_code == 200
    assert not client.post(f"/api/applications/{app['id']}/validate").json()['valid']


def test_scenario_templates_are_structurally_valid():
    """report / generate / review graphs reuse existing KINDS and pass inspect_graph."""
    for kind in ('report', 'generate', 'review'):
        data = apps.scenario_template(kind)
        errors, order, *_ = apps.inspect_graph(data, resources=False)
        assert errors == [], (kind, errors)
        assert data['scenario'] == kind
        assert order[0] == 'start' and order[-1] == 'answer'
        assert {n['kind'] for n in data['nodes']} <= apps.KINDS


def test_scenario_templates_can_be_created(env):
    client, session, actor = env
    for kind in ('report', 'generate', 'review'):
        body = apps.scenario_template(kind)
        row = create(client, body)
        assert row['scenario'] == kind
        assert row['status'] == 'draft'
        assert len(row['nodes']) >= 3
