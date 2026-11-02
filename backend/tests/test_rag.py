"""Real SQL/Qdrant/LC chain; only cloud model calls are test doubles."""
from contextlib import contextmanager
from hashlib import sha256

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from qdrant_client import QdrantClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import rag
from app.db import Base, get_entity, put_entity, list_entities
from app.security import Actor, current_session


class TestEmbeddings(Embeddings):
    last_usage = None
    def embed_documents(self, texts):
        self.last_usage={"input_tokens":len(texts)*5,"total_tokens":len(texts)*5}
        return [[(b+1)/256 for b in sha256(text.encode()).digest()[:4]] for text in texts]
    def embed_query(self, text):
        return self.embed_documents([text])[0]


@pytest.fixture
def env(monkeypatch):
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine);factory=sessionmaker(engine,expire_on_commit=False)
    @contextmanager
    def session():
        with factory() as db:
            try:yield db;db.commit()
            except BaseException:db.rollback();raise
    vector=QdrantClient(":memory:")
    rag._lexical_cache.clear()
    monkeypatch.setattr(rag,"db_session",session)
    monkeypatch.setattr(rag,"_vector_client",vector)
    model={"id":"embedding-config","type":"Embedding","modelId":"cloud-test","dimension":4,"connectionId":"con"}
    def model_for(db,type,model_id=None):
        if type=="Rerank":
            from fastapi import HTTPException
            raise HTTPException(409,"未配置重排")
        return model if type=="Embedding" else {"id":"llm","modelId":"cloud-chat","context":8192}
    monkeypatch.setattr(rag.providers,"get_model",model_for)
    monkeypatch.setattr(rag.providers,"make_embeddings",lambda *_:TestEmbeddings())
    monkeypatch.setattr(rag.providers,"make_chat",lambda *_,**__:FakeListChatModel(responses=["住宿费用标准为500元。[1]"]))
    with session() as db:
        put_entity(db,"kb",{"id":"kb","name":"制度","embedding":"cloud-test","embeddingConfigId":"embedding-config"})
        put_entity(db,"kb",{"id":"other","name":"其他部门","embedding":"cloud-test","embeddingConfigId":"embedding-config"})
        put_entity(db,"setting",{"id":"system","chatConcurrency":10,"rerankRequired":False})
    actor={"value":Actor("owner-a","admin","csrf")}
    app=FastAPI();app.include_router(rag.router,prefix="/api")
    app.dependency_overrides[current_session]=lambda:actor["value"]
    with TestClient(app) as client:
        yield client,session,actor
    vector.close();engine.dispose()


def add_doc(session,id="doc",kb="kb",status="ready",version="1",text="住宿费用标准为500元，每晚。"):
    doc={"id":id,"kbId":kb,"name":id+".md","status":status,"version":1,"publishedIndexVersion":version,
         "chunks":[{"id":"c1","title":"费用标准","content":text,"location":"费用 / 住宿","kind":"text"}]}
    with session() as db:
        rag.index_document(db,doc,doc["chunks"],get_entity(db,"kb",kb).payload,version)
        put_entity(db,"doc",doc,parent_id=kb)
    return doc


def test_version_and_authoritative_doc_filter(env):
    _,session,_=env
    add_doc(session)
    add_doc(session,id="disabled",status="disabled")
    add_doc(session,id="unpublished",status="review")
    add_doc(session,id="other-doc",kb="other")
    result=rag.retrieve_sync(["kb"],"住宿费用标准",rag.RetrievalBody(query="住宿费用标准",minScore=0,rerank=False))
    assert {s["docId"] for s in result["sources"]}=={"doc"}
    with session() as db:
        row=get_entity(db,"doc","doc");d=dict(row.payload);d["status"]="disabled";row.payload=d
    assert not rag.retrieve_sync(["kb"],"住宿费用标准")["sources"]


def test_unpublished_vector_version_is_never_visible(env):
    _,session,_=env
    doc=add_doc(session)
    draft=[{"id":"draft","title":"秘密草稿","content":"新草稿版本尚未发布","location":"草稿","kind":"text"}]
    with session() as db:rag.index_document(db,doc,draft,get_entity(db,"kb","kb").payload,"staging-2")
    result=rag.retrieve_sync(["kb"],"草稿",rag.RetrievalBody(query="草稿",mode="semantic",minScore=0,rerank=False))
    assert all(s["chunkId"]=="c1" for s in result["sources"])


