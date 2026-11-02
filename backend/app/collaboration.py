"""Governed pilot: versioned brief → design handoff → purchase acknowledgment.

Uses existing Entity storage; no ERP writes, external notifications or AI decisions.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from .db import Entity, db_session, get_entity, list_entities, put_entity
from .security import Actor, current_session, require_admin

router = APIRouter(prefix="/collaboration", tags=["collaboration"])
KIND_REQ, KIND_IFACE, KIND_BOM = "reqpkg", "iface", "bomrow"
PROJECT, MEMBER, EVENT, DECISION = "collab-project", "collab-member", "collab-event", "collab-decision"
Role = Literal["market", "business", "project_manager", "design", "purchase"]
ROLES = {"market": "市场", "business": "商务", "project_manager": "项目经理", "design": "设计", "purchase": "采购"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _uid(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:20]}"


def _row(entity):
    return {**deepcopy(entity.payload), "id": entity.id, "revision": entity.revision,
            "updatedAt": entity.updated_at.replace(tzinfo=timezone.utc).isoformat()}


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProjectCreate(Input):
    code: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=120)
    processOwner: str = Field(min_length=1, max_length=80)
    dataOwner: str = Field(min_length=1, max_length=80)


class MemberSet(Input):
    principal: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=80)
    roles: list[Role] = Field(max_length=5)
    expectedRevision: int = Field(ge=0)


class Versioned(Input):
    expectedRevision: int = Field(ge=1)


class ProjectPatch(Versioned):
    processOwner: str = Field(min_length=1, max_length=80)
    dataOwner: str = Field(min_length=1, max_length=80)


class ReqCreate(Input):
    projectId: str
    ownerName: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=2000)
    constraints: str = Field(default="", max_length=2000)
    attachments: list[str] = Field(default_factory=list, max_length=20)
    dueHint: str = Field(default="", max_length=120)


class ReqPatch(Versioned):
    summary: str | None = Field(default=None, min_length=1, max_length=2000)
    constraints: str | None = Field(default=None, max_length=2000)
    attachments: list[str] | None = Field(default=None, max_length=20)
    schemeNotes: str | None = Field(default=None, min_length=1, max_length=4000)
    status: Literal["briefed", "changed"] | None = None
    changeReason: str = Field(default="", max_length=1000)


class IfaceCreate(Input):
    reqPackageId: str
    name: str = Field(min_length=1, max_length=120)
    trigger: str = Field(min_length=1, max_length=200)
    deliverable: str = Field(min_length=1, max_length=200)
    slaHours: int = Field(default=24, ge=1, le=720)
    qualityRule: str = Field(min_length=1, max_length=400)
    escalateTo: str = Field(min_length=1, max_length=80)
    designOwner: str = Field(min_length=1, max_length=80)
    purchaseOwner: str = Field(min_length=1, max_length=80)


class IfacePatch(Versioned):
    status: Literal["in_progress", "delivered", "closed", "returned"]
    note: str = Field(min_length=1, max_length=1000)
    evidence: str = Field(default="", max_length=1000)


class BomCreate(Input):
    ifaceId: str
    materialCode: str = Field(min_length=1, max_length=80)
    materialName: str = Field(min_length=1, max_length=120)
    spec: str = Field(min_length=1, max_length=200)
    qty: str = Field(min_length=1, max_length=40)
    unit: str = Field(min_length=1, max_length=20)
    needBy: date
    supplierHint: str = Field(default="", max_length=120)

    @field_validator("qty")
    @classmethod
    def positive_quantity(cls, value):
        try:
            number = Decimal(value)
            if number.is_finite() and number > 0:
                return value
        except InvalidOperation:
            pass
        raise ValueError("数量必须是大于零的数字；单位单独填写")


class BomPatch(Versioned):
    status: Literal["pending", "quoted", "ordered", "arrived", "blocked"] | None = None
    eta: date | None = None
    note: str = Field(min_length=1, max_length=1000)
    sourceRef: str = Field(default="", max_length=200)
    rebase: bool = False


class DecisionCreate(Input):
    projectId: str
    title: str = Field(min_length=1, max_length=200)
    options: str = Field(min_length=1, max_length=2000)
    decision: str = Field(min_length=1, max_length=2000)
    ownerName: str = Field(min_length=1, max_length=80)
    dueAt: date
    evidence: str = Field(min_length=1, max_length=1000)


class DecisionClose(Versioned):
    result: str = Field(min_length=1, max_length=2000)
    evidence: str = Field(min_length=1, max_length=1000)


def _member_id(project, principal):
    return uuid.uuid5(uuid.NAMESPACE_URL, f"mideng:{project}:{principal}").hex


def _roles(db, project, actor):
    if actor.role == "admin":
        return list(ROLES)
    member = get_entity(db, MEMBER, _member_id(project, actor.owner), False)
    return member.payload["roles"] if member else []


def _access(db, project, actor, selected=None, allowed=None):
    get_entity(db, PROJECT, project)
    roles = _roles(db, project, actor)
    if not roles:
        raise HTTPException(403, "尚未获得此项目的协同授权，请联系管理员")
    if allowed is None:
        return selected if selected in roles else roles[0]
    if selected:
        if selected not in roles or selected not in allowed:
            raise HTTPException(403, "当前工作角色无权执行此操作")
        return selected
    candidates = [r for r in roles if r in allowed]
    if not candidates:
        raise HTTPException(403, "此操作需要指定的项目业务角色")
    return candidates[0]


def _event(db, entity, actor, role, action, detail=""):
    put_entity(db, EVENT, {"id": _uid("event"), "projectId": entity.payload.get("projectId", entity.id),
        "recordId": entity.id, "recordKind": entity.kind, "revision": entity.revision,
        "at": _now(), "principal": actor.owner, "role": role, "action": action, "detail": detail},
        owner=actor.owner, parent_id=entity.payload.get("projectId", entity.id))


def _save(db, entity, data, expected, actor, role, action, detail=""):
    """Compare-and-swap is in SQL, not a read-then-write revision check."""
    data = deepcopy(data)
    history = data.setdefault("history", [])
    history.append({"at": _now(), "by": ROLES.get(role, role), "action": action, "detail": detail})
    result = db.execute(update(Entity).where(Entity.kind == entity.kind, Entity.id == entity.id,
        Entity.revision == expected).values(payload=data, revision=expected + 1,
        updated_at=datetime.now(timezone.utc)), execution_options={"synchronize_session": False})
    if result.rowcount != 1:
        raise HTTPException(409, "记录已被其他人修改，请刷新后核对；本次修改未保存")
    db.expire(entity)
    db.refresh(entity)
    _event(db, entity, actor, role, action, detail)
    return _row(entity)


def _lock_basis(db, req):
    # Serialize downstream writes with a simultaneous requirement change.
    result = db.execute(update(Entity).where(Entity.kind == KIND_REQ, Entity.id == req.id,
        Entity.revision == req.revision).values(revision=req.revision),
        execution_options={"synchronize_session": False})
    if result.rowcount != 1:
        raise HTTPException(409, "需求依据已更新，请刷新后核对")


def _new(db, kind, data, actor, role, action):
    row = put_entity(db, kind, {"id": _uid(kind), "createdAt": _now(), **data},
                     owner=actor.owner, parent_id=data.get("projectId"))
    _event(db, row, actor, role, action)
    return _row(row)


def _insert_unique(db, kind, data, parent_id=None):
    row = Entity(kind=kind, id=data["id"], payload=data, parent_id=parent_id)
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        raise HTTPException(409, "记录已由另一请求建立，请刷新后核对")
    return row


def _migrate_legacy(db):
    """Idempotently scope pre-pilot data; only admins can grant access afterwards."""
    for kind in (KIND_REQ, KIND_IFACE, KIND_BOM):
        for entity in list_entities(db, kind):
            if entity.payload.get("projectId"):
                continue
            data = deepcopy(entity.payload)
            name = data.get("projectName") or "历史未命名项目"
            pid = "legacy-" + uuid.uuid5(uuid.NAMESPACE_URL, name).hex[:20]
            if not get_entity(db, PROJECT, pid, False):
                put_entity(db, PROJECT, {"id": pid, "code": pid, "name": name,
                    "processOwner": "待管理员确认", "dataOwner": "待管理员确认", "legacy": True})
            data.update(projectId=pid, legacy=True)
            # Never treat old records as confirmed current handoffs.
            if kind != KIND_REQ:
                data["basisVersion"] = 0
            if kind == KIND_REQ:
                data.setdefault("schemeVersion", 0)
            put_entity(db, kind, data, owner=entity.owner, parent_id=pid)


def _req(db, id):
    return get_entity(db, KIND_REQ, id)


def _ready(req):
    p = req.payload
    if p.get("status") != "briefed" or not p.get("schemeNotes") or p.get("schemeVersion") != p.get("version"):
        raise HTTPException(409, "请先发布当前版本交底，并由设计回写本版本方案")


def _basis_current(data, req):
    return data.get("basisVersion") == req.payload.get("version") and req.payload.get("status") == "briefed"


@router.get("/access")
def access(actor: Actor = Depends(current_session)):
    with db_session() as db:
        _migrate_legacy(db)
        projects = [{**_row(p), "roles": _roles(db, p.id, actor)} for p in list_entities(db, PROJECT)
                    if _roles(db, p.id, actor)]
        return {"principal": actor.owner, "admin": actor.role == "admin", "projects": projects, "roleLabels": ROLES}


@router.post("/projects")
def create_project(body: ProjectCreate, actor: Actor = Depends(require_admin)):
    with db_session() as db:
        # Code is the primary key: uniqueness also holds for concurrent requests.
        pid = "project-" + body.code.lower()
        if get_entity(db, PROJECT, pid, False):
            raise HTTPException(409, "项目编码已存在")
        row = _insert_unique(db, PROJECT, {"id": pid, **body.model_dump(), "projectId": pid,
            "sourceOfTruth": "用友/ERP 的财务、物料和订单仍以原系统为准；密灯仅记录协同与人工核对"})
        _event(db, row, actor, "admin", "建立项目责任档案")
        return _row(row)


@router.get("/projects/{project_id}/members")
def members(project_id: str, actor: Actor = Depends(require_admin)):
    with db_session() as db:
        get_entity(db, PROJECT, project_id)
        return [_row(m) for m in list_entities(db, MEMBER, parent_id=project_id)]


@router.patch("/projects/{project_id}")
def update_project(project_id: str, body: ProjectPatch, actor: Actor = Depends(require_admin)):
    with db_session() as db:
        entity = get_entity(db, PROJECT, project_id)
        data = {**deepcopy(entity.payload), **body.model_dump(exclude={"expectedRevision"})}
        return _save(db, entity, data, body.expectedRevision, actor, "admin", "确认项目责任人")


@router.put("/projects/{project_id}/members")
def set_member(project_id: str, body: MemberSet, actor: Actor = Depends(require_admin)):
    with db_session() as db:
        get_entity(db, PROJECT, project_id)
        mid = _member_id(project_id, body.principal)
        entity = get_entity(db, MEMBER, mid, False)
        data = {"id": mid, "projectId": project_id, **body.model_dump(exclude={"expectedRevision"})}
        data["roles"] = sorted(set(data["roles"]))
        if entity:
            return _save(db, entity, data, body.expectedRevision, actor, "admin", "调整项目授权")
        if body.expectedRevision != 0:
            raise HTTPException(409, "授权记录已改变，请刷新")
        row = _insert_unique(db, MEMBER, data, parent_id=project_id)
        _event(db, row, actor, "admin", "新增项目授权")
        return _row(row)


def _board(db, project_id):
    packages = [_row(e) for e in list_entities(db, KIND_REQ, parent_id=project_id)]
    reqs = {p["id"]: p for p in packages}
    contracts = [_row(e) for e in list_entities(db, KIND_IFACE, parent_id=project_id)]
    bom = [_row(e) for e in list_entities(db, KIND_BOM, parent_id=project_id)]
    decisions = [_row(e) for e in list_entities(db, DECISION, parent_id=project_id)]
    exceptions = []

    def exception(row, kind, typ, role, owner, action, due=""):
        exceptions.append({"id": f"{typ}-{row['id']}", "projectId": project_id, "relatedId": row["id"],
            "relatedKind": kind, "type": typ, "severity": "high", "ownerRole": role,
            "owner": owner, "title": action, "dueAt": due, "basisVersion": row.get("basisVersion", row.get("version"))})

    for p in packages:
        if p["status"] in ("draft", "changed"):
            exception(p, KIND_REQ, "待商务交底", "business", p.get("bizOwner") or "商务", "核对约束与变更原因，发布当前版本")
        elif not p.get("schemeNotes") or p.get("schemeVersion") != p["version"]:
            exception(p, KIND_REQ, "待设计回写", "design", "设计", "根据当前交底版本提交方案要点")
    for row in contracts + bom:
        req = reqs.get(row.get("reqPackageId"))
        row["needsReview"] = not req or row.get("basisVersion") != req["version"] or req["status"] != "briefed"
        if row["needsReview"]:
            exception(row, KIND_IFACE if row in contracts else KIND_BOM, "依据待复核", "design", row.get("designOwner") or "设计", "需求已变化；重新核对交付/料表，采购不得沿用旧依据")
    for c in contracts:
        c["overdue"] = c["status"] not in ("closed", "delivered") and c.get("dueAt", "9999") < _now()
        if c["overdue"]:
            exception(c, KIND_IFACE, "交付超时", "design", c["designOwner"], f"补齐交付，必要时升级给 {c['escalateTo']}", c["dueAt"])
        if c["status"] == "delivered" and not c["needsReview"]:
            exception(c, KIND_IFACE, "待采购验收", "purchase", c["purchaseOwner"], "按质量规则验收，确认或退回补齐", c["dueAt"])
    for b in bom:
        if b["status"] == "blocked":
            exception(b, KIND_BOM, "采购阻塞", "purchase", "采购", b.get("note") or "补充阻塞原因与交期")
    for d in decisions:
        if d["status"] == "open" and d["dueAt"] < date.today().isoformat():
            exception(d, DECISION, "决策执行超时", "project_manager", d["ownerName"], "核对执行结果并登记证据", d["dueAt"])
    return {"project": _row(get_entity(db, PROJECT, project_id)), "packages": packages, "contracts": contracts,
        "bom": bom, "decisions": decisions, "exceptions": exceptions,
        "events": [_row(e) for e in list_entities(db, EVENT, parent_id=project_id) if e.payload["recordKind"] != MEMBER],
        "measurements": {"communicationBaselineHours": None, "savedHours": None, "roi": None, "status": "待实测"}}


@router.get("/board")
def board(projectId: str, actor: Actor = Depends(current_session)):
    with db_session() as db:
        _access(db, projectId, actor)
        return _board(db, projectId)


@router.get("/projects/{project_id}/export")
def export(project_id: str, actor: Actor = Depends(current_session)):
    with db_session() as db:
        _access(db, project_id, actor)
        data = _board(db, project_id)
        # Grants/browser identities are operational access data, not project deliverables.
        for e in data["events"]:
            e.pop("principal", None)
        for d in data["decisions"]:
            d.pop("decider", None)
        return {"schemaVersion": 1, "exportedAt": _now(), **data}


@router.post("/packages")
def create_package(body: ReqCreate, actor: Actor = Depends(current_session), x_collaboration_role: str | None = Header(default=None)):
    with db_session() as db:
        role = _access(db, body.projectId, actor, x_collaboration_role, ["market"])
        return _new(db, KIND_REQ, {**body.model_dump(), "projectName": get_entity(db, PROJECT, body.projectId).payload["name"],
            "marketOwner": "市场", "bizOwner": "", "status": "draft", "version": 1,
            "schemeNotes": "", "schemeVersion": 0, "snapshots": []}, actor, role, "录入需求草稿")


@router.patch("/packages/{package_id}")
def patch_package(package_id: str, body: ReqPatch, actor: Actor = Depends(current_session), x_collaboration_role: str | None = Header(default=None)):
    with db_session() as db:
        entity = _req(db, package_id)
        data = deepcopy(entity.payload)
        # Exactly one category of change per request prevents mixed-field permission bypass.
        fields = body.model_fields_set - {"expectedRevision", "changeReason"}
        content = bool(fields & {"summary", "constraints", "attachments"})
        if "schemeNotes" in fields:
            if fields != {"schemeNotes"}:
                raise HTTPException(422, "方案回写与需求变更必须分开提交")
            role = _access(db, data["projectId"], actor, x_collaboration_role, ["design"])
            if not body.schemeNotes:
                raise HTTPException(422, "请填写本版本方案内容")
            if data["status"] != "briefed":
                raise HTTPException(409, "请商务先发布当前交底版本")
            data.update(schemeNotes=body.schemeNotes, schemeVersion=data["version"], schemeAuthor="设计", schemeAt=_now())
            action = "回写本版本方案"
        elif body.status == "changed":
            role = _access(db, data["projectId"], actor, x_collaboration_role, ["business"])
            if data["status"] != "briefed" or not body.changeReason or not content:
                raise HTTPException(422, "变更需要已交底版本、新需求内容及变更原因")
            snapshot = {k: deepcopy(v) for k, v in data.items() if k not in ("snapshots", "history")}
            data.setdefault("snapshots", []).append(snapshot)
            data.update(status="changed", version=data["version"] + 1, schemeNotes="", schemeVersion=0,
                        changeReason=body.changeReason, schemeAuthor="", schemeAt="")
            action = "需求升版；下游依据待复核"
        elif body.status == "briefed":
            role = _access(db, data["projectId"], actor, x_collaboration_role, ["business"])
            if fields != {"status"} or data["status"] not in ("draft", "changed"):
                raise HTTPException(409, "仅可发布待交底版本；修改内容请单独提交")
            data.update(status="briefed", bizOwner="商务")
            action = "发布交底版本"
        else:
            role = _access(db, data["projectId"], actor, x_collaboration_role, ["market"])
            if data["status"] != "draft" or not content or fields - {"summary", "constraints", "attachments"}:
                raise HTTPException(409, "市场仅可编辑草稿，已交底需求请商务登记升版")
            action = "编辑需求草稿"
        for key in ("summary", "constraints", "attachments"):
            if key in fields:
                if getattr(body, key) is None:
                    raise HTTPException(422, "需求字段不可为空值")
                data[key] = getattr(body, key)
        return _save(db, entity, data, body.expectedRevision, actor, role, action, body.changeReason)


@router.post("/contracts")
def create_contract(body: IfaceCreate, actor: Actor = Depends(current_session), x_collaboration_role: str | None = Header(default=None)):
    with db_session() as db:
        req = _req(db, body.reqPackageId)
        role = _access(db, req.payload["projectId"], actor, x_collaboration_role, ["design"])
        _lock_basis(db, req)
        _ready(req)
        return _new(db, KIND_IFACE, {**body.model_dump(), "projectId": req.payload["projectId"],
            "projectName": req.payload["projectName"], "basisVersion": req.payload["version"], "status": "open",
            "dueAt": (datetime.now(timezone.utc) + timedelta(hours=body.slaHours)).isoformat(),
            "note": "", "evidence": ""}, actor, role, "建立设计采购交付契约")


@router.patch("/contracts/{contract_id}")
def patch_contract(contract_id: str, body: IfacePatch, actor: Actor = Depends(current_session), x_collaboration_role: str | None = Header(default=None)):
    with db_session() as db:
        entity = get_entity(db, KIND_IFACE, contract_id)
        data = deepcopy(entity.payload)
        allowed = ["purchase"] if body.status in ("closed", "returned") else ["design"]
        role = _access(db, data["projectId"], actor, x_collaboration_role, allowed)
        req = _req(db, data["reqPackageId"])
        _lock_basis(db, req)
        if body.status in ("closed", "returned"):
            if data["status"] != "delivered" or not _basis_current(data, req):
                raise HTTPException(409, "只能验收当前版本的已交付契约")
        elif body.status == "delivered":
            _ready(req)
            if not body.evidence:
                raise HTTPException(422, "交付必须填写可核对的文档编号或证据位置")
            if data["status"] == "closed" and _basis_current(data, req):
                raise HTTPException(409, "本版本已验收，无需重复交付")
            data.update(basisVersion=req.payload["version"], evidence=body.evidence)
        elif data["status"] not in ("open", "returned", "in_progress", "overdue"):
            raise HTTPException(409, "当前状态不能恢复处理中；变更后请重新交付")
        data.update(status=body.status, note=body.note)
        action = {"closed": "采购确认验收", "returned": "采购退回补齐", "delivered": "设计提交版本交付", "in_progress": "设计推进交付"}[body.status]
        return _save(db, entity, data, body.expectedRevision, actor, role, action, body.note)


@router.post("/bom")
def create_bom(body: BomCreate, actor: Actor = Depends(current_session), x_collaboration_role: str | None = Header(default=None)):
    with db_session() as db:
        contract = get_entity(db, KIND_IFACE, body.ifaceId)
        c = contract.payload
        role = _access(db, c["projectId"], actor, x_collaboration_role, ["design"])
        req = _req(db, c["reqPackageId"])
        _lock_basis(db, req)
        _ready(req)
        if not _basis_current(c, req):
            raise HTTPException(409, "契约依据已过期，请设计先重新交付")
        return _new(db, KIND_BOM, {**body.model_dump(mode="json"), "projectId": c["projectId"],
            "projectName": c["projectName"], "reqPackageId": c["reqPackageId"], "basisVersion": req.payload["version"],
            "status": "pending", "eta": "", "note": "", "sourceRef": ""}, actor, role, "登记设计料表")


@router.patch("/bom/{bom_id}")
def patch_bom(bom_id: str, body: BomPatch, actor: Actor = Depends(current_session), x_collaboration_role: str | None = Header(default=None)):
    with db_session() as db:
        entity = get_entity(db, KIND_BOM, bom_id)
        data = deepcopy(entity.payload)
        role = _access(db, data["projectId"], actor, x_collaboration_role, ["design"] if body.rebase else ["purchase"])
        req = _req(db, data["reqPackageId"])
        _lock_basis(db, req)
        contract = get_entity(db, KIND_IFACE, data["ifaceId"]).payload
        if body.rebase:
            if body.status is not None or body.eta is not None or body.sourceRef:
                raise HTTPException(422, "设计复核依据不能同时改采购状态")
            _ready(req)
            if not _basis_current(contract, req) or contract["status"] not in ("delivered", "closed"):
                raise HTTPException(409, "请先完成当前版本设计交付")
            data["basisVersion"] = req.payload["version"]
            action = "设计复核料表依据（采购事实保持原记录）"
        else:
            if body.status in ("quoted", "ordered", "arrived"):
                if not _basis_current(data, req) or not _basis_current(contract, req) or contract["status"] != "closed":
                    raise HTTPException(409, "当前版本需设计复核并经采购验收，才可推进采购")
            transitions = {"pending": {"pending", "quoted", "blocked"}, "quoted": {"quoted", "ordered", "blocked"},
                "ordered": {"ordered", "arrived", "blocked"}, "arrived": {"arrived", "blocked"},
                "blocked": {"blocked", "pending", "quoted", "ordered", "arrived"}}
            if body.status and body.status not in transitions.get(data["status"], set()):
                raise HTTPException(409, "请依次登记询价、下单、到货；阻塞恢复需核对原系统")
            if body.status in ("ordered", "arrived") and not (body.sourceRef or data.get("sourceRef")):
                raise HTTPException(422, "下单/到货必须记录原系统订单或收货凭证编号")
            if body.status:
                data["status"] = body.status
            if body.eta:
                data["eta"] = body.eta.isoformat()
            if body.sourceRef:
                data["sourceRef"] = body.sourceRef
            action = "采购登记人工核对结果（不写入ERP）"
        data["note"] = body.note
        return _save(db, entity, data, body.expectedRevision, actor, role, action, body.note)


@router.post("/decisions")
def create_decision(body: DecisionCreate, actor: Actor = Depends(current_session), x_collaboration_role: str | None = Header(default=None)):
    with db_session() as db:
        role = _access(db, body.projectId, actor, x_collaboration_role, ["project_manager"])
        return _new(db, DECISION, {**body.model_dump(mode="json"), "decider": actor.owner, "status": "open", "result": ""}, actor, role, "人工登记决策与执行责任")


@router.patch("/decisions/{decision_id}")
def close_decision(decision_id: str, body: DecisionClose, actor: Actor = Depends(current_session), x_collaboration_role: str | None = Header(default=None)):
    with db_session() as db:
        entity = get_entity(db, DECISION, decision_id)
        role = _access(db, entity.payload["projectId"], actor, x_collaboration_role, ["project_manager"])
        if entity.payload["status"] != "open":
            raise HTTPException(409, "此决策已登记结果")
        data = {**deepcopy(entity.payload), "status": "closed", "result": body.result, "resultEvidence": body.evidence}
        return _save(db, entity, data, body.expectedRevision, actor, role, "登记决策执行结果", body.evidence)
