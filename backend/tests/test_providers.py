from contextlib import contextmanager

import httpx
import pytest
import respx
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import providers
from app.db import Base, Credential, get_entity, put_entity
from app.security import Actor


@pytest.fixture
def provider_env(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(engine, expire_on_commit=False)
    @contextmanager
    def db_scope():
        with session() as db:
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
    monkeypatch.setattr(providers, "db_session", db_scope)
    monkeypatch.setattr(providers.config, "data_dir", tmp_path)
    monkeypatch.setattr(providers.config, "allow_private_providers", True)
    app = FastAPI()
    app.include_router(providers.router, prefix="/api")
    app.dependency_overrides[providers.require_admin] = lambda: Actor("tester", "admin", "csrf")
    with TestClient(app) as client:
        yield client, db_scope
    engine.dispose()


def create_connection(client, provider="AIHubMix", key="test-api-key", url="http://provider.test/v1"):
    response = client.post("/api/connections", json={"name": "test connection", "provider": provider, "baseUrl": url, "apiKey": key, "enabled": True, "status": "connected"})
    assert response.status_code == 201, response.text
    return response.json()


def create_model(client, connection, type="Embedding", **fields):
    response = client.post("/api/models", json={"name": "test model", "provider": connection["provider"], "connectionId": connection["id"], "modelId": "test-model", "type": type, "enabled": True, "status": "connected", **fields})
    assert response.status_code == 201, response.text
    return response.json()


def mark_connected(db_scope, connection, model=None):
    with db_scope() as db:
        row = get_entity(db, "connection", connection["id"])
        row.payload = {**row.payload, "status": "connected"}
        if model:
            row = get_entity(db, "model", model["id"])
            row.payload = {**row.payload, "status": "connected"}


def test_save_is_offline_and_credentials_are_encrypted(provider_env):
    client, db_scope = provider_env
    with respx.mock(assert_all_called=False) as mock:
        connection = create_connection(client, key="secret-string-no-echo")
        model = create_model(client, connection)
        assert len(mock.calls) == 0
    assert connection["status"] == model["status"] == "untested"
    assert connection["keyConfigured"] is True
    assert "secret-string-no-echo" not in client.get("/api/connections").text
    with db_scope() as db:
        encrypted = db.get(Credential, connection["id"]).encrypted
        assert "secret-string-no-echo" not in encrypted
    assert providers.credentials(connection["id"])["apiKey"] == "secret-string-no-echo"


def test_connection_test_uses_authenticated_openrouter_endpoint(provider_env):
    client, _ = provider_env
    c = create_connection(client, "OpenRouter")
    with respx.mock as mock:
        route = mock.get("http://provider.test/v1/key").mock(return_value=httpx.Response(200, json={"data": {"limit": 1}}))
        response = client.post(f"/api/connections/{c['id']}/test")
        assert response.status_code == 200
        assert response.json()["status"] == "connected"
        assert route.called
        assert route.calls[0].request.headers["authorization"] == "Bearer test-api-key"


def test_upstream_errors_cannot_echo_keys(provider_env):
    client, _ = provider_env
    c = create_connection(client)
    with respx.mock as mock:
        mock.get("http://provider.test/v1/models").mock(return_value=httpx.Response(401, json={"error": "test-api-key has failed"}))
        response = client.post(f"/api/connections/{c['id']}/test")
    assert response.status_code == 502
    assert "test-api-key" not in response.text
    assert "HTTP 401" in response.text and "Base URL" in response.text
    assert client.get("/api/connections").json()[0]["status"] == "error"


def test_redirect_is_not_followed(provider_env):
    client, _ = provider_env
    c = create_connection(client)
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://provider.test/v1/models").mock(return_value=httpx.Response(302, headers={"Location": "http://127.0.0.1/private"}))
        private = mock.get("http://127.0.0.1/private").mock(return_value=httpx.Response(200, json={}))
        response = client.post(f"/api/connections/{c['id']}/test")
        assert not private.called
    assert response.status_code == 502
    assert "重定向" in response.text


def test_private_addresses_blocked_by_default(provider_env, monkeypatch):
    client, _ = provider_env
    monkeypatch.setattr(providers.config, "allow_private_providers", False)
    for url in ["https://127.0.0.1/v1", "https://10.0.0.1/v1", "https://localhost/v1", "http://example.com/v1", "https://user:password@example.com/v1", "https://example.com/v1?secret=a"]:
        response = client.post("/api/connections", json={"name": "invalid", "provider": "AIHubMix", "baseUrl": url})
        assert response.status_code == 422, (url, response.text)
    monkeypatch.setattr(providers.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("169.254.169.254", 443))])
    with pytest.raises(HTTPException) as e:
        providers.validate_outbound_url("https://rebound.example/v1")
    assert e.value.status_code == 422


