from contextlib import contextmanager
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import ingestion, parsers, providers
from app.db import Base, get_entity, list_entities, put_entity
from app.security import Actor, current_session


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine);factory=sessionmaker(engine,expire_on_commit=False)
    @contextmanager
    def scope():
        with factory() as db:
            try:yield db;db.commit()
            except BaseException:db.rollback();raise
    monkeypatch.setattr(ingestion,"db_session",scope)
    monkeypatch.setattr(ingestion.config,"data_dir",tmp_path)
    queued=[];indexed=[];removed=[]
    monkeypatch.setattr(ingestion,"enqueue",lambda task:queued.append(task))
    def index(db,doc,chunks,kb,version):
        indexed.append((doc["id"],chunks,kb,version))
        return {"tokens":None,"duration":.01,"collection":"test-collection","dimension":4}
    monkeypatch.setattr(ingestion,"_index",index)
    monkeypatch.setattr(ingestion,"_remove_vectors",lambda *args:removed.append(args))
    ingestion._stopping.clear()
    actor={"value":Actor("browser-owner","manager","csrf")}
    app=FastAPI();app.include_router(ingestion.router,prefix="/api")
    app.dependency_overrides[current_session]=lambda:actor["value"]
    with scope() as db:put_entity(db,"setting",{"id":"system","batchLimit":20,"fileLimit":1,"importConcurrency":2})
    with TestClient(app) as client:
        yield client,scope,actor,queued,indexed,removed
    engine.dispose()


def create_kb(client,name="制度"):
    response=client.post("/api/knowledge-bases",json={"name":name,"tags":["制度"],"description":"制度资料"})
    assert response.status_code==201,response.text
    return response.json()["id"]


def upload(client,kb,name="制度.md",data="# 住宿\n\n出差住宿费用标准为每晚500元。".encode(),auto=False,**form):
    response=client.post(f"/api/knowledge-bases/{kb}/documents",files=[("files",(name,data))],data={"autoPublish":str(auto).lower(),"imageUnderstanding":"false",**form})
    return response


def run_upload(env,auto=False):
    client,scope,actor,queued,indexed,removed=env
    kb=create_kb(client);response=upload(client,kb,auto=auto)
    assert response.status_code==202,response.text
    task=response.json()["tasks"][0];ingestion.process_task(task["id"])
    return kb,task


def test_parse_first_without_cloud_credentials(env):
    client,scope,_,_,indexed,_=env
    kb,task=run_upload(env)
    with scope() as db:
        doc=get_entity(db,"doc",task["docId"]).payload
        assert doc["status"]=="review" and "500" in doc["draftChunks"][0]["content"]
        assert not doc["chunks"] and get_entity(db,"task",task["id"]).payload["status"]=="review"
    assert not indexed
    detail=client.get(f"/api/documents/{task['docId']}").json()
    assert "originalPath" not in detail and detail["draftChunks"]
    assert client.get(f"/api/documents/{task['docId']}/original").content.startswith(b"#")


def test_publish_and_draft_edits_keep_old_version_available(env):
    client,scope,_,_,indexed,_=env
    kb,task=run_upload(env)
    response=client.post(f"/api/documents/{task['docId']}/publish")
    assert response.status_code==202
    ingestion.process_task(response.json()["id"])
    original=client.get(f"/api/documents/{task['docId']}").json()
    assert original["status"]=="ready" and original["version"]==1
    chunks=[{**original["chunks"][0],"content":"更新后的标准为600元。"}]
    edited=client.patch(f"/api/documents/{task['docId']}",json={"chunks":chunks}).json()
    assert edited["status"]=="ready" and "500" in edited["chunks"][0]["content"]
    assert "600" in edited["draftChunks"][0]["content"]
    response=client.post(f"/api/documents/{task['docId']}/publish");ingestion.process_task(response.json()["id"])
    published=client.get(f"/api/documents/{task['docId']}").json()
    assert published["version"]==2 and "600" in published["chunks"][0]["content"]
    assert "draftChunks" not in published and len(indexed)==2


