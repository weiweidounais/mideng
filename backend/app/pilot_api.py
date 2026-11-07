from .pilot_service import business_roles
"""Explicit HTTP contracts for the foundation, scoped to authenticated accounts."""
import hashlib
import secrets
import time
import threading
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update
from .pilot_models import Account, Session, Project, Membership, Audit, Outbox, Todo, Idempotency, utcnow
from .pilot_service import Store, ROLES, uid, fail, hasher, account_view, project_view, member_view

COOKIE = 'mideng_pilot_session'


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class AccountBody(Strict):
    username: str = Field(min_length=2, max_length=80, pattern=r'^[a-zA-Z0-9_.-]+$')
    display_name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=6, max_length=128)

    @field_validator('display_name')
    @classmethod
    def name_valid(cls, value):
        if not value.strip():
            raise ValueError('姓名不能为空白')
        return value.strip()

    @field_validator('password')
    @classmethod
    def password_valid(cls, value):
        if len(value.strip()) < 6:
            raise ValueError('密码至少需要6位非首尾空白字符')
        return value


class LoginBody(Strict):
    username: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=1, max_length=128)


class ProjectBody(Strict):
    code: str = Field(min_length=1, max_length=80, pattern=r'^[a-zA-Z0-9_.-]+$')
    name: str = Field(min_length=1, max_length=120)

    @field_validator('name')
    @classmethod
    def name_valid(cls, value):
        if not value.strip():
            raise ValueError('项目名称不能为空白')
        return value.strip()


class ProjectPatch(Strict):
    name: str = Field(min_length=1, max_length=120)

    @field_validator('name')
    @classmethod
    def name_valid(cls, value):
        if not value.strip():
            raise ValueError('项目名称不能为空白')
        return value.strip()
    revision: int = Field(ge=1)