def test_exact_connection_binding_and_capabilities(provider_env):
    client, db_scope = provider_env
    first = create_connection(client)
    second = create_connection(client)
    ambiguous = client.post("/api/models", json={"name": "x", "provider": "AIHubMix", "type": "LLM", "modelId": "x"})
    assert ambiguous.status_code == 409
    model = create_model(client, second, type="LLM")
    mark_connected(db_scope, second, model)
    with db_scope() as db:
        selected = providers.get_model(db, "LLM", model["id"])
        assert providers.get_connection(db, selected)["id"] == second["id"]
    deepseek = create_connection(client, "DeepSeek")
    unsupported = client.post("/api/models", json={"name": "bad", "provider": "DeepSeek", "connectionId": deepseek["id"], "modelId": "x", "type": "Embedding"})
    assert unsupported.status_code == 422


def test_bound_embedding_identity_cannot_be_changed_or_deleted(provider_env):
    client, db_scope = provider_env
    c = create_connection(client)
    model = create_model(client, c, dimension=3)
    with db_scope() as db:
        put_entity(db, "kb", {"id": "kb", "embeddingConfigId": model["id"], "embedding": model["modelId"]})
    assert client.patch(f"/api/models/{model['id']}", json={"dimension": 4}).status_code == 409
    assert client.patch(f"/api/models/{model['id']}", json={"modelId": "replacement"}).status_code == 409
    assert client.delete(f"/api/models/{model['id']}").status_code == 409
    assert client.patch(f"/api/models/{model['id']}", json={"name": "renamed"}).status_code == 200


def test_embeddings_are_ordered_and_actual_usage_retained(provider_env):
    client, db_scope = provider_env
    c = create_connection(client)
    model = create_model(client, c, dimension=3)
    mark_connected(db_scope, c, model)
    with db_scope() as db:
        embed = providers.make_embeddings(db, model)
    with respx.mock as mock:
        route = mock.post("http://provider.test/v1/embeddings").mock(return_value=httpx.Response(200, json={"data": [{"index": 1, "embedding": [0, 1, 0]}, {"index": 0, "embedding": [1, 0, 0]}], "usage": {"prompt_tokens": 6, "total_tokens": 6}}))
        result = embed.embed_documents(["a", "b"])
    assert result == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    assert embed.last_usage["input_tokens"] == 6
    assert embed.last_usage["total_tokens"] == 6
    assert b'"input":["a","b"]' in route.calls[0].request.content


def test_embeddings_reject_dimension_mismatch_and_unknown_is_not_zero(provider_env):
    client, db_scope = provider_env
    c = create_connection(client)
    model = create_model(client, c, dimension=3)
    with db_scope() as db:
        embed = providers.make_embeddings(db, model)
    with respx.mock as mock:
        route = mock.post("http://provider.test/v1/embeddings")
        route.mock(return_value=httpx.Response(200, json={"data": [{"index": 0, "embedding": [1, 0]}]}))
        with pytest.raises(HTTPException) as exc:
            embed.embed_query("a")
        assert exc.value.status_code == 409
        route.mock(return_value=httpx.Response(200, json={"data": [{"index": 0, "embedding": [1, 0, 0]}]}))
        embed.embed_query("a")
    assert embed.last_usage is None