def test_upload_rejects_duplicate_invalid_empty_large_and_atomic_batch(env):
    client,scope,*_=env
    kb=create_kb(client)
    first=upload(client,kb);assert first.status_code==202
    assert upload(client,kb,name="另一个名字.md").status_code==409
    assert upload(client,kb,name="制度.exe",data=b"not executable").status_code==422
    assert upload(client,kb,name="空文件.md",data=b"").status_code==422
    assert upload(client,kb,name="超大.md",data=b"x"*(1024*1024+1)).status_code==413
    bad=client.post(f"/api/knowledge-bases/{kb}/documents",files=[("files",("合法.md",b"valid different body")),("files",("bad.exe",b"bad"))])
    assert bad.status_code==422
    with scope() as db:assert len(list_entities(db,"doc",parent_id=kb))==1


def test_cancel_retry_preserves_original_and_restores_task(env):
    client,scope,_,_,indexed,_=env
    kb=create_kb(client);response=upload(client,kb,auto=True);task=response.json()["tasks"][0]
    assert client.post(f"/api/tasks/{task['id']}/cancel").status_code==200
    ingestion.process_task(task["id"]);assert not indexed
    assert client.get(f"/api/documents/{task['docId']}/original").status_code==200
    retry=client.post(f"/api/tasks/{task['id']}/retry");assert retry.status_code==202
    ingestion.process_task(task["id"])
    with scope() as db:
        assert get_entity(db,"doc",task["docId"]).payload["status"]=="ready"
        assert get_entity(db,"task",task["id"]).payload["status"]=="success"


def test_failed_index_keeps_inspectable_draft_and_sanitizes_error(env,monkeypatch):
    client,scope,*_=env
    def unavailable(*args):raise HTTPException(409,"请先配置 Embedding 模型")
    monkeypatch.setattr(ingestion,"_index",unavailable)
    kb,task=run_upload(env,auto=True)
    with scope() as db:
        doc=get_entity(db,"doc",task["docId"]).payload
        assert doc["status"]=="review" and doc["draftChunks"]
        assert get_entity(db,"task",task["id"]).payload["error"]=="请先配置 Embedding 模型"


def test_user_cannot_manage_or_read_unpublished_docs(env):
    client,scope,actor,*_=env
    kb,task=run_upload(env)
    actor["value"]=Actor("visitor","user","csrf")
    assert client.post("/api/knowledge-bases",json={"name":"禁止"}).status_code==403
    assert client.patch(f"/api/documents/{task['docId']}",json={"chunks":[]}).status_code==403
    assert client.get(f"/api/documents/{task['docId']}").status_code==404
    assert client.get(f"/api/documents/{task['docId']}/original").status_code==404


def test_replacement_preserves_published_original_and_version(env):
    client,scope,actor,*_=env
    kb,task=run_upload(env,auto=True);doc_id=task["docId"]
    old=client.get(f"/api/documents/{doc_id}/original").content
    response=upload(client,kb,name="制度新版本.md",data="# 新制度\n住宿600元".encode(),auto=False,replaceDocumentId=doc_id)
    assert response.status_code==202,response.text
    ingestion.process_task(response.json()["tasks"][0]["id"])
    actor["value"]=Actor("visitor","user","csrf")
    assert client.get(f"/api/documents/{doc_id}/original").content==old
    actor["value"]=Actor("manager","manager","csrf")
    pub=client.post(f"/api/documents/{doc_id}/publish");ingestion.process_task(pub.json()["id"])
    assert client.get(f"/api/documents/{doc_id}/original?version=1").content==old
    assert b"600" in client.get(f"/api/documents/{doc_id}/original").content


