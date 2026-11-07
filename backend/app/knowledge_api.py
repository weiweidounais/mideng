from .pilot_service import business_roles
"""Unified-account adapter. No legacy anonymous/global knowledge routers mounted."""
import hashlib,json,copy,zipfile
from pathlib import Path
from datetime import datetime,timedelta,timezone
from typing import Literal
from fastapi import APIRouter,Depends,Request,UploadFile,File,Query
from fastapi.responses import Response
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select,or_,update
from .pilot_models import Membership,utcnow
from .pilot_service import fail,uid
from .knowledge_models import Library,KnowledgeDocument,RuleApplication,RuleRun
from .knowledge_evaluation import EvaluationCase,EvaluationReport,evaluate_rules

class Strict(BaseModel):model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
class LibraryBody(Strict):
    name:str=Field(min_length=1,max_length=80)
    restricted:bool=True
    readers:list[str]=Field(default_factory=list,max_length=100)
class LibraryPatch(LibraryBody):revision:int=Field(ge=1)
class Action(Strict):
    revision:int=Field(ge=1)
    action:Literal['publish','withdraw','retry']
class Search(Strict):query:str=Field(min_length=1,max_length=2000)
class AppBody(Strict):
    definition:dict
    revision:int=Field(default=0,ge=0)
class AppPublish(Strict):
    revision:int=Field(ge=1)
    cases:list[EvaluationCase]=Field(min_length=1,max_length=20)
class AppRun(Strict):
    input:str=Field(min_length=1,max_length=10000)
    mode:Literal['draft','published']='published'
class AppRollback(Strict):
    revision:int=Field(ge=1)
    target_revision:int=Field(ge=1)

MAX_PARSE_ATTEMPTS = 3
STATE_HINTS = {
    'queued': '原件已保存，等待后台解析；不需要重复上传。',
    'parsing': '正在解析原件；任务中断后会在恢复窗口内重新领取。',
    'review': '解析完成，请先核对片段，再发布供原文检索。',
    'published': '原文已发布，可检索并核对来源原件；未启用AI生成。',
    'failed': '解析未完成，请核对文件格式和文字内容后重试；原件仍保留。',
}

class ProcessingStatus(Strict):
    attempts:int
    max_attempts:int
    lease_expires_at:str|None
    waiting_for_recovery:bool
    can_retry:bool
    can_publish:bool

def visible(store,db,a,pid,lid,edit=False):
    store.membership(db,a,pid)
    lib=db.get(Library,lid)
    if not lib or lib.project_id!=pid or (lib.restricted and a.id!=lib.owner_id and a.id not in lib.readers):
        fail(404,'NOT_ACCESSIBLE','知识空间不存在或无访问权限')
    if edit and a.id!=lib.owner_id:fail(403,'KNOWLEDGE_OWNER','仅资料责任人可维护此知识空间')
    return lib

def scoped(db,cls,pid,lid,oid):
    row=db.get(cls,oid)
    if not row or row.project_id!=pid or row.library_id!=lid:fail(404,'NOT_ACCESSIBLE','对象不存在或无访问权限')
    return row

def original(d):
    path=Path(d.path)
    if not path.is_file():fail(404,'ORIGINAL_MISSING','原件暂不可读，请联系资料责任人')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=d.sha256:fail(409,'ORIGINAL_CHANGED','原件校验不符，请联系资料责任人')
    return raw

def revision(row,expected):
    if row.revision!=expected:fail(409,'REVISION_CONFLICT','内容已更新，请刷新后核对',current_revision=row.revision)

def library_view(l):return {k:getattr(l,k) for k in ['id','name','owner_id','restricted','readers','revision','created_at']}|{'domain':'knowledge'}
def doc_view(d,owner=False):
    result={k:getattr(d,k) for k in ['id','name','actor_id','state','revision','size','sha256','warnings','error','created_at']}|{'chunk_count':len(d.chunks),'domain':'knowledge','status_hint':STATE_HINTS.get(d.state,'请刷新后核对任务状态。')}
    if owner:
        result['processing']=ProcessingStatus(attempts=d.attempts,max_attempts=MAX_PARSE_ATTEMPTS,
            lease_expires_at=d.lease_until,
            waiting_for_recovery=d.state=='parsing' and bool(d.lease_until and d.lease_until<utcnow()),
            can_retry=d.state=='failed',can_publish=d.state=='review' and bool(d.chunks)).model_dump()
    return result