def test_empty_evidence_does_not_call_llm(env,monkeypatch):
    client,session,_=env
    monkeypatch.setattr(rag.providers,"make_chat",lambda *_args,**_kw:pytest.fail("LLM must not run for empty evidence"))
    response=client.post("/api/chat/stream",json={"kbIds":["kb"],"question":"火星基地建设"})
    assert response.status_code==200
    assert "未找到足够依据" in response.text and "event: done" in response.text
    with session() as db:
        log=list_entities(db,"log")[0].payload
        assert log["status"]=="success" and log["tokens"] is None


def test_stream_chain_logs_and_owner_privacy(env):
    client,session,actor=env
    add_doc(session)
    response=client.post("/api/chat/stream",json={"kbIds":["kb"],"question":"住宿费用标准是多少"})
    assert response.status_code==200
    assert "event: token" in response.text and "event: sources" in response.text and "event: done" in response.text
    sessions=client.get("/api/chat-sessions").json();assert len(sessions)==1
    saved=sessions[0];assert saved["messages"][-1]["sources"][0]["docId"]=="doc"
    assert saved["messages"][-1]["status"]=="complete"
    with session() as db:
        log=list_entities(db,"log")[0].payload
        assert log["tokens"] is None  # Fake chat does not report supplier usage.
        assert log["status"]=="degraded"
        assert len(log["steps"])>=3
    actor["value"]=Actor("owner-b","admin","csrf")
    assert client.get("/api/chat-sessions").json()==[]
    assert client.patch("/api/chat-sessions/"+saved["id"],json={"title":"hijack"}).status_code==404
    assert client.delete("/api/chat-sessions/"+saved["id"]).status_code==404


def test_invalid_dimension_rejected_without_publish(env,monkeypatch):
    _,session,_=env
    class BadEmbeddings(TestEmbeddings):
        def embed_documents(self,texts):return [[1.,2.] for _ in texts]
    monkeypatch.setattr(rag.providers,"make_embeddings",lambda *_:BadEmbeddings())
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:add_doc(session)
    assert error.value.status_code==502
    with session() as db:assert not list_entities(db,"doc")


def test_followup_query_uses_only_owner_session_history(env):
    client,session,actor=env
    add_doc(session,text="住宿费用审批流程：员工提交，负责人审批，财务审核。")
    first=client.post("/api/chat/stream",json={"kbIds":["kb"],"question":"住宿费用审批流程"})
    assert first.status_code==200
    session_id=client.get("/api/chat-sessions").json()[0]["id"]
    second=client.post("/api/chat/stream",json={"sessionId":session_id,"kbIds":["kb"],"question":"然后下一步呢"})
    assert second.status_code==200
    with session() as db:
        log=list_entities(db,"log")[0].payload
        assert log["question"]=="然后下一步呢"
        assert "住宿费用审批流程" in log["retrievalQuery"]
    actor["value"]=Actor("owner-b","user","csrf")
    assert client.post("/api/chat/stream",json={"sessionId":session_id,"kbIds":["kb"],"question":"然后下一步呢"}).status_code==404
    assert rag.resolve_retrieval_query("下一步呢",[])=="下一步呢"
    assert rag.resolve_retrieval_query("产品支持哪些格式",[{"role":"user","content":"住宿费用"}])=="产品支持哪些格式"


def test_retrieval_does_not_disclose_internal_asset_paths(env):
    client,session,_=env
    add_doc(session)
    with session() as db:
        row=get_entity(db,"doc","doc")
        row.payload={**row.payload,"originalPath":"/private/original.pdf","pendingOriginal":{"path":"/private/new.pdf"},"pendingIndex":{"path":"/private/index"},"versionHistory":[{"path":"/private/old"}],"sha256":"private-hash"}
    response=client.post("/api/knowledge-bases/kb/retrieve",json={"query":"住宿费用标准","mode":"keyword","rerank":False})
    assert response.status_code==200
    assert "/private/" not in response.text
    assert "private-hash" not in response.text