def test_csv_and_word_preserve_actual_structure(env,tmp_path):
    client,scope,*_=env
    with scope() as db:
        csvfile=tmp_path/"price.csv";csvfile.write_text("项目,金额\n住宿,500\n餐费,100\n",encoding="utf-8")
        result=parsers.parse_file(csvfile,"price.csv","doc",{},db)
        assert result.chunks[0]["kind"]=="table" and "500" in result.chunks[0]["content"]
        assert result.chunks[0]["rowStart"]==2 and result.chunks[0]["rowEnd"]==3
        from docx import Document
        word=Document();word.add_heading("差旅制度",level=1);word.add_paragraph("真实正文，不是示例资料。")
        table=word.add_table(rows=2,cols=2);table.cell(0,0).text="项目";table.cell(0,1).text="标准";table.cell(1,0).text="住宿";table.cell(1,1).text="500"
        docx=tmp_path/"policy.docx";word.save(docx)
        parsed=parsers.parse_file(docx,"policy.docx","doc",{"imageUnderstanding":False},db)
        assert any("真实正文" in c["content"] for c in parsed.chunks)
        assert any(c["kind"]=="table" and "500" in c["content"] for c in parsed.chunks)


def test_docmind_official_sdk_poll_contract_and_vision(env,tmp_path,monkeypatch):
    _,scope,*_=env
    from alibabacloud_docmind_api20220711.client import Client
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    from PIL import Image
    image=tmp_path/"flow.png";Image.new("RGB",(100,100),"white").save(image)
    with scope() as db:put_entity(db,"connection",{"id":"docmind","provider":"阿里云 DocMind","enabled":True,"baseUrl":"docmind-api.cn-hangzhou.aliyuncs.com"})
    monkeypatch.setattr(providers,"credentials",lambda _: {"accessId":"fake-id","accessSecret":"fake-secret"})
    monkeypatch.setattr(Client,"submit_doc_structure_job_advance",lambda self,req,runtime:SimpleNamespace(body=SimpleNamespace(data=SimpleNamespace(id="job1"))))
    # SDK signature accepts request + runtime, not the extra headers used by some other Ali SDKs.
    monkeypatch.setattr(Client,"get_doc_structure_result_with_options",lambda self,req,runtime:SimpleNamespace(body=SimpleNamespace(completed=True,status="Success",data={"layouts":[{"type":"text","text":"审批流程","pageNum":[0],"pos":[{"x":0,"y":0}]}]})))
    monkeypatch.setattr(providers,"get_model",lambda *args:{"id":"vision","modelId":"vision-test"})
    monkeypatch.setattr(providers,"make_chat",lambda *args,**kwargs:FakeListChatModel(responses=["提交 → 审核 → 归档"]))
    with scope() as db:result=parsers.parse_file(image,"flow.png","image-doc",{},db)
    assert any(c["content"]=="审批流程" and c["pages"]==[1] for c in result.chunks)
    assert any(c["kind"]=="image" and c["generated"] for c in result.chunks)
    assert result.assets[0]["mediaType"]=="image/png"
    assert result.usage["visionCalls"][0]["tokens"] is None


def test_embedding_migration_publishes_atomically(env,monkeypatch):
    client,scope,_,queued,indexed,_=env
    kb,task=run_upload(env,auto=True)
    second=upload(client,kb,name="另一个.md",data="# 其他\n另一个知识文件".encode(),auto=True)
    ingestion.process_task(second.json()["tasks"][0]["id"])
    monkeypatch.setattr(providers,"get_model",lambda *args:{"id":"new-embedding","modelId":"new-model"})
    response=client.patch(f"/api/knowledge-bases/{kb}",json={"embeddingConfigId":"new-embedding"})
    assert response.status_code==200,response.text
    migration=response.json()["rebuildTaskIds"];assert len(migration)==2
    with scope() as db:old_versions={d.id:d.payload["publishedIndexVersion"] for d in list_entities(db,"doc",parent_id=kb)}
    ingestion.process_task(migration[0])
    with scope() as db:
        assert get_entity(db,"kb",kb).payload.get("embedding")!="new-model"
        assert {d.id:d.payload["publishedIndexVersion"] for d in list_entities(db,"doc",parent_id=kb)}==old_versions
    ingestion.process_task(migration[1])
    with scope() as db:
        assert get_entity(db,"kb",kb).payload["embedding"]=="new-model"
        assert all(d.payload["publishedIndexVersion"]!=old_versions[d.id] for d in list_entities(db,"doc",parent_id=kb))


