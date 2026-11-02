from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict
from .config import config
from .db import db_session,get_entity,put_entity,list_entities,Entity
from .security import Actor,current_session,require_admin,require_manager

router=APIRouter()
DEFAULT_SETTINGS={"id":"system","retention":30,"batchLimit":20,"fileLimit":50,"chatConcurrency":10,"importConcurrency":2,"rerankRequired":False}
def initialize_defaults():
    with db_session() as db:
        if not get_entity(db,"setting","system",False):put_entity(db,"setting",DEFAULT_SETTINGS)
        # Connection templates contain no credentials or alleged test results.
        templates=[("ali","阿里云百炼","https://dashscope.aliyuncs.com/compatible-mode/v1","OpenAI 兼容 + DashScope"),("openrouter","OpenRouter","https://openrouter.ai/api/v1","OpenAI 兼容"),("aihubmix","AIHubMix","https://aihubmix.com/v1","OpenAI 兼容"),("deepseek","DeepSeek","https://api.deepseek.com/v1","OpenAI 兼容"),("docmind","阿里云 DocMind","docmind-api.cn-hangzhou.aliyuncs.com","阿里云 SDK · AccessKey")]
        if not list_entities(db,"connection"):
            for id,provider,url,protocol in templates:
                put_entity(db,"connection",{"id":id,"name":provider,"provider":provider,"baseUrl":url,"protocol":protocol,"region":"中国大陆","enabled":True,"status":"untested","keyConfigured":False})

def public_payload(kind,data,manager=True):
    hidden={"originalPath","path","filePath","encrypted","secret","apiKey","accessSecret","accessId","owner","publishedIndexVersion","vectorCollection","sha256","draftSourceSha256","storagePath","pendingIndex","pendingOriginal","versionHistory"}
    out={k:v for k,v in data.items() if k not in hidden and not k.startswith("_")}
    if kind=="doc" and not manager:out.pop("draftChunks",None)
    return out

@router.get("/state")
def state(actor:Actor=Depends(current_session)):
    manager=actor.role in ("manager","admin")
    with db_session() as db:
        settings=dict(get_entity(db,"setting","system").payload);settings.pop("id",None)
        cutoff=datetime.now(timezone.utc)-timedelta(days=settings["retention"])
        db.query(Entity).filter(Entity.kind=="log",Entity.created_at<cutoff).delete(synchronize_session=False)
        docs=[]
        for row in list_entities(db,"doc"):
            if not manager and row.payload.get("status")!="ready":continue
            doc=public_payload("doc",row.payload,manager)
            doc["chunkCount"]=len(doc.get("chunks",[]))
            doc["hasDraft"]=bool(doc.get("draftChunks"))
            doc["chunks"]=[]
            doc.pop("draftChunks",None)
            docs.append(doc)
        kbs=[]
        for row in list_entities(db,"kb"):
            k=public_payload("kb",row.payload)
            owned=[d for d in docs if d.get("kbId")==row.id]
            k["status"]="ready" if any(d.get("status")=="ready" for d in owned) else "indexing" if any(d.get("status")=="indexing" for d in owned) else "empty"
            kbs.append(k)
        logs=[public_payload("log",r.payload) for r in list_entities(db,"log") if actor.role=="admin" or actor.role=="manager" and r.payload.get("source")!="chat"][:500]
        models=[public_payload("model",r.payload) for r in list_entities(db,"model")]
        connections=[public_payload("connection",r.payload) for r in list_entities(db,"connection")]
        if actor.role!="admin":
            connections=[{k:v for k,v in c.items() if k in ("id","provider","enabled","status")} for c in connections]
        return {"role":actor.role,"kbs":kbs,"docs":docs,"tasks":[public_payload("task",r.payload) for r in list_entities(db,"task")] if manager else [],"logs":logs,"models":models,"connections":connections,"sessions":[public_payload("chat",r.payload) for r in list_entities(db,"chat",owner=actor.owner)],"settings":settings,"runtime":{"database":"postgresql" if config.sql_url.startswith("postgres") else "sqlite-development","vectors":"qdrant-server" if config.qdrant_url else "qdrant-local-development","tasks":config.task_mode,"cloudConfigured":any(c.get("status")=="connected" for c in connections)}}

class SettingsBody(BaseModel):
    model_config=ConfigDict(extra="forbid")
    retention:int=Field(default=30,ge=1,le=365)
    batchLimit:int=Field(default=20,ge=1,le=100)
    fileLimit:int=Field(default=50,ge=1,le=500)
    chatConcurrency:int=Field(default=10,ge=1,le=50)
    importConcurrency:int=Field(default=2,ge=1,le=8)
    rerankRequired:bool=False

@router.patch("/settings")
def save_settings(body:SettingsBody,actor:Actor=Depends(require_admin)):
    with db_session() as db:put_entity(db,"setting",{"id":"system",**body.model_dump()})
    return body.model_dump()

@router.get("/settings")
def get_settings(actor:Actor=Depends(require_admin)):
    with db_session() as db:return get_entity(db,"setting","system").payload

@router.get("/logs")
def logs(q:str="",status:str="",source:str="",limit:int=Query(100,ge=1,le=2000),offset:int=Query(0,ge=0),actor:Actor=Depends(require_manager)):
    with db_session() as db:
        rows=[r.payload for r in list_entities(db,"log") if actor.role=="admin" or r.payload.get("source")!="chat"]
        rows=[r for r in rows if (not q or q.lower() in str((r.get("question"),r.get("kbName"),r.get("id"))).lower()) and (not status or r.get("status")==status) and (not source or r.get("source")==source)]
        return {"items":rows[offset:offset+limit],"total":len(rows)}

@router.get("/configuration-export")
def configuration_export(actor:Actor=Depends(require_admin)):
    with db_session() as db:
        return {"exportedAt":datetime.now(timezone.utc).isoformat(),"notice":"配置快照不包含凭证、口令、原件或向量；完整备份请按部署文档执行。","settings":{k:v for k,v in get_entity(db,"setting","system").payload.items() if k!="id"},"knowledgeBases":[public_payload("kb",r.payload) for r in list_entities(db,"kb")],"models":[public_payload("model",r.payload) for r in list_entities(db,"model")],"connections":[public_payload("connection",r.payload) for r in list_entities(db,"connection")]}