def test_real_langchain_openai_sse_usage_is_recorded(env,monkeypatch):
    import httpx
    import json
    import respx
    from langchain_openai import ChatOpenAI
    client,session,_=env
    add_doc(session)
    monkeypatch.setattr(rag.providers,"make_chat",lambda *_args,**_kw:ChatOpenAI(model="test-cloud-model",api_key="test-only-key",base_url="https://cloud-model.example/v1",streaming=True,stream_usage=True,use_responses_api=False,max_retries=0,http_client=httpx.Client(trust_env=False),http_async_client=httpx.AsyncClient(trust_env=False)))
    payloads=[
        {"id":"test-1","object":"chat.completion.chunk","created":1,"model":"test-cloud-model","choices":[{"index":0,"delta":{"role":"assistant","content":"住宿费用为500元。[1]"},"finish_reason":None}]},
        {"id":"test-1","object":"chat.completion.chunk","created":1,"model":"test-cloud-model","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]},
        {"id":"test-1","object":"chat.completion.chunk","created":1,"model":"test-cloud-model","choices":[],"usage":{"prompt_tokens":10,"completion_tokens":20,"total_tokens":30}},
    ]
    wire="".join("data: "+json.dumps(p,ensure_ascii=False)+"\n\n" for p in payloads)+"data: [DONE]\n\n"
    with respx.mock(assert_all_called=True) as mock:
        route=mock.post("https://cloud-model.example/v1/chat/completions").mock(return_value=httpx.Response(200,headers={"content-type":"text/event-stream"},content=wire.encode()))
        response=client.post("/api/chat/stream",json={"kbIds":["kb"],"question":"住宿费用标准"})
        assert response.status_code==200 and "event: done" in response.text
        assert route.called, response.text
    with session() as db:
        log=list_entities(db,"log")[0].payload
        assert log["inputTokens"]==10 and log["outputTokens"]==20
        assert log["steps"][-1]["tokens"]==30
        assert log["tokens"]==35  # 5 embedding + 30 LLM, skipped rerank is not charged.


@pytest.mark.asyncio
async def test_stream_disconnect_records_cancelled_and_releases_slot(env):
    _,session,actor=env
    add_doc(session)
    class Request:
        async def is_disconnected(self):return False
    response=await rag.chat_stream(rag.ChatBody(kbIds=["kb"],question="住宿费用标准"),Request(),actor["value"])
    iterator=response.body_iterator
    assert "event: meta" in await anext(iterator)
    assert "event: sources" in await anext(iterator)
    assert "event: token" in await anext(iterator)
    await iterator.aclose()
    assert not rag._active_chats
    with session() as db:
        log=list_entities(db,"log")[0].payload
        assert log["status"]=="cancelled"
        assert log["steps"][-1]["status"]=="已取消"
        chat=list_entities(db,"chat")[0].payload
        assert chat["messages"][-1]["status"]=="cancelled"


@pytest.mark.parametrize("context_limit",[4096,8192])
def test_entire_prompt_and_output_fit_context_budget(context_limit):
    history=[{"role":"user" if i%2==0 else "assistant","content":f"历史第{i}条"+"长内容"*2000} for i in range(12)]
    sources=[{"docId":"doc","chunkId":f"c{i}","title":"制度.md","location":"住宿标准","content":"每晚住宿报销标准500元。"*2000} for i in range(5)]
    payload,bounded,output_limit=rag.prepare_generation({"context":context_limit,"maxOutput":2048},"住宿报销标准"*20,history,sources)
    messages=rag._prompt.invoke(payload).to_messages()
    assert rag._prompt_budget(messages)+output_limit<=context_limit
    assert 0<output_limit<=2048 and payload["history"]
    assert "历史第11条" in payload["history"][-1].content
    assert bounded and bounded[0]["content"]!=sources[0]["content"]
    assert bounded[0]["content"] in payload["context"]
    assert payload["question"]=="住宿报销标准"*20


def test_oversized_question_fails_before_cloud_generation(env,monkeypatch):
    client,session,_=env
    add_doc(session)
    original=rag.providers.get_model
    monkeypatch.setattr(rag.providers,"get_model",lambda db,type,model_id=None: {"id":"llm","modelId":"small-context","context":4096} if type=="LLM" else original(db,type,model_id))
    monkeypatch.setattr(rag.providers,"make_chat",lambda *_args,**_kw:pytest.fail("Over-budget prompt must not call the cloud LLM"))
    response=client.post("/api/chat/stream",json={"kbIds":["kb"],"question":"住宿费用"*450})
    assert "上下文预算" in response.text and "event: done" in response.text
    with session() as db:
        log=list_entities(db,"log")[0].payload
        assert log["status"]=="failed" and log["outputTokens"] is None


@pytest.mark.asyncio
async def test_server_cancel_before_generation_still_sends_done(env,monkeypatch):
    _,session,actor=env
    add_doc(session)
    monkeypatch.setattr(rag.providers,"make_chat",lambda *_args,**_kw:pytest.fail("Cancelled request must not start LLM generation"))
    class Request:
        async def is_disconnected(self):return False
    response=await rag.chat_stream(rag.ChatBody(kbIds=["kb"],question="住宿费用标准"),Request(),actor["value"])
    iterator=response.body_iterator
    assert "event: meta" in await anext(iterator)
    for event in rag._active_chats.values():event.set()
    terminal=await anext(iterator)
    assert "event: done" in terminal and '"status": "cancelled"' in terminal
    with pytest.raises(StopAsyncIteration):await anext(iterator)
    assert not rag._active_chats


def test_frontend_stream_requires_done_and_exports_real_newlines():
    """Execute the exported UI transport guard with controlled SSE event flows."""
    import subprocess
    from pathlib import Path
    frontend=Path(__file__).resolve().parents[2]/"frontend"
    script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const ts=require('./node_modules/typescript');
const source=fs.readFileSync('src/pages/Chat.tsx','utf8');
const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
const mod={exports:{}};
vm.runInNewContext(js,{exports:mod.exports,module:mod,require:()=>({}),AbortController});
const guard=mod.exports.completeChatStream;
(async()=>{
 const controller=new AbortController(),received=[];
 await guard({},(event)=>received.push(event),controller.signal,async(_body,onEvent)=>{
   onEvent('meta',{sessionId:'s'});onEvent('token',{text:'回答'});onEvent('done',{session:{id:'s'}});
 });
 assert.deepEqual(received,['meta','token','done']);
 await assert.rejects(guard({},()=>{},controller.signal,async(_body,onEvent)=>{
   onEvent('meta',{sessionId:'s'});onEvent('token',{text:'部分回答'});
 }),/完成前中断/);
 await assert.rejects(guard({},()=>{},controller.signal,async(_body,onEvent)=>onEvent('done',{})),/完成前中断/);
 const cancelled=new AbortController();cancelled.abort();
 await guard({},()=>{},cancelled.signal,async()=>{});
 // Compile and run the real export handler; JSON tool escaping is irrelevant.
 const start=source.indexOf('function exportConversation()'),end=source.indexOf('\n  const lastUserQuestion',start);
 const handler=source.slice(start,end);let download;
 vm.runInNewContext(handler+';exportConversation();',{
   active:{title:'测试',messages:[{role:'user',content:'问题'},{role:'assistant',content:'答案',sources:[{title:'制度.md',location:'第1页'}]}]},
   notify:()=>{},downloadText:(...args)=>{download=args}
 });
 assert.equal(download[1],'# 测试\n\n## 提问\n\n问题\n\n\n\n## 回答\n\n答案\n\n[1] 制度.md · 第1页');
})().catch(error=>{console.error(error);process.exitCode=1});
'''
    result=subprocess.run(["node","-e",script],cwd=frontend,text=True,capture_output=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr


def test_chat_respects_saved_retrieval_and_explicit_model(env, monkeypatch):
    client, session, _ = env
    add_doc(session)
    with session() as db:
        row = get_entity(db, 'kb', 'kb'); row.payload = {**row.payload, 'mode': 'keyword', 'rerank': False, 'topK': 1, 'minScore': 0}
    original = rag.providers.get_model
    calls = []
    def selected(db, kind, model_id=None):
        calls.append((kind, model_id))
        if kind != 'LLM': raise AssertionError('Keyword retrieval must not call embedding/rerank')
        return original(db, kind, model_id)
    monkeypatch.setattr(rag.providers, 'get_model', selected)
    r = client.post('/api/chat/stream', json={'kbIds':['kb'],'question':'住宿费用标准','modelConfigId':'llm'})
    assert r.status_code == 200 and '住宿费用' in r.text and 'event: done' in r.text
    assert ('LLM', 'llm') in calls
    assert client.get('/api/chat-sessions').json()[0]['modelConfigId'] == 'llm'