def test_pdf_vector_flowchart_is_rendered_for_cloud_vision(env,tmp_path,monkeypatch):
    _,scope,*_=env
    import fitz
    pdf=fitz.open();page=pdf.new_page()
    page.insert_text((30,35),"Flowchart for approval process has meaningful selectable text plus vector shapes.")
    for x in (40,180,320):page.draw_rect(fitz.Rect(x,100,x+100,150))
    page.draw_line(fitz.Point(140,125),fitz.Point(180,125));page.draw_line(fitz.Point(280,125),fitz.Point(320,125))
    path=tmp_path/"vector-flow.pdf";pdf.save(path);pdf.close()
    cloud=[];vision=[]
    monkeypatch.setattr(parsers,"_docmind",lambda *args:cloud.append(True) or {"layouts":[{"type":"text","text":"可选择的真实文字","pageNum":[0]}]})
    def see(data,doc_id,title,result,db,check,location):
        assert data.startswith(b"\x89PNG");vision.append(location)
        result.chunks.append({"id":"figure","title":title,"content":"节点一 → 节点二 → 节点三","location":location,"kind":"image","generated":True})
    monkeypatch.setattr(parsers,"_vision",see)
    with scope() as db:result=parsers.parse_file(path,"vector-flow.pdf","doc",{"imageUnderstanding":True},db)
    assert cloud and vision==["第 1 页 · 页面图像"]
    assert any(c["kind"]=="image" for c in result.chunks)


def test_old_word_cloud_figures_are_saved_and_described(env,tmp_path,monkeypatch):
    _,scope,*_=env
    import httpx
    import respx
    from PIL import Image
    body=BytesIO();Image.new("RGB",(20,20),"white").save(body,"PNG")
    data={"layouts":[{"type":"text","text":"审批制度"},{"type":"figure","markdownContent":"![流程](https://example.oss-cn-hangzhou.aliyuncs.com/flow.png?signature=test)","pageNum":[1]}]}
    doc=tmp_path/"legacy.doc";doc.write_bytes(b"old word test fixture is handled by mocked cloud parser")
    monkeypatch.setattr(parsers,"_docmind",lambda *args:data)
    monkeypatch.setattr(providers,"validate_outbound_url",lambda url:url)
    seen=[]
    def vision(data,doc_id,label,result,db,check,location):
        seen.append(location)
        asset,_=parsers._safe_asset(data,doc_id,label,result)
        result.chunks.append({"id":"image","content":"审批流程描述","title":label,"location":location,"kind":"image","assetId":asset["id"]})
    monkeypatch.setattr(parsers,"_vision",vision)
    with respx.mock() as routes:
        routes.get("https://example.oss-cn-hangzhou.aliyuncs.com/flow.png").mock(return_value=httpx.Response(200,content=body.getvalue()))
        with scope() as db:result=parsers.parse_file(doc,"legacy.doc","old-word",{},db)
    assert seen==["第 2 页"] and result.assets and result.chunks[-1]["kind"]=="image"


def test_markdown_table_preserves_headers_and_rows(env,tmp_path):
    _,scope,*_=env
    path=tmp_path/"table.md";path.write_text("# 制度\n## 费用\n| 项目 | 金额 |\n| --- | --- |\n| 住宿 | 500 |\n| 餐费 | 100 |\n",encoding="utf-8")
    with scope() as db:result=parsers.parse_file(path,"table.md","md-table",{},db)
    table=next(c for c in result.chunks if c["kind"]=="table")
    assert "项目 | 金额" in table["content"] and "住宿 | 500" in table["content"]
    assert table["title"].startswith("制度 / 费用")


