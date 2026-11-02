"""HTTP contract E2E: only external cloud HTTP is replaced by test responses.

This does not claim that an actual paid provider account was exercised. The
application, auth, parser, SQL commits, local Qdrant, LangChain chain, and SSE
transport are real and operate exclusively inside pytest's temporary folder.
"""
import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import db as database
from app import ingestion, rag, security
from app.config import config
from app.db import get_entity
from app.main import app


@pytest.fixture
def full_stack(tmp_path,monkeypatch):
    url=f"sqlite:///{tmp_path / 'integration.db'}"
    engine=create_engine(url,connect_args={"check_same_thread":False,"timeout":30})
    monkeypatch.setattr(database,"engine",engine)
    monkeypatch.setattr(database,"SessionLocal",sessionmaker(engine,expire_on_commit=False))
    monkeypatch.setattr(config,"data_dir",tmp_path)
    monkeypatch.setattr(config,"database_url",url)
    monkeypatch.setattr(config,"qdrant_url","")
    monkeypatch.setattr(config,"qdrant_api_key","")
    monkeypatch.setattr(config,"task_mode","local")
    monkeypatch.setattr(config,"allow_private_providers",True)
    monkeypatch.setattr(config,"secret_key","")
    monkeypatch.setattr(config,"admin_password","")
    monkeypatch.setattr(config,"manager_password","")
    # Capture dispatch only: process_task below executes the real durable pipeline.
    queued=[]
    monkeypatch.setattr(ingestion,"enqueue",queued.append)
    monkeypatch.setattr(rag,"_vector_client",None)
    rag._lexical_cache.clear();security._failures.clear()
    with TestClient(app,raise_server_exceptions=False) as client:
        passwords=json.loads((tmp_path/"bootstrap-passwords.json").read_text())
        session=client.get("/api/session").json()
        logged=client.post("/api/auth/login",json={"role":"admin","password":passwords["admin"]},headers={"X-CSRF-Token":session["csrf"]})
        assert logged.status_code==200
        headers={"X-CSRF-Token":logged.json()["csrf"]}
        yield client,headers,queued,tmp_path
    engine.dispose()


