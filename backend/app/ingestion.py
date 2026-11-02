"""Knowledge assets, durable import tasks and staged index publication."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from .config import config
from .db import Entity, db_session, get_entity, list_entities, put_entity
from .parsers import ParseFailure, ParseResult, parse_file
from .metadata_extract import extract_document_metadata, sanitize_metadata_patch, empty_metadata, enhance_chunks_with_keywords, merge_document_metadata, apply_chunk_metadata_drafts
from .security import current_session, require_manager

router=APIRouter()
logger=logging.getLogger(__name__)
ALLOWED={"doc","docx","pdf","md","png","jpg","jpeg","xlsx","xls","csv","txt","json","html","htm","pptx","ipynb","py","js","ts","sql","yaml","yml"}
_executor:ThreadPoolExecutor|None=None
_futures:dict={}
_lock=threading.RLock()
_stopping=threading.Event()


def label():return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%m/%d %H:%M")
def iso():return datetime.now(timezone.utc).isoformat()
def uid():return str(uuid.uuid4())
def clean_doc(data):return {k:v for k,v in data.items() if k not in ("originalPath","sha256","draftSourceSha256","pendingIndex","pendingOriginal","versionHistory")}
def settings(db):
    row=get_entity(db,"setting","system",False)
    return row.payload if row else {"batchLimit":20,"fileLimit":50,"importConcurrency":2}
def error_text(exc):
    if isinstance(exc,HTTPException):return str(exc.detail)[:500]
    if isinstance(exc,ParseFailure):return str(exc)[:500]
    return "处理失败，请检查文件、模型配置及服务端日志后重试"


class LibraryCreate(BaseModel):
    model_config=ConfigDict(extra="forbid")
    id:str|None=None
    name:str=Field(min_length=1,max_length=30)
    description:str=Field(default="",max_length=120)
    category:str="行政制度"
    color:str="violet"
    tags:list[str]=Field(default_factory=list,max_length=10)
    embedding:str=""
    embeddingConfigId:str|None=None

class LibraryPatch(BaseModel):
    model_config=ConfigDict(extra="forbid")
    name:str|None=Field(default=None,min_length=1,max_length=30)
    description:str|None=Field(default=None,max_length=120)
    category:str|None=None
    color:str|None=None
    tags:list[str]|None=None
    embedding:str|None=None
    embeddingConfigId:str|None=None
    topK:int|None=Field(default=None,ge=1,le=20)
    minScore:float|None=Field(default=None,ge=0,le=1)
    rerank:bool|None=None
    mode:Literal['hybrid','semantic','keyword']|None=None

class DocumentPatch(BaseModel):
    model_config=ConfigDict(extra="forbid")
    status:str|None=None
    chunks:list[dict]|None=None

class MetadataPatch(BaseModel):
    model_config=ConfigDict(extra="forbid")
    docDate:str|None=None
    bizVersion:str|None=None
    subject:str|None=None
    ownerPerson:str|None=None
    keywords:list[str]|None=None
    likelyQuestions:list[str]|None=None

class MetadataExtractBody(BaseModel):
    model_config=ConfigDict(extra="forbid")
    mode:Literal["rules","llm","auto"]="auto"
    modelConfigId:str|None=None


def _new_task(db,doc:dict,options:dict,operation="import"):
    task_id=uid()
    # Build/import traceId == task.id; import log reuses the same id for one drill-down chain.
    task={"id":task_id,"traceId":task_id,"kbId":doc["kbId"],"docId":doc["id"],"name":doc["name"],"progress":0,
          "status":"processing","stage":"排队等待处理","autoPublish":bool(options.get("autoPublish",True)),
          "time":label(),"createdAt":iso(),"operation":operation,"options":options,"attempts":0}
    put_entity(db,"task",task,parent_id=doc["kbId"])
    return task


@router.get("/knowledge-bases")
def libraries(actor=Depends(current_session)):
    with db_session() as db:return [r.payload for r in list_entities(db,"kb")]

@router.post("/knowledge-bases",status_code=201)
def create_library(body:LibraryCreate,actor=Depends(require_manager)):
    data=body.model_dump(exclude_none=True);data["id"]=uid();data["name"]=data["name"].strip()
    if not data["name"]:raise HTTPException(422,"知识库名称不能为空")
    with db_session() as db:
        if any(r.payload["name"]==data["name"] for r in list_entities(db,"kb")):raise HTTPException(409,"已有同名知识库")
        if data.get("embeddingConfigId") or data.get("embedding"):
            from .providers import get_model
            model=get_model(db,"Embedding",data.get("embeddingConfigId") or data["embedding"])
            data.update(embedding=model["modelId"],embeddingConfigId=model["id"])
        else:
            from .providers import get_model
            try:model=get_model(db,'Embedding')
            except HTTPException:model=None
            if model:data.update(embedding=model["modelId"],embeddingConfigId=model["id"])
        data.update(status="empty",updatedAt=label(),createdAt=iso())
        put_entity(db,"kb",data)
        return data

@router.get("/knowledge-bases/{kb_id}")
def library(kb_id:str,actor=Depends(current_session)):
    with db_session() as db:return get_entity(db,"kb",kb_id).payload

@router.patch("/knowledge-bases/{kb_id}")
def edit_library(kb_id:str,body:LibraryPatch,actor=Depends(require_manager)):
    changes=body.model_dump(exclude_unset=True,exclude_none=True);queued=[]
    with db_session() as db:
        row=get_entity(db,"kb",kb_id);data=dict(row.payload)
        if "name" in changes:
            changes["name"]=changes["name"].strip()
            if not changes["name"]:raise HTTPException(422,"知识库名称不能为空")
            if any(k.id!=kb_id and k.payload["name"]==changes["name"] for k in list_entities(db,"kb")):raise HTTPException(409,"已有同名知识库")
        target=changes.get("embeddingConfigId") or changes.get("embedding")
        if target:
            from .providers import get_model
            model=get_model(db,"Embedding",target)
            changed=model["id"]!=data.get("embeddingConfigId") or model["modelId"]!=data.get("embedding")
            changes.update(embedding=model["modelId"],embeddingConfigId=model["id"])
            published=[d for d in list_entities(db,"doc",parent_id=kb_id) if d.payload.get("publishedIndexVersion")]
            if changed and published:
                if data.get("pendingEmbedding"):raise HTTPException(409,"此知识库已有模型重建任务，请完成或取消后重试")
                migration=uid();data["pendingEmbedding"]={"modelId":model["modelId"],"configId":model["id"],"migrationId":migration}
                for doc in published:
                    t=_new_task(db,doc.payload,{"autoPublish":True,"migrationId":migration,"targetEmbedding":model["modelId"],"targetEmbeddingConfigId":model["id"]},"reindex")
                    queued.append(t["id"])
                changes.pop("embedding",None);changes.pop("embeddingConfigId",None)
        data.update(changes,updatedAt=label());row.payload=data
    for task_id in queued:enqueue(task_id)
    return {**data,"rebuildTaskIds":queued}

@router.post("/knowledge-bases/{kb_id}/cancel-rebuild")
def cancel_rebuild(kb_id:str,actor=Depends(require_manager)):
    staged=[]
    with db_session() as db:
        row=get_entity(db,"kb",kb_id);data=dict(row.payload);pending=data.pop("pendingEmbedding",None)
        if not pending:return data
        for task in list_entities(db,"task",parent_id=kb_id):
            if task.payload.get("options",{}).get("migrationId")==pending["migrationId"] and task.payload["status"]=="processing":task.payload={**task.payload,"status":"cancelled","stage":"整库重建已取消","runToken":uid()}
        for doc in list_entities(db,"doc",parent_id=kb_id):
            p=dict(doc.payload);index=p.pop("pendingIndex",None)
            if index:staged.append((doc.id,index["indexVersion"]))
            doc.payload=p
        row.payload=data
    for doc_id,version in staged:
        try:_remove_vectors(doc_id,version)
        except Exception:logger.warning("Staged vector cleanup pending for document %s",doc_id)
    return data

@router.delete("/knowledge-bases/{kb_id}")
def delete_library(kb_id:str,actor=Depends(require_manager)):
    ids=[]
    with db_session() as db:
        kb=get_entity(db,"kb",kb_id)
        for row in list_entities(db,"doc",parent_id=kb_id):ids.append(row.id);_delete_doc_rows(db,row)
        for row in list_entities(db,"task",parent_id=kb_id):db.delete(row)
        db.delete(kb)
    for doc_id in ids:
        try:_remove_vectors(doc_id)
        except Exception:logger.warning("Vector deletion deferred; DB tombstone blocks retrieval: %s",doc_id)
    return {"deleted":True}



@router.post("/chunk-preview")
async def chunk_preview(
    files: list[UploadFile] | None = File(None),
    text: str | None = Form(None),
    fileName: str = Form("preview.md"),
    chunkSize: int = Form(600),
    chunkStrategy: str = Form("recursive"),
    parentSize: int = Form(2000),
    chunkOverlap: int | None = Form(None),
    enhanceKeywords: bool = Form(True),
    extractMetadata: bool = Form(False),
    extractMetadataMode: str = Form("auto"),
    actor=Depends(require_manager),
):
    """Parse + split without persisting. Optionally return doc-level metadata suggestions."""
    import tempfile
    from .parsers import normalize_chunk_options

    files = files or []
    if len(files) > 1:
        raise HTTPException(422, "切块预览每次仅支持一个文件")
    _aliases = {"semantic", "llm_semantic", "semantic_llm"}
    if chunkStrategy in _aliases:
        chunkStrategy = "semantic"
    if chunkStrategy not in ("recursive", "parent_child", "semantic"):
        raise HTTPException(422, "切块策略不合法")
    if not 200 <= chunkSize <= 1500:
        raise HTTPException(422, "片段长度不合法")
    if chunkStrategy == "parent_child" and not (chunkSize <= parentSize <= 8000):
        raise HTTPException(422, "父片段长度需不小于子片段且不超过 8000")
    if chunkOverlap is not None and not (0 <= chunkOverlap <= max(0, chunkSize // 2)):
        raise HTTPException(422, "片段重叠长度不合法")
    if extractMetadataMode not in ("off", "rules", "llm", "auto"):
        extractMetadataMode = "auto"
    if not extractMetadata:
        extractMetadataMode = "off"

    raw: bytes | None = None
    name = Path((fileName or "preview.md").replace("\\", "/")).name.replace("\x00", "")[:200] or "preview.md"
    if files:
        upload = files[0]
        name = Path((upload.filename or name).replace("\\", "/")).name.replace("\x00", "")[:200] or name
        raw = await upload.read()
        if not raw:
            raise HTTPException(422, "上传文件为空")
        if len(raw) > 20 * 1024 * 1024:
            raise HTTPException(422, "预览文件过大（上限 20MB）")
    elif text is not None and str(text).strip():
        raw = str(text).encode("utf-8")
        if not name.lower().endswith((".md", ".txt", ".csv", ".html", ".htm", ".json")):
            name = "preview.md"
    else:
        raise HTTPException(422, "请上传文件或提供 text 正文")

    suffix = Path(name).suffix.lower() or ".md"
    if suffix.lstrip(".") not in ALLOWED and suffix != ".md":
        raise HTTPException(422, "暂不支持该文件格式的切块预览")

    options = {
        "chunkSize": chunkSize,
        "chunkStrategy": chunkStrategy,
        "parentSize": parentSize,
        "imageUnderstanding": False,
        "parser": "auto",
        "enhanceKeywords": enhanceKeywords,
    }
    if chunkOverlap is not None:
        options["chunkOverlap"] = chunkOverlap
    normalized = normalize_chunk_options(options)

    with tempfile.TemporaryDirectory(prefix="mideng-chunk-preview-") as tmp:
        path = Path(tmp) / name
        path.write_bytes(raw)
        try:
            with db_session() as db:
                result = parse_file(path, name, "preview", options, db, check=lambda: None)
        except ParseFailure as exc:
            raise HTTPException(422, str(exc)[:500]) from None
        except Exception as exc:
            logger.exception("chunk preview failed")
            raise HTTPException(500, f"切块预览失败：{type(exc).__name__}") from None

    chunks = result.chunks or []
    warnings = list(result.warnings or [])
    metadata = None
    if extractMetadataMode != "off":
        try:
            text_sample = "\n\n".join(f"{c.get('title', '')}\n{c.get('content', '')}" for c in chunks[:40])
            if not text_sample.strip():
                try:
                    text_sample = raw.decode("utf-8", errors="ignore")[:12000]
                except Exception:
                    text_sample = ""
            with db_session() as db:
                metadata, meta_warnings, _usage = extract_document_metadata(
                    name, text_sample, chunks=chunks, db=db, mode=extractMetadataMode
                )
            warnings.extend(meta_warnings)
        except Exception as exc:
            logger.warning("chunk-preview metadata extract failed: %s", type(exc).__name__)
            warnings.append(f"文档元数据预览失败，已跳过：{type(exc).__name__}")
            metadata = empty_metadata(status="failed", mode=extractMetadataMode)

    return {
        "fileName": name,
        "options": {
            **normalized,
            "enhanceKeywords": bool(enhanceKeywords),
            "extractMetadata": bool(extractMetadata),
            "extractMetadataMode": extractMetadataMode,
        },
        "chunkCount": len(chunks),
        "chunks": chunks,
        "warnings": warnings,
        "metadata": metadata,
    }


class ChunkEnhanceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fileName: str = "preview.md"
    chunks: list[dict] = Field(default_factory=list)
    force: bool = True
    skipEdited: bool = True


@router.post("/chunk-preview/enhance")
def chunk_preview_enhance(body: ChunkEnhanceBody, actor=Depends(require_manager)):
    """Re-run rule keyword / light metadata enhance on preview chunks (no persist)."""
    import copy
    chunks = copy.deepcopy(body.chunks or [])
    if len(chunks) > 50000:
        raise HTTPException(422, "片段数量过多")
    warnings = enhance_chunks_with_keywords(
        chunks, body.fileName or "preview.md", force=bool(body.force), skip_edited=bool(body.skipEdited)
    )
    return {"fileName": body.fileName, "chunks": chunks, "chunkCount": len(chunks), "warnings": warnings}


@router.post("/metadata-preview/batch")
async def metadata_preview_batch(
    files: list[UploadFile] = File(...),
    mode: str = Form("auto"),
    actor=Depends(require_manager),
):
    """Batch doc-level metadata preview for import wizard. Heuristic fallback; never hard-fail."""
    import tempfile
    if mode not in ("off", "rules", "llm", "auto"):
        mode = "auto"
    if not files:
        raise HTTPException(422, "请至少上传一个文件")
    if len(files) > 40:
        raise HTTPException(422, "单批预览文件过多")
    items = []
    with tempfile.TemporaryDirectory(prefix="mideng-meta-preview-") as tmp:
        for upload in files:
            name = Path((upload.filename or "file.md").replace("\\", "/")).name.replace("\x00", "")[:200] or "file.md"
            warnings: list[str] = []
            metadata = empty_metadata(status="empty", mode=mode)
            try:
                raw = await upload.read()
                await upload.close()
                if not raw:
                    warnings.append("文件为空")
                    items.append({"name": name, "metadata": metadata, "warnings": warnings})
                    continue
                if len(raw) > 20 * 1024 * 1024:
                    warnings.append("文件过大，已跳过元数据预览")
                    items.append({"name": name, "metadata": metadata, "warnings": warnings})
                    continue
                path = Path(tmp) / name
                path.write_bytes(raw)
                try:
                    text_sample = raw.decode("utf-8")
                except Exception:
                    text_sample = raw.decode("utf-8", errors="ignore")
                # Prefer parse when text formats; otherwise heuristic on raw text
                chunks = None
                suffix = Path(name).suffix.lower().lstrip(".")
                if suffix in ("md", "txt", "csv", "html", "htm", "json") or not suffix:
                    try:
                        with db_session() as db:
                            result = parse_file(
                                path, name, "preview",
                                {"imageUnderstanding": False, "parser": "auto", "enhanceKeywords": False, "chunkSize": 600},
                                db, check=lambda: None,
                            )
                        chunks = result.chunks
                        text_sample = "\n\n".join(f"{c.get('title', '')}\n{c.get('content', '')}" for c in (chunks or [])[:40]) or text_sample
                        warnings.extend(result.warnings or [])
                    except Exception as exc:
                        warnings.append(f"解析降级为原文启发式：{type(exc).__name__}")
                with db_session() as db:
                    metadata, meta_warnings, _usage = extract_document_metadata(
                        name, text_sample[:12000], chunks=chunks, db=db, mode=mode if mode != "off" else "rules"
                    )
                warnings.extend(meta_warnings)
            except Exception as exc:
                logger.warning("metadata-preview batch item failed %s: %s", name, type(exc).__name__)
                warnings.append(f"元数据预览失败：{type(exc).__name__}")
                metadata = empty_metadata(status="failed", mode=mode)
            items.append({"name": name, "metadata": metadata, "warnings": warnings})
    return {"items": items, "count": len(items)}


@router.post("/knowledge-bases/{kb_id}/documents",status_code=202)
async def upload_documents(kb_id:str,files:list[UploadFile]=File(...),autoPublish:bool=Form(True),parser:str=Form("auto"),
                           imageUnderstanding:bool=Form(True),chunkSize:int=Form(600),chunkStrategy:str=Form("recursive"),
                           parentSize:int=Form(2000),chunkOverlap:int|None=Form(None),extractMetadata:bool=Form(True),
                           extractMetadataMode:str=Form("auto"),semanticModelConfigId:str|None=Form(None),
                           replaceDocumentId:str|None=Form(None),
                           draftMetadataByFile:str|None=Form(None),
                           draftChunkMetaByFile:str|None=Form(None),
                           actor=Depends(require_manager)):
    if parser not in ("auto","cloud") or not 200<=chunkSize<=1500:raise HTTPException(422,"解析策略或片段长度不合法")
    _aliases={"semantic","llm_semantic","semantic_llm"}
    if chunkStrategy in _aliases:chunkStrategy="semantic"
    if chunkStrategy not in ("recursive","parent_child","semantic"):raise HTTPException(422,"切块策略不合法")
    if chunkStrategy=="parent_child" and not (chunkSize<=parentSize<=8000):raise HTTPException(422,"父片段长度需不小于子片段且不超过 8000")
    if chunkOverlap is not None and not (0<=chunkOverlap<=max(0,chunkSize//2)):raise HTTPException(422,"片段重叠长度不合法")
    if extractMetadataMode not in ("off","rules","llm","auto"):raise HTTPException(422,"元数据抽取模式不合法")
    if not extractMetadata:extractMetadataMode="off"
    draft_doc_map:dict={}
    draft_chunk_map:dict={}
    if draftMetadataByFile:
        try:
            parsed=json.loads(draftMetadataByFile)
            if isinstance(parsed,dict):draft_doc_map={str(k):v for k,v in parsed.items() if isinstance(v,dict)}
        except Exception:raise HTTPException(422,"draftMetadataByFile 须为 JSON 对象：文件名→元数据") from None
    if draftChunkMetaByFile:
        try:
            parsed=json.loads(draftChunkMetaByFile)
            if isinstance(parsed,dict):draft_chunk_map={str(k):v for k,v in parsed.items() if isinstance(v,list)}
        except Exception:raise HTTPException(422,"draftChunkMetaByFile 须为 JSON 对象：文件名→片段元数据数组") from None
    with db_session() as db:
        kb=get_entity(db,"kb",kb_id).payload
        limits=settings(db)
        if kb.get("pendingEmbedding"):raise HTTPException(409,"整库切换模型期间暂不接受新文档，请等待完成或取消重建")
        if len(files)>limits.get("batchLimit",20):raise HTTPException(422,"超过单批文件数量限制")
        existing=[d.payload for d in list_entities(db,"doc",parent_id=kb_id)]
    # Validate and persist files before creating any database records. Rejected batches leave no partial records.
    prepared=[];saved=[];committed=False
    try:
        for file in files:
            name=Path((file.filename or "").replace("\\","/")).name.replace("\x00","")[:200]
            kind=Path(name).suffix.lower().lstrip(".")
            if kind not in ALLOWED:raise HTTPException(422,f"{name}：暂不支持该文件格式")
            folder=config.data_dir/"originals";folder.mkdir(parents=True,exist_ok=True)
            path=folder/f"{uid()}.{kind}";digest=hashlib.sha256();total=0
            with path.open("wb") as out:
                saved.append(path)
                while block:=await file.read(1024*1024):
                    total+=len(block)
                    if total>limits.get("fileLimit",50)*1024*1024:raise HTTPException(413,f"{name}：超过单文件大小限制")
                    digest.update(block);out.write(block)
            await file.close()
            if not total:raise HTTPException(422,f"{name}：文件为空")
            sha=digest.hexdigest()
            if any(d.get("sha256")==sha and d["id"]!=replaceDocumentId for d in existing) or any(p["sha256"]==sha for p in prepared):raise HTTPException(409,f"{name}：同库中已存在相同内容，请跳过重复文件或明确替换原文档")
            if any(d["name"].casefold()==name.casefold() and d["id"]!=replaceDocumentId for d in existing) or any(p["name"].casefold()==name.casefold() for p in prepared):raise HTTPException(409,f"{name}：同名文档已存在，请明确选择替换")
            prepared.append({"name":name,"kind":kind,"bytes":total,"originalPath":str(path.resolve()),"sha256":sha})
        if replaceDocumentId and len(prepared)!=1:raise HTTPException(422,"替换文档时一次只能上传一份文件")
        tasks=[]
        with db_session() as db:
            get_entity(db,"kb",kb_id)
            for item in prepared:
                original=get_entity(db,"doc",replaceDocumentId,False) if replaceDocumentId else None
                if replaceDocumentId and (not original or original.parent_id!=kb_id):raise HTTPException(404,"待替换文档不存在")
                data=dict(original.payload) if original else {"id":uid(),"kbId":kb_id,"chunks":[],"version":0,"createdAt":iso()}
                if any(t.payload["status"]=="processing" and t.payload["docId"]==data["id"] for t in list_entities(db,"task",parent_id=kb_id)):raise HTTPException(409,"文档正在处理中，请完成或取消现有任务")
                incoming={**item,"size":f"{item['bytes']/1024/1024:.1f} MB" if item['bytes']>=1024*1024 else f"{max(1,item['bytes']//1024)} KB"}
                if data.get("publishedIndexVersion"):data["pendingOriginal"]=incoming
                else:data.update(incoming)
                data.update(updatedAt=label(),error=None)
                if not data.get("publishedIndexVersion"):data["status"]="indexing"
                else:data["draftStatus"]="indexing"
                # Apply import-time document metadata draft (manual wins over later auto fill).
                file_draft=draft_doc_map.get(item["name"]) or draft_doc_map.get(name)
                if file_draft:
                    data["metadata"]=merge_document_metadata(data.get("metadata"),file_draft,mark_edited=True)
                put_entity(db,"doc",data,parent_id=kb_id)
                task_opts={"autoPublish":autoPublish,"parser":parser,"imageUnderstanding":imageUnderstanding,"chunkSize":chunkSize,"chunkStrategy":chunkStrategy,"parentSize":parentSize,
                           "extractMetadata":bool(extractMetadata),"extractMetadataMode":extractMetadataMode}
                if chunkOverlap is not None:task_opts["chunkOverlap"]=chunkOverlap
                if chunkStrategy=="semantic" and semanticModelConfigId:task_opts["semanticModelConfigId"]=semanticModelConfigId
                chunk_draft=draft_chunk_map.get(item["name"]) or draft_chunk_map.get(name)
                if chunk_draft:task_opts["draftChunkMeta"]=chunk_draft
                if file_draft:task_opts["draftMetadata"]=file_draft
                task=_new_task(db,data,task_opts,"import")
                tasks.append(task)
        committed=True
        for task in tasks:enqueue(task["id"])
        return {"tasks":tasks,"accepted":len(tasks)}
    except BaseException:
        if not committed:
            for path in saved:path.unlink(missing_ok=True)
        raise

@router.get("/documents/{doc_id}")
def document(doc_id:str,actor=Depends(current_session)):
    with db_session() as db:
        data=get_entity(db,"doc",doc_id).payload
        if actor.role=="user" and data.get("status")!="ready":raise HTTPException(404,"文档不可用")
        result=clean_doc(data)
        if actor.role=="user":result.pop("draftChunks",None);result.pop("draftStatus",None)
        return result

@router.patch("/documents/{doc_id}/metadata")
def patch_metadata(doc_id:str,body:MetadataPatch,actor=Depends(require_manager)):
    try:patch=sanitize_metadata_patch(body.model_dump(exclude_unset=True))
    except ValueError as exc:raise HTTPException(422,str(exc)) from None
    with db_session() as db:
        row=get_entity(db,"doc",doc_id);data=dict(row.payload)
        meta=dict(data.get("metadata") or empty_metadata(status="empty",mode="manual"))
        meta.update(patch);meta["extractedAt"]=_iso_now_local();meta["status"]="ok";meta.setdefault("extractor",{"mode":"manual"})
        if isinstance(meta.get("extractor"),dict):meta["extractor"]={**meta["extractor"],"edited":True}
        data["metadata"]=meta;data["updatedAt"]=label();row.payload=data
        return clean_doc(data)

@router.post("/documents/{doc_id}/metadata/extract")
def extract_metadata(doc_id:str,body:MetadataExtractBody|None=None,actor=Depends(require_manager)):
    body=body or MetadataExtractBody()
    with db_session() as db:
        row=get_entity(db,"doc",doc_id);data=dict(row.payload)
        chunks=data.get("draftChunks") or data.get("chunks") or []
        text_sample="\n\n".join(f"{c.get('title','')}\n{c.get('content','')}" for c in chunks[:40])
        meta,warnings,usage=extract_document_metadata(data.get("name") or "",text_sample,chunks=chunks,db=db,mode=body.mode,model_config_id=body.modelConfigId)
        warn_list=list(data.get("warnings") or [])
        for w in warnings:
            if w not in warn_list:warn_list.append(w)
        data["metadata"]=meta;data["warnings"]=warn_list;data["updatedAt"]=label();row.payload=data
        return {"metadata":meta,"warnings":warnings,"usage":usage,"document":clean_doc(data)}

def _iso_now_local():
    return datetime.now(timezone.utc).isoformat()

@router.patch("/documents/{doc_id}")
def edit_document(doc_id:str,body:DocumentPatch,actor=Depends(require_manager)):
    with db_session() as db:
        row=get_entity(db,"doc",doc_id);data=dict(row.payload)
        kb=get_entity(db,"kb",data["kbId"]).payload
        if kb.get("pendingEmbedding"):raise HTTPException(409,"模型重建期间不能修订文档，请完成或取消重建")
        if body.status is not None:
            if body.status not in ("ready","disabled"):raise HTTPException(422,"只能启用或停用已发布文档")
            if not data.get("publishedIndexVersion"):raise HTTPException(409,"文档尚未建立可用索引，请先发布")
            data["status"]=body.status
        if body.chunks is not None:
            if not body.chunks or len(body.chunks)>50000:raise HTTPException(422,"知识片段不能为空或超过数量限制")
            chunks=[]
            for c in body.chunks:
                if not isinstance(c.get("content"),str) or not c["content"].strip() or len(c["content"])>100000:raise HTTPException(422,"片段内容不能为空或超过长度限制")
                if c.get("kind","text") not in ("text","table","image"):raise HTTPException(422,"片段类型不合法")
                if c.get("id") is not None and (not isinstance(c["id"],str) or not c["id"] or len(c["id"])>100):raise HTTPException(422,"片段 ID 不合法")
                if not all(isinstance(c.get(key,""),str) and len(c.get(key,""))<=1000 for key in ("title","location")):raise HTTPException(422,"片段标题或位置不合法")
                c=dict(c);c.pop("assetUrl",None)
                if c.get("assetId"):
                    asset=get_entity(db,"asset",str(c["assetId"]),False)
                    if not asset or asset.parent_id!=doc_id:raise HTTPException(422,"图片资源不属于此文档")
                    c["assetUrl"]=f"/api/assets/{asset.id}"
                chunks.append({k:v for k,v in {**c,"id":c.get("id") or uid(),"edited":True}.items() if k in ("id","title","content","location","kind","edited","page","pages","bbox","assetId","assetUrl","generated","sheet","rowStart","rowEnd","parentId","role","parentExcerpt","splitter","metadata")})
            if len({c["id"] for c in chunks})!=len(chunks):raise HTTPException(422,"知识片段 ID 不能重复")
            data["draftChunks"]=chunks;data["draftStatus"]="review"
            if not data.get("publishedIndexVersion"):data["status"]="review"
        data["updatedAt"]=label();row.payload=data
        return clean_doc(data)

def _enqueue_document(doc_id,operation):
    with db_session() as db:
        row=get_entity(db,"doc",doc_id);doc=dict(row.payload);kb=get_entity(db,"kb",doc["kbId"]).payload
        if kb.get("pendingEmbedding"):raise HTTPException(409,"整库重建中，请在任务中心操作")
        if any(t.payload["docId"]==doc_id and t.payload["status"]=="processing" for t in list_entities(db,"task",parent_id=doc["kbId"])):raise HTTPException(409,"此文档已有处理任务")
        if operation=="publish" and not doc.get("draftChunks"):raise HTTPException(409,"没有可发布的待检查片段")
        task=_new_task(db,doc,{"autoPublish":True},operation)
    enqueue(task["id"]);return task

@router.post("/documents/{doc_id}/publish",status_code=202)
def publish_document(doc_id:str,actor=Depends(require_manager)):return _enqueue_document(doc_id,"publish")
@router.post("/documents/{doc_id}/reindex",status_code=202)
def reindex_document(doc_id:str,actor=Depends(require_manager)):return _enqueue_document(doc_id,"reindex")

def _delete_doc_rows(db,row):
    data=row.payload
    for task in list_entities(db,"task",parent_id=data["kbId"]):
        if task.payload["docId"]==row.id:task.payload={**task.payload,"status":"cancelled","stage":"文档已删除","runToken":uid()}
    for asset in list_entities(db,"asset",parent_id=row.id):
        Path(asset.payload["path"]).unlink(missing_ok=True);db.delete(asset)
    originals=[data,data.get("pendingOriginal",{}),*data.get("versionHistory",[])]
    for original in originals:
        if original.get("originalPath"):Path(original["originalPath"]).unlink(missing_ok=True)
    for parsed in (config.data_dir/"parsed").glob(f"{row.id}-*.json"):parsed.unlink(missing_ok=True)
    db.delete(row)

@router.delete("/documents/{doc_id}")
def delete_document(doc_id:str,actor=Depends(require_manager)):
    with db_session() as db:
        row=get_entity(db,"doc",doc_id)
        if get_entity(db,"kb",row.payload["kbId"]).payload.get("pendingEmbedding"):raise HTTPException(409,"整库重建期间请先取消重建再删除文档")
        _delete_doc_rows(db,row)
    try:_remove_vectors(doc_id)
    except Exception:logger.warning("Vector deletion deferred for %s; DB blocks retrieval",doc_id)
    return {"deleted":True}

@router.get("/documents/{doc_id}/original")
def original_file(doc_id:str,version:int|None=None,actor=Depends(current_session)):
    with db_session() as db:
        doc=get_entity(db,"doc",doc_id).payload
        if actor.role=="user" and doc.get("status")!="ready":raise HTTPException(404,"文档不可用")
        selected=doc
        if version is not None and version!=doc.get("version"):
            selected=next((v for v in doc.get("versionHistory",[]) if v.get("version")==version),None)
            if not selected:raise HTTPException(404,"此版本原件不存在")
        elif version is None and actor.role!="user" and doc.get("pendingOriginal"):selected=doc["pendingOriginal"]
        path=Path(selected["originalPath"]).resolve()
        if not path.is_relative_to(config.data_dir.resolve()) or not path.is_file():raise HTTPException(404,"原文件不存在")
        return FileResponse(path,filename=selected["name"],content_disposition_type="inline" if selected["kind"] in ("pdf","png","jpg","jpeg") else "attachment")

@router.get("/assets/{asset_id}")
def asset_file(asset_id:str,actor=Depends(current_session)):
    with db_session() as db:
        asset=get_entity(db,"asset",asset_id).payload;doc=get_entity(db,"doc",asset["docId"]).payload
        if actor.role=="user" and doc.get("status")!="ready":raise HTTPException(404,"资源不可用")
        if actor.role=="user" and not asset.get("published") and not any(c.get("assetId")==asset_id for c in doc.get("chunks",[])):raise HTTPException(404,"资源尚未发布")
        path=Path(asset["path"]).resolve()
        if not path.is_relative_to(config.data_dir.resolve()) or not path.is_file():raise HTTPException(404,"资源不存在")
        return FileResponse(path,media_type=asset.get("mediaType","application/octet-stream"),headers={"X-Content-Type-Options":"nosniff"})

@router.post("/tasks/{task_id}/retry",status_code=202)
def retry_task(task_id:str,actor=Depends(require_manager)):
    with db_session() as db:
        row=db.query(Entity).filter(Entity.kind=="task",Entity.id==task_id).with_for_update().one_or_none()
        if row is None:raise HTTPException(404,"任务不存在")
        data=dict(row.payload)
        if data["status"] not in ("failed","cancelled"):raise HTTPException(409,"只有失败或取消的任务可以重试")
        get_entity(db,"doc",data["docId"])
        data.update(status="processing",progress=0,stage="等待重试",error=None,runToken=uid(),time=label());row.payload=data
    enqueue(task_id);return data

@router.post("/tasks/{task_id}/cancel")
def cancel_task(task_id:str,actor=Depends(require_manager)):
    with db_session() as db:
        row=db.query(Entity).filter(Entity.kind=="task",Entity.id==task_id).with_for_update().one_or_none()
        if row is None:raise HTTPException(404,"任务不存在")
        data=dict(row.payload)
        if data["status"]!="processing":raise HTTPException(409,"任务已结束，无需取消")
        data.update(status="cancelled",stage="已停止后续处理",runToken=uid());row.payload=data
        doc=get_entity(db,"doc",data["docId"],False)
        if doc:
            p=dict(doc.payload);p["draftStatus"]="cancelled"
            if not p.get("publishedIndexVersion"):p["status"]="review" if p.get("draftChunks") else "failed"
            doc.payload=p
        return data


class JobCancelled(Exception):pass

def _check(task_id,token):
    if _stopping.is_set():raise JobCancelled()
    with db_session() as db:
        row=get_entity(db,"task",task_id,False)
        if not row or row.payload.get("status")!="processing" or row.payload.get("runToken")!=token:raise JobCancelled()
        if not get_entity(db,"doc",row.payload["docId"],False):raise JobCancelled()

def _stage(task_id,token,progress,stage):
    _check(task_id,token)
    with db_session() as db:
        row=get_entity(db,"task",task_id);row.payload={**row.payload,"progress":progress,"stage":stage}

def _index(db,doc,chunks,kb,index_version):
    from .rag import index_document
    return index_document(db,doc,chunks,kb,index_version)

def _remove_vectors(doc_id,index_version=None):
    from .rag import remove_document_vectors
    return remove_document_vectors(doc_id,index_version)

def _log_import(db,task,doc,started,status,message,usage,steps):
    calls=usage.get("visionCalls",[]);numbers=[c.get("tokens") for c in calls]
    embed_tokens=usage.get("embeddingTokens")
    measured=numbers+([embed_tokens] if 'embeddingTokens' in usage else [])
    tokens=sum(measured) if measured and all(type(n) is int for n in measured) else None
    kb=get_entity(db,"kb",doc["kbId"],False)
    trace_id=task.get("traceId") or task["id"]
    put_entity(db,"log",{"id":trace_id,"traceId":trace_id,"question":f"导入文档：{doc['name']}","answer":message,"model":" / ".join(dict.fromkeys(s['model'] for s in steps if s.get('model'))) or '尚未调用模型',
        "kbName":kb.payload["name"] if kb else "已删除知识库","status":status,"tokens":tokens,"inputTokens":None,"outputTokens":None,
        "duration":round(time.monotonic()-started,3),"firstToken":None,"time":label(),"createdAt":iso(),"role":"知识库管理人员",
        "source":"import","steps":steps,"usage":usage,"taskId":task["id"],"documentId":doc["id"]})


def process_task(task_id:str):
    """DB status is authoritative. Stale/duplicate runs cannot publish a new index."""
    started=time.monotonic();token=uid();index_version=uid();usage={};steps=[];doc={};task={};staged=False
    try:
        with db_session() as db:
            row=get_entity(db,"task",task_id,False)
            if not row or row.payload.get("status")!="processing":return
            task={**row.payload,"runToken":token,"attempts":row.payload.get("attempts",0)+1,"stage":"读取文档","progress":5,"error":None};row.payload=task
            doc=dict(get_entity(db,"doc",task["docId"]).payload);kb=dict(get_entity(db,"kb",doc["kbId"]).payload)
        options=dict(task.get("options",{}));source=doc.get("pendingOriginal") or doc
        def checkpoint(job_id):
            _check(task_id,token)
            with db_session() as db:
                row=get_entity(db,"task",task_id);opts=dict(row.payload.get("options",{}))
                if job_id:opts["docmindJobId"]=job_id
                else:opts.pop("docmindJobId",None)
                row.payload={**row.payload,"options":opts}
        options["_checkpoint"]=checkpoint
        reusable=doc.get("draftChunks") and doc.get("draftSourceSha256")==source.get("sha256")
        if (task.get("operation") in ("publish","reindex") and (doc.get("draftChunks") or doc.get("chunks"))) or reusable:
            result=ParseResult(chunks=doc.get("draftChunks") or doc["chunks"],warnings=doc.get("warnings",[]))
        else:
            _stage(task_id,token,15,"解析文字、表格和图片")
            parse_start=time.monotonic()
            with db_session() as db:
                result=parse_file(Path(source["originalPath"]),source["name"],doc["id"],options,db,lambda:_check(task_id,token))
            usage.update(result.usage);steps.append({"name":"文档解析与图像理解","model":"DocMind / 本地结构读取 / 视觉模型","duration":round(time.monotonic()-parse_start,3),"tokens":None,"status":"成功"})
        _check(task_id,token)
        with db_session() as db:
            row=get_entity(db,"doc",doc["id"]);p=dict(row.payload);p.update(draftChunks=result.chunks,draftStatus="review",draftSourceSha256=source.get("sha256"),warnings=result.warnings,updatedAt=label())
            if not p.get("publishedIndexVersion"):p["status"]="review"
            row.payload=p
            for asset in result.assets:put_entity(db,"asset",asset,parent_id=doc["id"])
            connection=get_entity(db,"connection",result.usage.get("docmindConnectionId",""),False)
            if connection:connection.payload={**connection.payload,"status":"connected"}
            if result.raw is not None:
                folder=config.data_dir/"parsed";folder.mkdir(parents=True,exist_ok=True)
                (folder/f"{doc['id']}-{token}.json").write_text(json.dumps(result.raw,ensure_ascii=False),encoding="utf-8")
        # Apply import-time chunk metadata drafts (manual) onto parsed chunks.
        draft_chunk_meta=options.get("draftChunkMeta")
        if draft_chunk_meta:
            merge_warnings=apply_chunk_metadata_drafts(result.chunks or [], draft_chunk_meta if isinstance(draft_chunk_meta, list) else [])
            if merge_warnings:
                result.warnings=list(result.warnings or [])+merge_warnings
            with db_session() as db:
                row=get_entity(db,"doc",doc["id"]);p=dict(row.payload)
                p["draftChunks"]=result.chunks;p["warnings"]=list(result.warnings or []);p["updatedAt"]=label();row.payload=p
                doc=p

        # Metadata extraction (non-blocking): heuristics first; optional LLM when configured.
        # Skip re-extract on publish/reindex when usable metadata already exists (preserve manual edits).
        # When import carried a manual draft (extractor.edited), only fill missing fields.
        meta_mode=str(options.get("extractMetadataMode") or ("auto" if options.get("extractMetadata",True) else "off"))
        if options.get("extractMetadata") is False:meta_mode="off"
        existing_meta=doc.get("metadata") or {}
        manual_draft=bool((existing_meta.get("extractor") or {}).get("edited")) or bool(options.get("draftMetadata"))
        if task.get("operation") in ("publish","reindex") and existing_meta.get("status") in ("ok","partial") and (
            existing_meta.get("keywords") or existing_meta.get("docDate") or existing_meta.get("bizVersion")
            or existing_meta.get("subject") or existing_meta.get("ownerPerson") or existing_meta.get("likelyQuestions")
        ):
            meta_mode="off"
        if meta_mode!="off":
            _stage(task_id,token,45,"抽取文档元数据")
            meta_start=time.monotonic()
            try:
                text_sample="\n\n".join(f"{c.get('title','')}\n{c.get('content','')}" for c in (result.chunks or [])[:40])
                with db_session() as db:
                    meta,meta_warnings,meta_usage=extract_document_metadata(
                        source.get("name") or doc.get("name") or "",
                        text_sample,
                        chunks=result.chunks,
                        db=db,
                        mode=meta_mode,
                        model_config_id=options.get("extractModelConfigId"),
                    )
                if manual_draft:
                    seed = existing_meta if (existing_meta.get("extractor") or {}).get("edited") else (options.get("draftMetadata") or existing_meta)
                    auto_meta = meta
                    # Manual draft wins; auto only fills fields the draft left empty.
                    meta = merge_document_metadata(seed if isinstance(seed, dict) else {}, None, mark_edited=True)
                    meta = merge_document_metadata(meta, auto_meta, fill_missing_only=True, mark_edited=True)
                if meta_usage:usage.update({k:v for k,v in meta_usage.items() if v is not None})
                warn_list=list(result.warnings or [])
                warn_list.extend(meta_warnings)
                result.warnings=warn_list
                with db_session() as db:
                    row=get_entity(db,"doc",doc["id"]);p=dict(row.payload)
                    p["metadata"]=meta;p["warnings"]=warn_list;p["updatedAt"]=label();row.payload=p
                    doc=p
                steps.append({"name":"元数据抽取","model":(meta.get("extractor") or {}).get("mode","rules"),"duration":round(time.monotonic()-meta_start,3),"tokens":meta_usage.get("llmTokens"),"status":"成功" if meta.get("status") in ("ok","partial","empty") else "降级"})
            except Exception as meta_exc:
                logger.warning("Metadata extraction failed for %s: %s",doc.get("id"),type(meta_exc).__name__)
                warn_list=list(result.warnings or [])+["元数据抽取失败，已跳过，不影响入库"]
                result.warnings=warn_list
                with db_session() as db:
                    row=get_entity(db,"doc",doc["id"]);p=dict(row.payload)
                    if not ((p.get("metadata") or {}).get("extractor") or {}).get("edited"):
                        p["metadata"]=empty_metadata(status="failed",mode=meta_mode)
                    p["warnings"]=warn_list;p["updatedAt"]=label();row.payload=p
                    doc=p
                steps.append({"name":"元数据抽取","model":meta_mode,"duration":round(time.monotonic()-meta_start,3),"tokens":None,"status":"失败已跳过"})
        elif manual_draft and existing_meta:
            # No auto extract but keep draft already written at upload time
            pass
        if not task.get("autoPublish",True):
            with db_session() as db:
                row=get_entity(db,"task",task_id)
                if row.payload.get("runToken")!=token or row.payload["status"]!="processing":raise JobCancelled()
                row.payload={**row.payload,"status":"review","progress":100,"stage":"解析完成，等待检查后发布"}
                _log_import(db,task,doc,started,"success","解析完成，等待检查后发布",usage,steps)
            return
        _stage(task_id,token,70,"生成向量与知识索引")
        with db_session() as db:
            target=dict(get_entity(db,"kb",doc["kbId"]).payload)
            doc=dict(get_entity(db,"doc",doc["id"]).payload)
            if options.get("migrationId"):
                pending=target.get("pendingEmbedding",{})
                if pending.get("migrationId")!=options["migrationId"]:raise JobCancelled()
                target.update(embedding=options["targetEmbedding"],embeddingConfigId=options["targetEmbeddingConfigId"])
            index_start=time.monotonic();indexed=_index(db,doc,result.chunks,target,index_version);staged=True
            usage["embeddingTokens"]=indexed.get("tokens");steps.append({"name":"向量索引","model":target.get("embedding","未配置"),"duration":round(time.monotonic()-index_start,3),"tokens":indexed.get("tokens"),"status":"成功"})
        _check(task_id,token)
        with db_session() as db:
            tr=db.query(Entity).filter(Entity.kind=="task",Entity.id==task_id).with_for_update().one_or_none()
            if not tr or tr.payload.get("runToken")!=token or tr.payload["status"]!="processing":raise JobCancelled()
            kbrow=db.query(Entity).filter(Entity.kind=="kb",Entity.id==doc["kbId"]).with_for_update().one_or_none()
            if not kbrow:raise JobCancelled()
            row=get_entity(db,"doc",doc["id"]);p=dict(row.payload);kbdata=dict(kbrow.payload)
            migration=options.get("migrationId")
            publication={"chunks":result.chunks,"indexVersion":index_version,"collection":indexed.get("collection"),"embeddingConfigId":target.get("embeddingConfigId"),"migrationId":migration}
            if migration:
                if kbdata.get("pendingEmbedding",{}).get("migrationId")!=migration:raise JobCancelled()
                p["pendingIndex"]=publication;row.payload=p;db.flush()
                published=list_entities(db,"doc",parent_id=doc["kbId"])
                active=[d for d in published if d.payload.get("publishedIndexVersion")]
                if all(d.payload.get("pendingIndex",{}).get("migrationId")==migration for d in active):
                    for d in active:_publish_row(d,d.payload["pendingIndex"])
                    pending=kbdata.pop("pendingEmbedding");kbdata.update(embedding=pending["modelId"],embeddingConfigId=pending["configId"],updatedAt=label());kbrow.payload=kbdata
            else:
                if kbdata.get("pendingEmbedding"):raise JobCancelled()
                _publish_row(row,publication)
                kbrow.payload={**kbdata,"status":"ready","updatedAt":label()}
            tr=get_entity(db,"task",task_id)
            if tr.payload.get("runToken")!=token or tr.payload["status"]!="processing":raise JobCancelled()
            tr.payload={**tr.payload,"status":"success","progress":100,"stage":"索引完成" if not migration or not kbrow.payload.get("pendingEmbedding") else "新索引已就绪，等待整库切换","completedAt":iso()}
            _log_import(db,task,doc,started,"success","知识索引构建完成",usage,steps)
    except JobCancelled:
        if staged:
            try:_remove_vectors(doc.get("id",""),index_version)
            except Exception:logger.warning("Orphan staged index will remain invisible: %s",task_id)
    except Exception as exc:
        message=error_text(exc)
        logger.warning("Import task %s failed (%s)",task_id,type(exc).__name__)
        with db_session() as db:
            row=get_entity(db,"task",task_id,False)
            if row and row.payload.get("runToken")==token and row.payload.get("status")=="processing":
                row.payload={**row.payload,"status":"failed","stage":"处理失败","error":message}
                d=get_entity(db,"doc",row.payload["docId"],False)
                if d:
                    p=dict(d.payload);p.update(error=message,draftStatus="failed")
                    if not p.get("publishedIndexVersion"):p["status"]="review" if p.get("draftChunks") else "failed"
                    d.payload=p
                    _log_import(db,task,d.payload,started,"failed",message,usage,steps)
        if staged:
            try:_remove_vectors(doc.get("id",""),index_version)
            except Exception:pass


def _publish_row(row,publication):
    p=dict(row.payload);was_disabled=p.get("status")=="disabled"
    if p.get("publishedIndexVersion"):
        history=list(p.get("versionHistory",[]));history.append({k:p.get(k) for k in ("version","originalPath","name","kind")});p["versionHistory"]=history
    replacement=p.pop("pendingOriginal",None)
    if replacement:p.update(replacement)
    from sqlalchemy.orm import object_session
    db=object_session(row)
    for c in publication["chunks"]:
        if c.get("assetId"):
            asset=get_entity(db,"asset",c["assetId"],False)
            if asset:asset.payload={**asset.payload,"published":True}
    p.update(chunks=publication["chunks"],publishedIndexVersion=publication["indexVersion"],publishedCollection=publication.get("collection"),
             publishedEmbeddingConfigId=publication.get("embeddingConfigId"),version=p.get("version",0)+1,status="disabled" if was_disabled else "ready",updatedAt=label(),error=None)
    p.pop("draftChunks",None);p.pop("draftStatus",None);p.pop("draftSourceSha256",None);p.pop("pendingIndex",None);row.payload=p


def enqueue(task_id:str):
    global _executor
    if config.task_mode=="celery":
        if not config.qdrant_url:raise HTTPException(503,"Celery 模式必须配置独立 Qdrant 服务")
        from .worker import celery_app
        try:celery_app.send_task("knowledge.process",args=[task_id],retry=False)
        except Exception:
            with db_session() as db:
                row=get_entity(db,"task",task_id,False)
                if row:row.payload={**row.payload,"status":"failed","stage":"队列不可用","error":"无法连接任务队列，请检查 Redis 和 Worker 后重试"}
            raise HTTPException(503,"无法连接任务队列，文档已保存，可在任务中心重试") from None
        return
    with _lock:
        if task_id in _futures and not _futures[task_id].done():
            _futures[task_id].add_done_callback(lambda _future:_resume_if_waiting(task_id))
            return
        if _executor is None:
            _stopping.clear()
            with db_session() as db:workers=max(1,min(8,int(settings(db).get("importConcurrency",2))))
            _executor=ThreadPoolExecutor(max_workers=workers,thread_name_prefix="knowledge-import")
        _futures[task_id]=_executor.submit(process_task,task_id)


def _resume_if_waiting(task_id):
    if _stopping.is_set():return
    with db_session() as db:
        row=get_entity(db,"task",task_id,False)
        waiting=row and row.payload.get("status")=="processing"
    if waiting:enqueue(task_id)


def recover_jobs():
    _stopping.clear()
    with db_session() as db:ids=[r.id for r in list_entities(db,"task") if r.payload.get("status")=="processing"]
    for task_id in ids:
        try:enqueue(task_id)
        except Exception:logger.warning("Could not schedule persisted task %s",task_id)


def shutdown_jobs():
    global _executor
    _stopping.set()
    if _executor:_executor.shutdown(wait=False,cancel_futures=True);_executor=None