def test_dashscope_rerank_protocol_is_not_openai_shape(provider_env):
    client, db_scope = provider_env
    c = create_connection(client, "阿里云百炼", url="http://provider.test/compatible-mode/v1")
    model = create_model(client, c, type="Rerank")
    with respx.mock as mock:
        route = mock.post("http://provider.test/api/v1/services/rerank/text-rerank/text-rerank").mock(return_value=httpx.Response(200, json={"output": {"results": [{"index": 1, "relevance_score": .9}]}, "usage": {"total_tokens": 7}}))
        with db_scope() as db:
            ranks, usage = providers.rerank(db, model, "q", ["a", "b"], 999)
    import json
    body = json.loads(route.calls[0].request.content)
    assert body["input"] == {"query": "q", "documents": ["a", "b"]}
    assert body["parameters"]["top_n"] == 2
    assert ranks == [{"index": 1, "score": .9}]
    assert usage["total_tokens"] == 7


def test_rerank_rejects_invalid_vendor_indices(provider_env):
    client, db_scope = provider_env
    c = create_connection(client)
    model = create_model(client, c, type="Rerank")
    with respx.mock as mock:
        mock.post("http://provider.test/v1/rerank").mock(return_value=httpx.Response(200, json={"results": [{"index": 99, "relevance_score": .8}]}))
        with db_scope() as db, pytest.raises(HTTPException):
            providers.rerank(db, model, "q", ["a"], 1)


def test_docmind_credentials_remain_separate_and_no_fake_test_success(provider_env):
    client, _ = provider_env
    c = client.post("/api/connections", json={"name": "ocr", "provider": "阿里云 DocMind", "accessId": "ak-id", "accessSecret": "secret-ak"}).json()
    assert c["keyConfigured"] is True
    assert "secret-ak" not in str(c)
    assert providers.credentials(c["id"]) == {"accessId": "ak-id", "accessSecret": "secret-ak"}
    with respx.mock(assert_all_called=False) as mock:
        response = client.post(f"/api/connections/{c['id']}/test")
        assert not mock.calls
    assert response.json()["status"] == "untested"


def test_provider_routes_require_authentication():
    app = FastAPI(); app.include_router(providers.router, prefix="/api")
    with TestClient(app) as client:
        assert client.get("/api/connections").status_code == 401
        assert client.post("/api/models", json={}).status_code == 401