def run_knowledge_job(store):
    """Durable lease: a killed parser becomes reclaimable; no provider calls."""
    with store.transaction(write=True) as db:
        now=utcnow();d=db.scalar(select(KnowledgeDocument).where(or_(KnowledgeDocument.state=='queued',(KnowledgeDocument.state=='parsing') & (KnowledgeDocument.lease_until<now))).order_by(KnowledgeDocument.created_at).limit(1))
        if not d:return False

        if d.attempts>=MAX_PARSE_ATTEMPTS:
            d.state='failed';d.error='任务中断次数达到上限，请核对后手动重试';d.revision+=1;d.lease_until=None;return True
        d.attempts+=1;d.state='parsing';d.lease_until=(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat();did=d.id;claim=d.attempts;path=d.path;name=d.name;sha=d.sha256
    chunks=[];warnings=[];error=''
    try:
        raw=Path(path).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=sha:raise ValueError('original hash')
        from .parsers import parse_file
        result=parse_file(Path(path),name,did,{'imageUnderstanding':False,'parser':'local','chunkStrategy':'recursive'},None)
        chunks=result.chunks;warnings=result.warnings
        if not chunks:raise ValueError('empty')
    except Exception:
        error='解析未完成，请核对原件格式与文字内容；图片/扫描件识别需要另行配置服务。'
    with store.transaction(write=True) as db:
        d=db.get(KnowledgeDocument,did)
        if d.state!='parsing' or d.attempts!=claim:return False
        d.state='failed' if error else 'review';d.error=error;d.chunks=chunks;d.warnings=warnings;d.revision+=1;d.lease_until=None
    return True

def make_knowledge_router(store,actor,key):
    router=APIRouter(prefix='/projects/{pid}/knowledge',tags=['项目知识与应用'])
    def readers(db,pid,ids):
        for aid in ids:
            m=db.scalar(select(Membership).where(Membership.project_id==pid,Membership.account_id==aid))
            if not m or not m.active or m.valid_from>utcnow() or (m.valid_until and m.valid_until<=utcnow()):fail(422,'READER_INVALID','共享对象须为当前有效项目成员')
    def mutation(db,a,pid,lid,action,idem,payload,work):
        visible(store,db,a,pid,lid,edit=True)
        return store.mutation(db,a,'knowledge:'+pid+':'+lid+':'+action,idem,payload,work)

    @router.get('/libraries')
    def libraries(pid:str,a=Depends(actor)):
        with store.transaction() as db:
            store.membership(db,a,pid)
            rows=db.scalars(select(Library).where(Library.project_id==pid).order_by(Library.created_at))
            return [library_view(l) for l in rows if not l.restricted or l.owner_id==a.id or a.id in l.readers]

    @router.post('/libraries')
    def create(pid:str,b:LibraryBody,r:Request,a=Depends(actor),idem=Depends(key)):
        with store.transaction(write=True) as db:
            _,m=store.membership(db,a,pid)
            if not set(business_roles(m.roles))&{'项目经理','设计','商务','管理员'}:fail(403,'KNOWLEDGE_CREATE','由项目经理、设计或商务建立知识空间')
            readers(db,pid,b.readers)
            def work():
                l=Library(id=uid(),project_id=pid,owner_id=a.id,**b.model_dump());db.add(l);db.flush();store.audit(db,a,'knowledge.create',l.id,1,r.state.request_id,pid);return library_view(l)
            return store.mutation(db,a,'knowledge:'+pid+':create',idem,b.model_dump(),work)

    @router.put('/libraries/{lid}')
    def share(pid:str,lid:str,b:LibraryPatch,r:Request,a=Depends(actor),idem=Depends(key)):
        with store.transaction(write=True) as db:
            l=visible(store,db,a,pid,lid,edit=True);readers(db,pid,b.readers)
            def work():
                revision(l,b.revision);l.name=b.name;l.restricted=b.restricted;l.readers=b.readers;l.revision+=1;store.audit(db,a,'knowledge.share',lid,l.revision,r.state.request_id,pid);return library_view(l)
            return mutation(db,a,pid,lid,'share',idem,b.model_dump(),work)

    @router.get('/libraries/{lid}/documents')
    def documents(pid:str,lid:str,page:int=Query(1,ge=1),a=Depends(actor)):
        with store.transaction() as db:
            l=visible(store,db,a,pid,lid);q=select(KnowledgeDocument).where(KnowledgeDocument.library_id==lid)
            rows=list(db.scalars(q.order_by(KnowledgeDocument.created_at.desc())))
            rows=[d for d in rows if d.state=='published' or a.id==l.owner_id]
            return {'items':[doc_view(d,a.id==l.owner_id) for d in rows[(page-1)*20:page*20]],'total':len(rows),'page':page,'can_edit':a.id==l.owner_id,'model_enabled':False}

    @router.post('/libraries/{lid}/documents')
    async def upload(pid:str,lid:str,r:Request,file:UploadFile=File(...),a=Depends(actor),idem=Depends(key)):
        with store.transaction() as db:visible(store,db,a,pid,lid,edit=True)
        name=file.filename or '';ext=Path(name).suffix.lower()
        if not name or len(name)>180 or Path(name).name!=name or any(ord(c)<32 for c in name) or '\\' in name:fail(422,'UNSAFE_FILENAME','原件文件名无效')
        if ext not in {'.md','.txt','.csv','.pdf','.docx','.xlsx'}:fail(422,'FILE_TYPE','当前支持Markdown、TXT、CSV、PDF、Word、Excel')
        raw=await file.read(20*1024*1024+1)
        if not raw or len(raw)>20*1024*1024:fail(422,'FILE_SIZE','原件须非空且不超过20MB')
        if ext=='.pdf':
            import fitz
            try:
                if not raw.startswith(b'%PDF-'):raise ValueError()
                with fitz.open(stream=raw,filetype='pdf') as pdf:
                    if pdf.is_encrypted or pdf.page_count<1:raise ValueError()
            except Exception:fail(422,'FILE_FORMAT','PDF真实格式无效')
        if ext in {'.docx','.xlsx'}:
            import io
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as z:
                    required='word/document.xml' if ext=='.docx' else 'xl/workbook.xml'
                    if any('vbaproject' in n.lower() for n in z.namelist()) or required not in z.namelist() or len(z.infolist())>10000 or sum(i.file_size for i in z.infolist())>200*1024*1024:raise ValueError()
            except (ValueError,zipfile.BadZipFile):fail(422,'FILE_FORMAT','Office真实格式或解压内容无效')
        if ext in {'.txt','.csv','.md'}:
            try:
                text=raw.decode('utf-8-sig')
                if '\x00' in text:raise ValueError()
            except (ValueError,UnicodeError):fail(422,'FILE_FORMAT','文本真实内容须为有效UTF-8')
        folder=Path(store.engine.url.database).resolve().parent/'knowledge-originals';folder.mkdir(mode=0o700,exist_ok=True);did=uid();path=folder/(did+ext);sha=hashlib.sha256(raw).hexdigest();written=False
        try:
            with store.transaction(write=True) as db:
                def work():
                    nonlocal written
                    with path.open('xb') as f:f.write(raw)
                    path.chmod(0o600);written=True;d=KnowledgeDocument(id=did,project_id=pid,library_id=lid,actor_id=a.id,name=name,path=str(path),sha256=sha,size=len(raw));db.add(d);db.flush();store.audit(db,a,'knowledge.upload',did,1,r.state.request_id,pid);return doc_view(d,True)
                return mutation(db,a,pid,lid,'upload',idem,{'name':name,'sha256':sha},work)
        except BaseException:
            if written:path.unlink(missing_ok=True)
            raise

    @router.get('/libraries/{lid}/documents/{did}')
    def document(pid:str,lid:str,did:str,a=Depends(actor)):
        with store.transaction() as db:
            l=visible(store,db,a,pid,lid);d=scoped(db,KnowledgeDocument,pid,lid,did)
            if d.state!='published' and a.id!=l.owner_id:fail(404,'NOT_ACCESSIBLE','资料尚未发布')
            return doc_view(d,a.id==l.owner_id)|{'chunks':d.chunks}

    @router.get('/libraries/{lid}/documents/{did}/original')
    def download(pid:str,lid:str,did:str,a=Depends(actor)):
        with store.transaction() as db:
            l=visible(store,db,a,pid,lid);d=scoped(db,KnowledgeDocument,pid,lid,did)
            if d.state!='published' and a.id!=l.owner_id:fail(404,'NOT_ACCESSIBLE','资料尚未发布')
            from urllib.parse import quote
            return Response(original(d),media_type='application/octet-stream',headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(d.name)})

    @router.post('/libraries/{lid}/documents/{did}/actions')
    def action(pid:str,lid:str,did:str,b:Action,r:Request,a=Depends(actor),idem=Depends(key)):
        with store.transaction(write=True) as db:
            visible(store,db,a,pid,lid,edit=True);d=scoped(db,KnowledgeDocument,pid,lid,did)
            def work():
                revision(d,b.revision)
                if b.action=='publish':
                    if d.state!='review' or not d.chunks:fail(409,'NOT_REVIEWED','请先完成解析并核对片段')
                    original(d);d.state='published'
                elif b.action=='withdraw':
                    if d.state!='published':fail(409,'STATE_CONFLICT','资料尚未发布')
                    d.state='review'
                else:
                    if d.state!='failed':fail(409,'STATE_CONFLICT','仅失败任务可重试')
                    d.state='queued';d.error='';d.attempts=0
                d.revision+=1;store.audit(db,a,'knowledge.'+b.action,did,d.revision,r.state.request_id,pid);return doc_view(d,True)
            return mutation(db,a,pid,lid,'document:'+did,idem,b.model_dump(),work)

    @router.post('/libraries/{lid}/search')
    def search(pid:str,lid:str,b:Search,a=Depends(actor)):
        with store.transaction() as db:
            visible(store,db,a,pid,lid);hits=[]
            for d in db.scalars(select(KnowledgeDocument).where(KnowledgeDocument.library_id==lid,KnowledgeDocument.state=='published')):
                for chunk in d.chunks:
                    if b.query.casefold() in chunk['content'].casefold():hits.append({'document_id':d.id,'name':d.name,'location':chunk['location'],'content':chunk['content'],'original_url':f'/api/projects/{pid}/knowledge/libraries/{lid}/documents/{d.id}/original'})
            return {'mode':'keyword','model_enabled':False,'results':hits[:20],'notice':'仅检索已发布资料原文，未调用模型生成答案'}

    @router.get('/capabilities')
    def capabilities(pid:str,a=Depends(actor)):
        with store.transaction() as db:store.membership(db,a,pid)
        return {'model_enabled':False,'keyword_search':True,'rules':True,'local_parse':True,'interfaces':{'retrieve':'/libraries/{lid}/retrieve','chat':'/libraries/{lid}/chat/stream'},'notice':'模型接入接口已预留；本轮使用功能测试，未连接模型服务'}

    @router.post('/libraries/{lid}/retrieve')
    def retrieve(pid:str,lid:str,b:Search,a=Depends(actor)):
        with store.transaction() as db:visible(store,db,a,pid,lid)
        fail(503,'MODEL_NOT_CONFIGURED','向量模型尚未配置；可使用原文检索。')

    @router.post('/libraries/{lid}/chat/stream')
    def chat(pid:str,lid:str,b:Search,a=Depends(actor)):
        with store.transaction() as db:visible(store,db,a,pid,lid)
        from fastapi.responses import StreamingResponse
        # A terminal SSE error is part of the reserved contract, not a fake answer.
        event={'error':{'code':'MODEL_NOT_CONFIGURED','message':'生成及向量模型尚未配置；当前不生成模型答案。'}}
        return StreamingResponse(iter(['event: error\ndata: '+json.dumps(event,ensure_ascii=False)+'\n\n']),media_type='text/event-stream')
    def definition(data):
        from .applications import Definition,_definition,inspect_graph
        from pydantic import ValidationError
        try:body=Definition.model_validate(data)
        except ValidationError:fail(422,'APPLICATION_INVALID','请检查应用名称、节点和连接')
        d=_definition(body)
        if any(n['kind'] not in {'start','condition','template','output'} for n in d['nodes']):fail(409,'MODEL_DISABLED','检索与模型节点尚未启用，请先使用规则和模板节点')
        g=inspect_graph(d)
        if g[0]:fail(422,'APPLICATION_INVALID','；'.join(x['message'] for x in g[0]),field_errors=[{'field':x.get('nodeId','graph'),'message':x['message']} for x in g[0]])
        return d,g

    def app_view(app,owner):
        return {'id':app.id,'revision':app.revision,'domain':'knowledge','name':(app.definition if owner else app.published)['name'],'published':app.published is not None,'definition':app.definition if owner else None,'published_revision':app.published.get('revision') if app.published else None,'versions':[{'revision':v['revision'],'published_at':v['published_at']} for v in app.versions] if owner else []}

    @router.get('/libraries/{lid}/applications')
    def applications(pid:str,lid:str,a=Depends(actor)):
        with store.transaction() as db:
            l=visible(store,db,a,pid,lid)
            return [app_view(x,a.id==l.owner_id) for x in db.scalars(select(RuleApplication).where(RuleApplication.library_id==lid)) if x.published or a.id==l.owner_id]

    @router.post('/libraries/{lid}/applications')
    def app_create(pid:str,lid:str,b:AppBody,r:Request,a=Depends(actor),idem=Depends(key)):
        d,_=definition(b.definition)
        with store.transaction(write=True) as db:
            def work():
                app=RuleApplication(id=uid(),project_id=pid,library_id=lid,actor_id=a.id,definition=d);db.add(app);db.flush();store.audit(db,a,'knowledge.application.create',app.id,1,r.state.request_id,pid);return app_view(app,True)
            return mutation(db,a,pid,lid,'application.create',idem,b.model_dump(),work)

    @router.put('/libraries/{lid}/applications/{aid}')
    def app_edit(pid:str,lid:str,aid:str,b:AppBody,r:Request,a=Depends(actor),idem=Depends(key)):
        d,_=definition(b.definition)
        with store.transaction(write=True) as db:
            visible(store,db,a,pid,lid,edit=True);app=scoped(db,RuleApplication,pid,lid,aid)
            def work():
                revision(app,b.revision);app.definition=d;app.revision+=1;store.audit(db,a,'knowledge.application.edit',aid,app.revision,r.state.request_id,pid);return app_view(app,True)
            return mutation(db,a,pid,lid,'application.edit:'+aid,idem,b.model_dump(),work)

    @router.post('/libraries/{lid}/applications/{aid}/evaluate',response_model=EvaluationReport)
    async def app_evaluate(pid:str,lid:str,aid:str,b:AppPublish,r:Request,a=Depends(actor),idem=Depends(key)):
        with store.transaction(write=True) as db:
            visible(store,db,a,pid,lid,edit=True);app=scoped(db,RuleApplication,pid,lid,aid)
            saved=store.mutation(db,a,'knowledge:'+pid+':'+lid+':application.evaluate:'+aid,idem,b.model_dump(),lambda:{'id':uid(),'revision':1,'domain':'knowledge'})
            old=db.get(RuleRun,saved['id'])
            if old:return old.result
            revision(app,b.revision);d,g=definition(app.definition)
            report=await evaluate_rules(app,d,g,b.cases,a,saved['id']);result=report.model_dump()
            db.add(RuleRun(id=report.id,project_id=pid,library_id=lid,application_id=aid,actor_id=a.id,result=result))
            store.audit(db,a,'knowledge.application.evaluate',report.id,1,r.state.request_id,pid)
            from .pilot_models import Idempotency
            row=db.scalar(select(Idempotency).where(Idempotency.actor_id==a.id,Idempotency.key==idem,Idempotency.action=='knowledge:'+pid+':'+lid+':application.evaluate:'+aid));row.result=result
            return report

    @router.post('/libraries/{lid}/applications/{aid}/publish')
    async def app_publish(pid:str,lid:str,aid:str,b:AppPublish,r:Request,a=Depends(actor),idem=Depends(key)):
        with store.transaction(write=True) as db:
            visible(store,db,a,pid,lid,edit=True);app=scoped(db,RuleApplication,pid,lid,aid)
            # Rules only; this coroutine has no model or network operations.
            d,g=definition(app.definition);report=await evaluate_rules(app,d,g,b.cases,a,uid())
            def work():
                revision(app,b.revision)
                if report.passed!=report.total:fail(422,'EVALUATION_FAILED','测试用例未全部通过，未发布新版本',field_errors=[{'field':'cases.'+str(c.number-1),'message':'用例'+str(c.number)+'的实际结果不符合预期'} for c in report.cases if not c.passed])
                if app.published and app.published['revision']==app.revision:return app_view(app,True)
                snapshot=copy.deepcopy(d)|{'revision':app.revision,'evaluation':report.model_dump(),'published_at':utcnow()};app.published=snapshot;app.versions=[*app.versions,snapshot];store.audit(db,a,'knowledge.application.publish',aid,app.revision,r.state.request_id,pid);return app_view(app,True)
            return mutation(db,a,pid,lid,'application.publish:'+aid,idem,b.model_dump(),work)

    @router.post('/libraries/{lid}/applications/{aid}/rollback')
    def app_rollback(pid:str,lid:str,aid:str,b:AppRollback,r:Request,a=Depends(actor),idem=Depends(key)):
        with store.transaction(write=True) as db:
            visible(store,db,a,pid,lid,edit=True);app=scoped(db,RuleApplication,pid,lid,aid)
            def work():
                revision(app,b.revision);target=next((v for v in app.versions if v['revision']==b.target_revision),None)
                if not target:fail(404,'VERSION_NOT_FOUND','已发布版本不存在')
                app.published=copy.deepcopy(target);app.revision+=1;store.audit(db,a,'knowledge.application.rollback',aid,app.revision,r.state.request_id,pid);return app_view(app,True)
            return mutation(db,a,pid,lid,'application.rollback:'+aid,idem,b.model_dump(),work)

    @router.post('/libraries/{lid}/applications/{aid}/run')
    async def app_run(pid:str,lid:str,aid:str,b:AppRun,r:Request,a=Depends(actor),idem=Depends(key)):
        from .applications import _execute,RunBody
        from .security import Actor
        with store.transaction(write=True) as db:
            visible(store,db,a,pid,lid,edit=b.mode=='draft');app=scoped(db,RuleApplication,pid,lid,aid)
            data=app.definition if b.mode=='draft' else app.published
            if not data:fail(409,'NOT_PUBLISHED','应用尚未发布')
            d,g=definition({k:v for k,v in data.items() if k not in {'revision','evaluation','published_at'}})
            # Return saved result without a second execution on uncertain retries.
            old=store.mutation(db,a,'knowledge:'+pid+':'+lid+':application.run:'+aid,idem,b.model_dump(),lambda:{'id':uid(),'revision':1,'domain':'knowledge'})
            run=db.get(RuleRun,old['id'])
            if run:return run.result
            result=await _execute(d,RunBody(input=b.input,mode=b.mode),Actor(a.id,'user',''),{'id':old['id'],'applicationId':aid,'steps':[],'output':'','createdAt':utcnow()},g,persist=False)
            result.update(domain='knowledge',revision=1,application_revision=app.revision if b.mode=='draft' else app.published['revision']);db.add(RuleRun(id=old['id'],project_id=pid,library_id=lid,application_id=aid,actor_id=a.id,result=result));store.audit(db,a,'knowledge.application.run',old['id'],1,r.state.request_id,pid)
            from .pilot_models import Idempotency
            row=db.scalar(select(Idempotency).where(Idempotency.actor_id==a.id,Idempotency.key==idem,Idempotency.action=='knowledge:'+pid+':'+lid+':application.run:'+aid));row.result=result
            return result

    @router.get('/libraries/{lid}/runs')
    def runs(pid:str,lid:str,a=Depends(actor)):
        with store.transaction() as db:
            visible(store,db,a,pid,lid)
            return [x.result for x in db.scalars(select(RuleRun).where(RuleRun.library_id==lid,RuleRun.actor_id==a.id).order_by(RuleRun.created_at.desc()).limit(50))]
    return router