def test_retry_reuses_parsed_content_instead_of_repeating_cloud_work(env,monkeypatch):
    client,scope,_,_,indexed,_=env
    real_parse=ingestion.parse_file;calls=[]
    def counted(*args,**kwargs):calls.append(True);return real_parse(*args,**kwargs)
    monkeypatch.setattr(ingestion,"parse_file",counted)
    def fail(*args):raise HTTPException(409,"请配置索引模型")
    monkeypatch.setattr(ingestion,"_index",fail)
    kb,task=run_upload(env,auto=True);assert len(calls)==1
    monkeypatch.setattr(ingestion,"_index",lambda *args:{"tokens":None,"collection":"test"})
    assert client.post(f"/api/tasks/{task['id']}/retry").status_code==202
    ingestion.process_task(task["id"])
    assert len(calls)==1
    with scope() as db:assert get_entity(db,"doc",task["docId"]).payload["status"]=="ready"


def test_cancel_during_index_never_publishes_staging_vectors(env,monkeypatch):
    client,scope,_,_,indexed,removed=env
    kb,task=run_upload(env,auto=True);doc_id=task["docId"]
    with scope() as db:old_version=get_entity(db,"doc",doc_id).payload["publishedIndexVersion"]
    response=client.post(f"/api/documents/{doc_id}/reindex");task_id=response.json()["id"]
    def cancel_inside(db,doc,chunks,kb,version):
        row=get_entity(db,"task",task_id);row.payload={**row.payload,"status":"cancelled","runToken":"cancelled"}
        return {"tokens":None,"collection":"staging"}
    monkeypatch.setattr(ingestion,"_index",cancel_inside)
    ingestion.process_task(task_id)
    with scope() as db:
        doc=get_entity(db,"doc",doc_id).payload
        assert doc["status"]=="ready" and doc["publishedIndexVersion"]==old_version
    assert removed and removed[-1][1]!=old_version


def test_docmind_resumes_checkpoint_and_polls_without_resubmitting(env,tmp_path,monkeypatch):
    _,scope,*_=env
    from alibabacloud_docmind_api20220711.client import Client
    path=tmp_path/"resume.doc";path.write_bytes(b"legacy word")
    with scope() as db:put_entity(db,"connection",{"id":"docmind","provider":"阿里云 DocMind","enabled":True,"baseUrl":"docmind-api.cn-hangzhou.aliyuncs.com"})
    monkeypatch.setattr(providers,"credentials",lambda _:{"accessId":"test","accessSecret":"test"})
    monkeypatch.setattr(Client,"submit_doc_structure_job_advance",lambda *_:pytest.fail("Resume must not submit a second cloud job"))
    queries=[]
    def query(self,request,runtime):
        queries.append(request.id)
        return SimpleNamespace(body=SimpleNamespace(completed=len(queries)>1,status="Success",data={"layouts":[{"type":"text","text":"恢复的真实内容"}]}))
    monkeypatch.setattr(Client,"get_doc_structure_result_with_options",query)
    monkeypatch.setattr(parsers.time,"sleep",lambda _:None)
    result=parsers.ParseResult()
    with scope() as db:data=parsers._docmind(path,db,lambda:None,result,{"docmindJobId":"existing-cloud-job"})
    assert queries==["existing-cloud-job","existing-cloud-job"] and data["layouts"][0]["text"]=="恢复的真实内容"


def test_upload_parent_child_strategy_persists_and_parses(env):
    client,scope,_,_,indexed,_=env
    kb=create_kb(client,name="父子库")
    body="# 总则\n\n"+"\n\n".join(f"## 第{i}章\n\n"+("出差住宿费用标准条款。"*25) for i in range(1,8))
    response=upload(client,kb,name="制度长文.md",data=body.encode(),auto=False,chunkStrategy="parent_child",chunkSize="200",parentSize="800",chunkOverlap="20")
    assert response.status_code==202,response.text
    task=response.json()["tasks"][0]
    with scope() as db:
        opts=get_entity(db,"task",task["id"]).payload.get("options") or {}
        assert opts.get("chunkStrategy")=="parent_child"
        assert opts.get("parentSize")==800
        assert opts.get("chunkOverlap")==20
    ingestion.process_task(task["id"])
    with scope() as db:
        doc=get_entity(db,"doc",task["docId"]).payload
        chunks=doc.get("draftChunks") or []
        parents=[c for c in chunks if c.get("role")=="parent"]
        children=[c for c in chunks if c.get("role")=="child"]
        assert parents and children
        assert all(c.get("parentId") in {p["id"] for p in parents} for c in children)