def test_langchain_chat_uses_compatible_max_tokens_and_closes_clients(provider_env):
    client, db_scope = provider_env
    c = create_connection(client)
    model = create_model(client, c, type="LLM", maxOutput=32)
    with db_scope() as db:
        llm = providers.make_chat(db, model, streaming=False)
    try:
        with respx.mock as mock:
            route = mock.post("http://provider.test/v1/chat/completions").mock(return_value=httpx.Response(200, json={"id": "completion-test", "object": "chat.completion", "created": 1, "model": "test-model", "choices": [{"index": 0, "message": {"role": "assistant", "content": "正常"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5}}))
            result = llm.invoke("连接测试")
            import json
            body = json.loads(route.calls[0].request.content)
            assert body["max_tokens"] == 32
            assert "max_completion_tokens" not in body
            assert result.usage_metadata["total_tokens"] == 5
    finally:
        providers.close_chat(llm)
    assert llm.http_client.is_closed
    assert llm.http_async_client.is_closed


def test_model_test_endpoint_persists_actual_usage_not_synthetic_counts(provider_env):
    client, db_scope = provider_env
    c = create_connection(client)
    model = create_model(client, c)
    mark_connected(db_scope, c)
    with respx.mock as mock:
        mock.post("http://provider.test/v1/embeddings").mock(return_value=httpx.Response(200, json={"data": [{"index": 0, "embedding": [1, 0, 0]}], "usage": {"prompt_tokens": 8, "total_tokens": 8}}))
        response = client.post(f"/api/models/{model['id']}/test")
    assert response.status_code == 200
    assert response.json()["model"]["dimension"] == 3
    with db_scope() as db:
        from app.db import list_entities
        logs = list_entities(db, "log")
        assert len(logs) == 1
        assert logs[0].payload["tokens"] == 8
        assert logs[0].payload["inputTokens"] == 8
        assert logs[0].payload["outputTokens"] is None
        assert logs[0].payload["firstToken"] is None


def test_lost_encryption_key_can_be_recovered_with_complete_credentials(provider_env, monkeypatch):
    client, _ = provider_env
    c = create_connection(client)
    def cannot_decrypt(_):
        raise ValueError("lost key")
    monkeypatch.setattr(providers, "decrypt_secret", cannot_decrypt)
    assert client.patch(f"/api/connections/{c['id']}", json={"name": "rename"}).status_code == 503
    replaced = client.patch(f"/api/connections/{c['id']}", json={"apiKey": "replacement-test-only-key"})
    assert replaced.status_code == 200
    assert replaced.json()["status"] == "untested"
    cleared = client.patch(f"/api/connections/{c['id']}", json={"clearCredentials": True})
    assert cleared.status_code == 200
    assert cleared.json()["keyConfigured"] is False


def test_bound_embedding_connection_space_is_immutable_but_credentials_can_rotate(provider_env):
    client, db_scope = provider_env
    connection = create_connection(client)
    model = create_model(client, connection, dimension=3)
    with db_scope() as db:
        put_entity(db, "kb", {"id": "bound-kb", "embeddingConfigId": model["id"], "embedding": model["modelId"]})
    for patch in [{"baseUrl": "http://replacement.test/v1"}, {"provider": "OpenRouter"}, {"protocol": "different-protocol"}]:
        response = client.patch(f"/api/connections/{connection['id']}", json=patch)
        assert response.status_code == 409
        assert "新增连接" in response.json()["detail"]
    unchanged = client.get("/api/connections").json()[0]
    assert unchanged["baseUrl"] == connection["baseUrl"]
    assert unchanged["provider"] == connection["provider"]
    allowed = client.patch(f"/api/connections/{connection['id']}", json={"apiKey": "rotated-key-test-only", "name": "renamed", "enabled": False, "rerankUrl": "http://rerank.test/v1/rerank"})
    assert allowed.status_code == 200
    assert allowed.json()["name"] == "renamed"
    assert providers.credentials(connection["id"])["apiKey"] == "rotated-key-test-only"


def test_inline_model_configuration_accepts_sdk_names_and_encrypts_key(provider_env):
    client, db_scope = provider_env
    with respx.mock(assert_all_called=False) as cloud:
        response = client.post("/api/models/configure", json={"name": "inline model", "provider": "OpenRouter", "type": "LLM", "model": "vendor/actual-model", "base_url": "http://inline.test/v1", "api_key": "inline-secret-never-public", "context": 8192})
        assert not cloud.calls
    assert response.status_code == 201, response.text
    assert "inline-secret-never-public" not in response.text
    model, connection = response.json()["model"], response.json()["connection"]
    assert model["modelId"] == "vendor/actual-model"
    assert model["connectionId"] == connection["id"]
    assert connection["baseUrl"] == "http://inline.test/v1" and connection["keyConfigured"]
    assert model["status"] == connection["status"] == "untested"
    assert not {"apiKey", "api_key", "baseUrl", "base_url", "connectionMode"} & set(model)
    with db_scope() as db:
        encrypted = db.get(Credential, connection["id"]).encrypted
        assert "inline-secret-never-public" not in encrypted
    assert providers.credentials(connection["id"])["apiKey"] == "inline-secret-never-public"


def test_inline_failed_model_save_rolls_back_new_connection_and_credential(provider_env):
    client, db_scope = provider_env
    response = client.post("/api/models/configure", json={"name": "bad capabilities", "provider": "DeepSeek", "type": "Embedding", "model": "unsupported", "base_url": "http://rollback.test/v1", "api_key": "rollback-test-key"})
    assert response.status_code == 422
    assert client.get("/api/connections").json() == []
    assert client.get("/api/models").json() == []
    with db_scope() as db:
        assert db.query(Credential).count() == 0


def test_inline_edit_preserves_blank_key_and_uses_existing_connection(provider_env):
    client, _ = provider_env
    connection = create_connection(client, key="keep-original-test-key")
    model = create_model(client, connection, type="LLM")
    response = client.patch(f"/api/models/{model['id']}/configure", json={"base_url": "http://updated.test/v1", "api_key": "", "model": "updated-model"})
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["connection"]["id"] == connection["id"]
    assert updated["connection"]["baseUrl"] == "http://updated.test/v1"
    assert updated["model"]["modelId"] == "updated-model"
    assert providers.credentials(connection["id"])["apiKey"] == "keep-original-test-key"
    assert "keep-original-test-key" not in response.text
    assert len(client.get("/api/connections").json()) == 1


def test_inline_shared_connection_update_requires_explicit_choice(provider_env):
    client, db_scope = provider_env
    connection = create_connection(client)
    first = create_model(client, connection, type="LLM")
    second = create_model(client, connection, type="Vision")
    mark_connected(db_scope, connection, first)
    mark_connected(db_scope, connection, second)
    url = f"/api/models/{first['id']}/configure"
    patch = {"baseUrl": "http://shared-new.test/v1", "apiKey": "shared-rotated-test-key"}
    rejected = client.patch(url, json=patch)
    assert rejected.status_code == 409 and "共享连接" in rejected.text
    assert client.get("/api/connections").json()[0]["baseUrl"] == connection["baseUrl"]
    accepted = client.patch(url, json={**patch, "updateSharedConnection": True})
    assert accepted.status_code == 200
    assert providers.credentials(connection["id"])["apiKey"] == "shared-rotated-test-key"
    assert all(model["status"] == "untested" for model in client.get("/api/models").json())


def test_inline_configuration_cannot_bypass_bound_embedding_protection(provider_env):
    client, db_scope = provider_env
    connection = create_connection(client)
    model = create_model(client, connection, dimension=3)
    with db_scope() as db:
        put_entity(db, "kb", {"id": "bound-inline", "embeddingConfigId": model["id"]})
    url = f"/api/models/{model['id']}/configure"
    for patch in [{"baseUrl": "http://wrong-space.test/v1"}, {"model": "wrong-model"}, {"connectionMode": "new", "apiKey": "new-connection-test-key"}]:
        response = client.patch(url, json=patch)
        assert response.status_code == 409, response.text
        assert len(client.get("/api/connections").json()) == 1
        assert providers.credentials(connection["id"])["apiKey"] == "test-api-key"
    rotated = client.patch(url, json={"api_key": "allowed-rotation-test-key"})
    assert rotated.status_code == 200
    assert providers.credentials(connection["id"])["apiKey"] == "allowed-rotation-test-key"


def test_qwen_multimodal_uses_native_payload_and_twenty_item_batches(provider_env):
    client, db_scope = provider_env
    c = create_connection(client, '阿里云百炼')
    model = create_model(client, c, modelId='qwen3-vl-embedding', dimension=3, sendDimensions=True)
    with db_scope() as db: embed = providers.make_embeddings(db, model)
    seen = []
    def respond(request):
        import json
        body = json.loads(request.content); seen.append(body)
        return httpx.Response(200, json={'output': {'embeddings': [{'index': i, 'embedding': [1, 0, 0]} for i in range(len(body['input']['contents']))]}, 'usage': {'input_tokens': 4, 'total_tokens': 4}})
    with respx.mock as mock:
        mock.post('http://provider.test/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding').mock(side_effect=respond)
        assert len(embed.embed_documents(['测试'] * 21)) == 21
    assert [len(x['input']['contents']) for x in seen] == [20, 1]
    assert seen[0]['parameters'] == {'enable_fusion': False, 'dimension': 3}
    assert embed.last_usage['total_tokens'] == 8


def test_sensenova_rejects_false_embedding_and_image_understanding(provider_env):
    client, _ = provider_env
    c = create_connection(client, 'SenseNova')
    for model, kind in [('sensenova-6.8-flash-lite', 'Embedding'), ('sensenova-u1.5-fast', 'Vision')]:
        r = client.post('/api/models', json={'name': 'bad', 'provider': 'SenseNova', 'connectionId': c['id'], 'modelId': model, 'type': kind})
        assert r.status_code == 422


def test_sensenova_rerank_uses_chat_and_rejects_invented_indexes(provider_env):
    client, scope = provider_env
    c = create_connection(client, 'SenseNova')
    model = create_model(client, c, type='Rerank', modelId='sensenova-6.8-flash-lite')
    with respx.mock as mock:
        route = mock.post('http://provider.test/v1/chat/completions')
        route.mock(return_value=httpx.Response(200, json={'choices':[{'message':{'content':'[{"index":0,"score":0.9}]'}}], 'usage': {'total_tokens': 42}}))
        with scope() as db:
            ranks, usage = providers.rerank(db, model, '问题', ['相关', '无关'], 1)
        assert ranks == [{'index': 0, 'score': .9}] and usage['total_tokens'] == 42
        route.mock(return_value=httpx.Response(200, json={'choices':[{'message':{'content':'[{"index":9,"score":0.9},{"index":1,"score":0.1}]'}}]}))
        with scope() as db, pytest.raises(HTTPException):
            providers.rerank(db, model, '问题', ['相关', '无关'], 1)


def test_model_test_authenticates_connection_first(provider_env):
    client, _ = provider_env
    c = create_connection(client)
    model = create_model(client, c)
    with respx.mock as mock:
        auth = mock.get('http://provider.test/v1/models').mock(return_value=httpx.Response(200, json={'data': []}))
        embed = mock.post('http://provider.test/v1/embeddings').mock(return_value=httpx.Response(200, json={'data':[{'index':0,'embedding':[1,0,0]}]}))
        response = client.post(f"/api/models/{model['id']}/test")
        assert response.status_code == 200 and auth.called and embed.called
        assert response.json()['model']['dimension'] == 3


def test_pasted_full_operation_url_is_normalized(provider_env):
    client, _ = provider_env
    c = create_connection(client, url='http://provider.test/v1/chat/completions/')
    assert c['baseUrl'] == 'http://provider.test/v1'


def test_sensenova_rerank_batches_candidates_and_preserves_usage(provider_env):
    client, scope = provider_env
    c = create_connection(client, 'SenseNova')
    model = create_model(client, c, type='Rerank', modelId='sensenova-6.8-flash-lite')
    batches = []
    def respond(request):
        import json
        data = json.loads(request.content)
        docs = json.loads(data['messages'][1]['content'])['documents']; batches.append(docs)
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps([{'index': 0, 'score': .8}])}}], 'usage': {'total_tokens': 10}})
    with respx.mock as mock, scope() as db:
        mock.post('http://provider.test/v1/chat/completions').mock(side_effect=respond)
        ranks, usage = providers.rerank(db, model, 'query', ['doc'] * 17, 1)
    assert [len(b) for b in batches] == [8, 8, 1]
    assert len(ranks) == 1 and usage['total_tokens'] == 30