def test_real_import_publish_retrieve_chat_and_disable(full_stack):
    client,headers,queued,tmp_path=full_stack
    base="https://integration-cloud.example/v1"
    calls={"embedding":0,"rerank":0,"chat":0,"stream":0}

    def embedding_response(request):
        payload=json.loads(request.content)
        assert request.headers["authorization"]=="Bearer test-contract-key-not-a-real-secret"
        assert payload["model"]=="contract-embedding"
        inputs=payload["input"] if isinstance(payload["input"],list) else [payload["input"]]
        calls["embedding"]+=1
        return httpx.Response(200,json={"data":[{"index":i,"embedding":[1.,.2,.3,.4]} for i in range(len(inputs))],"usage":{"prompt_tokens":5,"total_tokens":5}})

    def rerank_response(request):
        payload=json.loads(request.content);calls["rerank"]+=1
        assert payload["model"]=="contract-rerank"
        assert payload["documents"] and 1<=payload["top_n"]<=len(payload["documents"])
        return httpx.Response(200,json={"results":[{"index":i,"relevance_score":.99-i*.02} for i in range(min(payload["top_n"],len(payload["documents"])))],"usage":{"total_tokens":7}})

    def chat_response(request):
        payload=json.loads(request.content);calls["chat"]+=1
        assert payload["model"]=="contract-llm"
        if not payload.get("stream"):
            return httpx.Response(200,json={"id":"test-connection","object":"chat.completion","created":1,"model":"contract-llm","choices":[{"index":0,"message":{"role":"assistant","content":"连接正常"},"finish_reason":"stop"}],"usage":{"prompt_tokens":3,"completion_tokens":2,"total_tokens":5}})
        calls["stream"]+=1
        assert any("500" in message.get("content","") for message in payload["messages"])
        parts=[
            {"id":"test-stream","object":"chat.completion.chunk","created":1,"model":"contract-llm","choices":[{"index":0,"delta":{"role":"assistant","content":"一线城市住宿标准为500元/人/晚。[1]"},"finish_reason":None}]},
            {"id":"test-stream","object":"chat.completion.chunk","created":1,"model":"contract-llm","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]},
            {"id":"test-stream","object":"chat.completion.chunk","created":1,"model":"contract-llm","choices":[],"usage":{"prompt_tokens":10,"completion_tokens":20,"total_tokens":30}},
        ]
        wire="".join("data: "+json.dumps(p,ensure_ascii=False)+"\n\n" for p in parts)+"data: [DONE]\n\n"
        return httpx.Response(200,headers={"content-type":"text/event-stream"},content=wire.encode())

    with respx.mock(assert_all_called=True) as cloud:
        cloud.get(base+"/models").mock(return_value=httpx.Response(200,json={"data":[{"id":"contract-embedding"},{"id":"contract-rerank"},{"id":"contract-llm"}]}))
        cloud.post(base+"/embeddings").mock(side_effect=embedding_response)
        cloud.post(base+"/rerank").mock(side_effect=rerank_response)
        cloud.post(base+"/chat/completions").mock(side_effect=chat_response)
        connection=client.patch("/api/connections/aihubmix",json={"baseUrl":base,"apiKey":"test-contract-key-not-a-real-secret","enabled":True},headers=headers)
        assert connection.status_code==200,connection.text
        tested=client.post("/api/connections/aihubmix/test",headers=headers)
        assert tested.status_code==200,tested.text
        model_ids={}
        for type,id,extra in [("Embedding","contract-embedding",{"dimension":4}),("Rerank","contract-rerank",{}),("LLM","contract-llm",{"context":8192})]:
            created=client.post("/api/models",json={"name":type+" 集成模型","provider":"AIHubMix","connectionId":"aihubmix","modelId":id,"type":type,"enabled":True,**extra},headers=headers)
            assert created.status_code==201,created.text
            model_ids[type]=created.json()["id"]
            tested=client.post(f"/api/models/{created.json()['id']}/test",headers=headers)
            assert tested.status_code==200,tested.text

        library=client.post("/api/knowledge-bases",json={"name":"真实链路验收库","embeddingConfigId":model_ids["Embedding"]},headers=headers)
        assert library.status_code==201,library.text
        kb_id=library.json()["id"]
        content="# 差旅住宿制度\n\n一线城市住宿费用标准为500元/人/晚，其他城市350元/人/晚。报销需提供有效发票。\n"
        uploaded=client.post(f"/api/knowledge-bases/{kb_id}/documents",files={"files":("真实差旅制度.md",content.encode(),"text/markdown")},data={"autoPublish":"false","parser":"auto","imageUnderstanding":"false"},headers=headers)
        assert uploaded.status_code==202,uploaded.text
        task_id=uploaded.json()["tasks"][0]["id"];doc_id=uploaded.json()["tasks"][0]["docId"]
        assert queued==[task_id]
        ingestion.process_task(task_id)
        doc=client.get(f"/api/documents/{doc_id}").json()
        assert doc["status"]=="review" and doc["draftChunks"]
        assert "500" in "".join(c["content"] for c in doc["draftChunks"])
        before_embeddings=calls["embedding"]
        before=client.post(f"/api/knowledge-bases/{kb_id}/retrieve",json={"query":"住宿费用标准"},headers=headers)
        assert before.status_code==200 and before.json()["sources"]==[]
        assert calls["embedding"]==before_embeddings

        publish=client.post(f"/api/documents/{doc_id}/publish",headers=headers)
        assert publish.status_code==202,publish.text
        assert queued[-1]==publish.json()["id"]
        ingestion.process_task(publish.json()["id"])
        ready=client.get(f"/api/documents/{doc_id}").json()
        assert ready["status"]=="ready" and ready["chunks"]
        assert (tmp_path/"qdrant").is_dir() and (tmp_path/"integration.db").is_file()
        with database.db_session() as db:
            persisted=get_entity(db,"doc",doc_id).payload
            assert persisted["publishedIndexVersion"]
        retrieval=client.post(f"/api/knowledge-bases/{kb_id}/retrieve",json={"query":"住宿费用标准"},headers=headers)
        assert retrieval.status_code==200,retrieval.text
        assert retrieval.json()["sources"][0]["docId"]==doc_id
        assert "500" in retrieval.json()["results"][0]["chunk"]["content"]
        assert str(tmp_path) not in retrieval.text

        streamed=client.post("/api/chat/stream",json={"kbIds":[kb_id],"question":"一线城市住宿费用标准是多少？"},headers=headers)
        assert streamed.status_code==200,streamed.text
        assert all(f"event: {e}" in streamed.text for e in ("meta","sources","token","done"))
        assert "500元" in streamed.text and "event: error" not in streamed.text
        sessions=client.get("/api/chat-sessions").json()
        answer=sessions[0]["messages"][-1]
        assert answer["status"]=="complete" and answer["tokens"]==20
        assert answer["sources"][0]["docId"]==doc_id
        source=answer["sources"][0]
        original=client.get(source["originalUrl"])
        assert original.status_code==200 and original.content==content.encode()
        logs=client.get("/api/logs",params={"source":"chat","q":"一线城市住宿费用标准是多少"}).json()["items"]
        assert len(logs)==1 and logs[0]["status"]=="success"
        assert logs[0]["inputTokens"]==10 and logs[0]["outputTokens"]==20
        assert logs[0]["tokens"]==42
        assert logs[0]["firstToken"] is not None and len(logs[0]["steps"])==4
        state=client.get("/api/state")
        assert state.status_code==200
        assert "test-contract-key-not-a-real-secret" not in state.text

        disabled=client.patch(f"/api/documents/{doc_id}",json={"status":"disabled"},headers=headers)
        assert disabled.status_code==200
        after=client.post(f"/api/knowledge-bases/{kb_id}/retrieve",json={"query":"住宿费用标准"},headers=headers)
        assert after.status_code==200 and not after.json()["sources"]
        assert calls["stream"]==1


def test_ten_anonymous_conversations_do_not_mix_sessions(full_stack):
    """Ten concurrent API flows, no cloud dependency: empty knowledge is deterministic."""
    import asyncio
    client,headers,queued,tmp_path=full_stack
    library=client.post('/api/knowledge-bases',json={'name':'并发空知识库'},headers=headers)
    assert library.status_code==201
    kb_id=library.json()['id']
    async def one(index):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver',timeout=30) as browser:
            session=(await browser.get('/api/session')).json()
            response=await browser.post('/api/chat/stream',json={'kbIds':[kb_id],'question':f'并发验证问题 {index}'},headers={'X-CSRF-Token':session['csrf']})
            assert response.status_code==200,response.text
            assert 'event: done' in response.text and '未找到足够依据' in response.text
            own=(await browser.get('/api/chat-sessions')).json()
            assert len(own)==1
            assert own[0]['messages'][0]['content']==f'并发验证问题 {index}'
            return own[0]['id']
    async def all_requests():return await asyncio.gather(*(one(i) for i in range(10)))
    ids=asyncio.run(all_requests())
    assert len(set(ids))==10