class MemberBody(Strict):
    account_id: str = Field(min_length=1, max_length=100)
    roles: list[str] = Field(min_length=1, max_length=10)
    active: bool = True
    revision: int = Field(ge=0)
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    @field_validator('roles')
    @classmethod
    def roles_valid(cls, value):
        if len(value) != len(set(value)) or any(r not in ROLES for r in value):
            raise ValueError('岗位必须是有效且不重复的业务岗位')
        return value

    @field_validator('valid_from', 'valid_until')
    @classmethod
    def aware(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError('日期须含时区')
        return value.astimezone(timezone.utc) if value else None


class AccountOut(BaseModel):
    id: str
    username: str
    display_name: str
    is_admin: bool


class SessionOut(BaseModel):
    account: AccountOut
    csrf: str


class SetupOut(BaseModel):
    required: bool


class OkOut(BaseModel):
    ok: bool


class ProjectOut(BaseModel):
    id: str
    code: str
    name: str
    revision: int
    roles: list[str]
    actions: list[str]


class MemberOut(BaseModel):
    id: str
    account_id: str
    username: str
    display_name: str
    roles: list[str]
    active: bool
    valid_from: str
    valid_until: str | None
    revision: int


class AuditOut(BaseModel):
    id: str
    actor_roles: list[str]
    actor_id: str
    action: str
    object_id: str
    revision: int
    request_id: str
    at: str


class TodoOut(BaseModel):
    target_kind:str|None=None
    target_id:str|None=None
    version_id:str|None=None
    id: str
    project_id: str
    title: str
    created_at: str


def make_router(store: Store):
    router = APIRouter(prefix='/api')
    attempts = defaultdict(deque)
    attempts_lock = threading.Lock()
    dummy_hash = hasher.hash(secrets.token_urlsafe(16))

    def actor(request: Request):
        raw = request.cookies.get(COOKIE, '')
        with store.transaction() as db:
            session = db.get(Session, hashlib.sha256(raw.encode()).hexdigest())
            a = db.get(Account, session.account_id) if session else None
            if not session or session.expires_at <= utcnow() or not a or not a.active:
                fail(401, 'SESSION_EXPIRED', '请登录独立账号后继续')
            if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
                if not secrets.compare_digest(request.headers.get('x-csrf-token', ''), session.csrf):
                    fail(403, 'CSRF_REJECTED', '请求验证失败，请刷新页面后重试')
            request.state.actor_id = a.id
            return a

    def admin(a=Depends(actor)):
        if not a.is_admin:
            fail(403, 'ADMIN_REQUIRED', '需要管理员配置权限')
        return a

    def key(x_idempotency_key: Annotated[str, Header(min_length=8, max_length=100)]):
        return x_idempotency_key

    def issue(db, a, request, response):
        old = db.get(Session, hashlib.sha256(request.cookies.get(COOKIE, '').encode()).hexdigest())
        if old:
            db.delete(old)
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        db.add(Session(token_hash=hashlib.sha256(token.encode()).hexdigest(), account_id=a.id,
                       csrf=csrf, expires_at=(datetime.now(timezone.utc) + timedelta(hours=8)).isoformat()))
        response.set_cookie(COOKIE, token, httponly=True, secure=request.url.scheme=='https', samesite='strict', max_age=28800, path='/')
        return {'account': account_view(a), 'csrf': csrf}

    @router.get('/setup', response_model=SetupOut)
    def setup_state():
        with store.transaction() as db:
            return {'required': db.scalar(select(Account.id).limit(1)) is None}

    @router.post('/setup', response_model=SessionOut)
    def setup(body: AccountBody, request: Request, response: Response):
        if request.client.host not in {'127.0.0.1', '::1'}:
            fail(403, 'LOOPBACK_REQUIRED', '首次设置仅允许本机访问')
        with store.transaction(write=True) as db:
            if db.scalar(select(Account.id).limit(1)):
                fail(409, 'ALREADY_INITIALIZED', '已完成首次设置，请登录')
            a = Account(id=uid(), username=body.username, display_name=body.display_name,
                        password_hash=hasher.hash(body.password), is_admin=True)
            db.add(a); db.flush()
            store.audit(db, a, 'account.bootstrap', a.id, 1, request.state.request_id)
            return issue(db, a, request, response)

    @router.post('/auth/login', response_model=SessionOut)
    def login(body: LoginBody, request: Request, response: Response):
        identifier = request.client.host
        with attempts_lock:
            bucket = attempts[identifier]
            now = time.monotonic()
            while bucket and bucket[0] < now - 600:
                bucket.popleft()
            if len(bucket) >= 8:
                fail(429, 'LOGIN_LIMIT', '尝试次数过多，请10分钟后再试')
            bucket.append(now)
        with store.transaction(write=True) as db:
            a = db.scalar(select(Account).where(Account.username == body.username))
            valid = hasher.verify(body.password, a.password_hash if a else dummy_hash)
            if not a or not valid or not a.active:
                fail(401, 'LOGIN_FAILED', '账号或密码不正确')
            with attempts_lock:
                attempts.pop(identifier, None)
            return issue(db, a, request, response)

    @router.get('/session', response_model=SessionOut)
    def session(request: Request, a=Depends(actor)):
        with store.transaction() as db:
            s = db.get(Session, hashlib.sha256(request.cookies[COOKIE].encode()).hexdigest())
            return {'account': account_view(a), 'csrf': s.csrf}

    @router.post('/auth/logout', response_model=OkOut)
    def logout(request: Request, response: Response, a=Depends(actor)):
        with store.transaction(write=True) as db:
            s = db.get(Session, hashlib.sha256(request.cookies[COOKIE].encode()).hexdigest())
            if s:
                db.delete(s)
        response.delete_cookie(COOKIE, path='/')
        return {'ok': True}

    @router.get('/accounts', response_model=list[AccountOut])
    def accounts(a=Depends(admin)):
        with store.transaction() as db:
            return [account_view(v) for v in db.scalars(select(Account).where(Account.active.is_(True)))]

    @router.post('/accounts', response_model=AccountOut)
    def create_account(body: AccountBody, request: Request, a=Depends(admin), idem=Depends(key)):
        with store.transaction(write=True) as db:
            def write():
                if db.scalar(select(Account).where(Account.username == body.username)):
                    fail(409, 'USERNAME_EXISTS', '账号名已存在')
                row = Account(id=uid(), username=body.username, display_name=body.display_name,
                              password_hash=hasher.hash(body.password), is_admin=False)
                db.add(row); db.flush()
                store.audit(db, a, 'account.create', row.id, 1, request.state.request_id)
                return account_view(row)
            # A salted request digest prevents stored idempotency metadata from being a password oracle.
            payload = body.model_dump(exclude={'password'}) | {'password_digest': hashlib.sha256((a.password_hash + body.password).encode()).hexdigest()}
            return store.mutation(db, a, 'account.create', idem, payload, write)

    from .handoff_schemas import DocOut,ContractOut,RowOut,FileOut
    from .procurement_schemas import ProcurementMutation
    from .change_schemas import ChangeMutation
    from .trace_schemas import Mutation as TraceMutation, ReshapeOut, LabelOut

    class KnowledgeResult(BaseModel):
        model_config = {'extra':'allow'}
        domain: Literal['knowledge']
        id: str
        revision: int

    class RequestOut(BaseModel):
        result: KnowledgeResult | ProjectOut | AccountOut | MemberOut | DocOut | ContractOut | RowOut | FileOut | ProcurementMutation | ChangeMutation | TraceMutation | ReshapeOut | LabelOut

    @router.get('/requests/{request_key}', response_model=RequestOut)
    def request_result(request_key: str, a=Depends(actor)):
        with store.transaction() as db:
            record = db.scalar(select(Idempotency).where(Idempotency.actor_id == a.id, Idempotency.key == request_key))
            if not record:
                fail(404, 'RESULT_NOT_FOUND', '尚未找到已提交结果，可使用原请求编号重试')
            if record.action == 'account.create':
                if not a.is_admin:
                    fail(403, 'ADMIN_REQUIRED', '需要管理员配置权限')
            elif record.action.startswith('member.update:'):
                if not a.is_admin:
                    fail(403, 'ADMIN_REQUIRED', '需要管理员配置权限')
            else:
                if record.action.startswith('knowledge:'):
                    from .knowledge_api import visible
                    pid=record.action.split(':')[1];lid=record.result['id'] if record.action.endswith(':create') else record.action.split(':')[2]
                    visible(store,db,a,pid,lid)
                    return {'result':record.result}
                if record.action.startswith('assurance:'):
                    from .assurance_service import access
                    from .assurance_models import EvidenceExport
                    from .evidence_export import export_access
                    pid=record.action.split(':',2)[1];store.membership(db,a,pid)
                    if ':exception:' in record.action or ':file:' in record.action:
                        access(store,db,a,pid,record.action.split(':')[3])
                    elif record.action.endswith(':export'):
                        job=db.get(EvidenceExport,record.result.get('id'));export_access(store,db,a,job)
                    return {'result':record.result}
                if record.action.startswith('cost:'):
                    store.membership(db,a,record.action.split(':')[1],'cost.detail')
                    return {'result':record.result}
                elif record.action.startswith('trace:'):
                    store.membership(db,a,record.action.split(':')[1])
                    return {'result':record.result}
                elif record.action.startswith('change:'):
                    pid=record.action.split(':',2)[1];_,m=store.membership(db,a,pid)
                    if ':file:' in record.action:
                        from .change_models import ChangeFile
                        f=db.get(ChangeFile,record.result.get('id'))
                        if f and f.restricted and not set(business_roles(m.roles))&{'商务','财务'}:fail(404,'NOT_ACCESSIBLE','原件不存在或无访问权限')
                    return {'result':record.result}
                if record.action.startswith('procurement:'):
                    pid=record.action.split(':',2)[1]
                    _,m=store.membership(db,a,pid)
                    if ':file.archive:' in record.action and not set(business_roles(m.roles))&{'商务','财务'}:
                        fail(404,'NOT_ACCESSIBLE','原件不存在或无访问权限')
                    return {'result':record.result}
                if record.action.startswith('handoff:'):
                    pid=record.action.split(':',2)[1]
                    store.membership(db,a,pid)
                    # Re-check draft and current role scope before returning a prior response.
                    if record.action.endswith('document.create') or ':document.' in record.action:
                        from .handoff_models import Document
                        from .handoff_service import visible,EDIT
                        d=db.get(Document,record.result.get('id'))
                        roles=business_roles(store.membership(db,a,pid)[1].roles)
                        if not d or not visible(db,d,a,roles):
                            fail(404,'NOT_ACCESSIBLE','对象不存在或无访问权限')
                        result=dict(record.result)
                        if d.created_by!=a.id and not set(roles).intersection(EDIT[d.kind]):
                            result['draft']=None
                            result['draft_files']=[]
                        return {'result':result}
                else:
                    pid = record.action.split(':', 1)[1] if ':' in record.action else record.result['id']
                    store.membership(db, a, pid)
            return {'result': record.result}

    @router.get('/projects', response_model=list[ProjectOut])
    def projects(a=Depends(actor)):
        with store.transaction() as db:
            rows = db.execute(select(Project, Membership).join(Membership, Membership.project_id == Project.id).where(
                Membership.account_id == a.id, Membership.active.is_(True), Membership.valid_from <= utcnow())).all()
            return [project_view(p, m.roles) for p, m in rows if not m.valid_until or m.valid_until > utcnow()]

    @router.post('/projects', response_model=ProjectOut)
    def create_project(body: ProjectBody, request: Request, a=Depends(admin), idem=Depends(key)):
        with store.transaction(write=True) as db:
            def write():
                if db.scalar(select(Project.id).where(Project.code == body.code)):
                    fail(409, 'PROJECT_CODE_EXISTS', '项目编码已存在')
                p = Project(id=uid(), code=body.code, name=body.name, owner_id=a.id)
                db.add(p); db.flush()
                db.add(Membership(id=uid(), project_id=p.id, account_id=a.id, roles=['管理员'], valid_from=utcnow()))
                store.audit(db, a, 'project.create', p.id, 1, request.state.request_id, p.id)
                db.add(Outbox(id=uid(), project_id=p.id, recipient_id=a.id, title='项目已创建，请配置成员岗位'))
                return project_view(p, ['管理员'])
            return store.mutation(db, a, 'project.create', idem, body.model_dump(), write)

    @router.get('/projects/{pid}', response_model=ProjectOut)
    def project(pid: str, a=Depends(actor)):
        with store.transaction() as db:
            p, m = store.membership(db, a, pid)
            return project_view(p, m.roles)

    @router.patch('/projects/{pid}', response_model=ProjectOut)
    def patch_project(pid: str, body: ProjectPatch, request: Request, a=Depends(actor), idem=Depends(key)):
        with store.transaction(write=True) as db:
            p, m = store.membership(db, a, pid, 'project.edit')
            def write():
                count = db.execute(update(Project).where(Project.id == pid, Project.revision == body.revision).values(
                    name=body.name, revision=Project.revision + 1).execution_options(synchronize_session=False)).rowcount
                if count != 1:
                    fail(409, 'REVISION_CONFLICT', '项目已被更新，保留了你的输入，请核对最新版本', current_revision=p.revision)
                store.audit(db, a, 'project.edit', pid, body.revision + 1, request.state.request_id, pid)
                return {'id': p.id, 'code': p.code, 'name': body.name, 'revision': body.revision + 1,
                        'roles': m.roles, 'actions': project_view(p, m.roles)['actions']}
            return store.mutation(db, a, 'project.edit:' + pid, idem, body.model_dump(), write)

    @router.get('/projects/{pid}/members', response_model=list[MemberOut])
    def members(pid: str, a=Depends(actor)):
        with store.transaction() as db:
            store.membership(db, a, pid)
            return [member_view(m, person) for m, person in db.execute(select(Membership, Account).join(
                Account, Membership.account_id == Account.id).where(Membership.project_id == pid))]

    @router.put('/projects/{pid}/members', response_model=MemberOut)
    def save_member(pid: str, body: MemberBody, request: Request, a=Depends(admin), idem=Depends(key)):
        with store.transaction(write=True) as db:
            # Technical admin manages membership, but is never implicitly allowed project business reads.
            if not db.get(Project, pid):
                fail(404, 'NOT_ACCESSIBLE', '项目不存在或无访问权限')
            person = db.get(Account, body.account_id)
            if not person or not person.active:
                fail(422, 'ACCOUNT_NOT_FOUND', '请选择有效独立账号')
            def write():
                m = db.scalar(select(Membership).where(Membership.project_id == pid, Membership.account_id == body.account_id))
                current = m.revision if m else 0
                if current != body.revision:
                    fail(409, 'REVISION_CONFLICT', '成员授权已更新，请核对后重试', current_revision=current)
                start = body.valid_from.isoformat() if body.valid_from else (m.valid_from if m else utcnow())
                end = body.valid_until.isoformat() if body.valid_until else None
                if end and end <= start:
                    fail(422, 'INVALID_VALIDITY', '失效时间必须晚于生效时间')
                if m:
                    result = db.execute(update(Membership).where(Membership.id == m.id, Membership.revision == current).values(
                        roles=body.roles, active=body.active, valid_from=start, valid_until=end,
                        revision=current + 1).execution_options(synchronize_session=False))
                    if result.rowcount != 1:
                        fail(409, 'REVISION_CONFLICT', '成员授权已更新')
                    db.refresh(m)
                else:
                    m = Membership(id=uid(), project_id=pid, account_id=person.id, roles=body.roles,
                                   active=body.active, valid_from=start, valid_until=end)
                    db.add(m); db.flush()
                store.audit(db, a, 'member.update', m.id, m.revision, request.state.request_id, pid)
                if body.active:
                    db.add(Outbox(id=uid(), project_id=pid, recipient_id=person.id, title='项目岗位已配置，请核对本人权限'))
                return member_view(m, person)
            return store.mutation(db, a, 'member.update:' + pid, idem, body.model_dump(mode='json'), write)

    @router.get('/projects/{pid}/audit', response_model=list[AuditOut])
    def audit(pid: str, a=Depends(actor)):
        with store.transaction() as db:
            store.membership(db, a, pid, 'audit.read')
            return [dict(id=v.id, actor_id=v.actor_id, actor_roles=v.actor_roles, action=v.action, object_id=v.object_id,
                         revision=v.revision, request_id=v.request_id, at=v.at)
                    for v in db.scalars(select(Audit).where(Audit.project_id == pid).order_by(Audit.at.desc()).limit(100))]

    @router.get('/todos', response_model=list[TodoOut])
    def todos(a=Depends(actor)):
        with store.transaction() as db:
            result = []
            for v in db.scalars(select(Todo).where(Todo.recipient_id == a.id).order_by(Todo.created_at.desc())):
                m = db.scalar(select(Membership).where(Membership.project_id == v.project_id, Membership.account_id == a.id))
                if m and m.active and m.valid_from <= utcnow() and (not m.valid_until or m.valid_until > utcnow()):
                    result.append(dict(id=v.id, project_id=v.project_id, title=v.title, created_at=v.created_at,target_kind=v.target_kind,target_id=v.target_id,version_id=v.version_id))
            return result

    from .handoff_api import make_handoff_router
    router.include_router(make_handoff_router(store,actor,key))
    from .procurement_api import make_procurement_router
    router.include_router(make_procurement_router(store,actor,key))
    from .change_api import make_change_router
    router.include_router(make_change_router(store,actor,key))
    from .trace_api import make_trace_router
    router.include_router(make_trace_router(store,actor,key))
    @router.get('/spool-locator/{sid}',response_model=ProjectOut)
    def locate(sid:str,a=Depends(actor)):
        from .trace_models import Spool
        with store.transaction() as db:
            s=db.get(Spool,sid)
            if not s:fail(404,'NOT_ACCESSIBLE','对象不存在或无访问权限')
            p,m=store.membership(db,a,s.project_id)
            return project_view(p,m.roles)
    from .cost_api import make_cost_router
    router.include_router(make_cost_router(store,actor,key))
    from .assurance_api import make_assurance_router
    router.include_router(make_assurance_router(store,actor,key))
    from .trace_workspace import make_trace_workspace
    router.include_router(make_trace_workspace(store,actor))
    from .cost_workspace import make_cost_workspace
    router.include_router(make_cost_workspace(store,actor))
    from .workspace_api import make_workspace_router
    router.include_router(make_workspace_router(store,actor))
    from .knowledge_api import make_knowledge_router
    router.include_router(make_knowledge_router(store,actor,key))
    return router