def test_upload_semantic_strategy_persists_and_degrades_without_llm(env):
    client,scope,_,_,indexed,_=env
    kb=create_kb(client,name="语义库")
    body="# 总则\n\n"+"\n\n".join(f"## 第{i}章\n\n"+("差旅报销条款说明。"*20) for i in range(1,6))
    response=upload(client,kb,name="语义制度.md",data=body.encode(),auto=False,chunkStrategy="semantic",chunkSize="250",chunkOverlap="20")
    assert response.status_code==202,response.text
    task=response.json()["tasks"][0]
    with scope() as db:
        opts=get_entity(db,"task",task["id"]).payload.get("options") or {}
        assert opts.get("chunkStrategy")=="semantic"
    ingestion.process_task(task["id"])
    with scope() as db:
        doc=get_entity(db,"doc",task["docId"]).payload
        chunks=doc.get("draftChunks") or []
        assert chunks
        warnings=doc.get("warnings") or []
        assert any("降级" in w or "LLM" in w for w in warnings)


def test_upload_extracts_document_metadata_by_default(env):
    client, scope, *_ = env
    kb = create_kb(client, name="元数据库")
    body = (
        "---\ndate: 2024-06-01\nversion: V1.0\nauthor: 赵六\nsubject: 财务部\n---\n\n"
        "# 费用报销办法\n\n生效日期：2024年06月01日\n负责人：赵六\n\n"
        "## 住宿\n\n出差住宿标准每晚500元。\n"
    )
    response = upload(
        client,
        kb,
        name="费用报销办法.md",
        data=body.encode(),
        auto=False,
        extractMetadata="true",
        extractMetadataMode="rules",
    )
    assert response.status_code == 202, response.text
    task = response.json()["tasks"][0]
    with scope() as db:
        opts = get_entity(db, "task", task["id"]).payload.get("options") or {}
        assert opts.get("extractMetadata") is True
        assert opts.get("extractMetadataMode") == "rules"
    ingestion.process_task(task["id"])
    with scope() as db:
        doc = get_entity(db, "doc", task["docId"]).payload
        meta = doc.get("metadata") or {}
        assert meta.get("status") == "ok"
        assert meta.get("docDate") == "2024-06-01"
        assert meta.get("keywords")
        assert meta.get("likelyQuestions")
        assert (meta.get("extractor") or {}).get("mode") == "rules"
    detail = client.get(f"/api/documents/{task['docId']}").json()
    assert "metadata" in detail and detail["metadata"]["docDate"] == "2024-06-01"


def test_upload_can_disable_metadata_extraction(env):
    client, scope, *_ = env
    kb = create_kb(client, name="关闭元数据")
    response = upload(
        client,
        kb,
        name="普通.md",
        data="# 标题\n\n正文内容。\n".encode(),
        auto=False,
        extractMetadata="false",
    )
    assert response.status_code == 202, response.text
    task = response.json()["tasks"][0]
    ingestion.process_task(task["id"])
    with scope() as db:
        doc = get_entity(db, "doc", task["docId"]).payload
        # When off, process_task should leave metadata unset or skipped
        meta = doc.get("metadata")
        assert meta is None or meta.get("status") in ("skipped", "empty", None)


def test_patch_and_reextract_metadata_api(env):
    client, scope, *_ = env
    kb, task = run_upload(env, auto=False)
    doc_id = task["docId"]
    patched = client.patch(
        f"/api/documents/{doc_id}/metadata",
        json={"keywords": ["差旅", "住宿"], "subject": "行政部", "docDate": "2024-01-01"},
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["metadata"]["keywords"] == ["差旅", "住宿"]
    assert body["metadata"]["extractor"]["edited"] is True
    extracted = client.post(f"/api/documents/{doc_id}/metadata/extract", json={"mode": "rules"})
    assert extracted.status_code == 200, extracted.text
    assert "metadata" in extracted.json()
