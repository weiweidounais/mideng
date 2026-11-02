"""一期协同：需求交底包、设计↔采购契约、例外待办、采购料表。"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .db import db_session, get_entity, list_entities, put_entity
from .security import Actor, current_session

router = APIRouter(prefix="/collaboration", tags=["collaboration"])

KIND_REQ = "reqpkg"
KIND_IFACE = "iface"
KIND_BOM = "bomrow"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _row(entity) -> dict:
    data = dict(entity.payload)
    data["id"] = entity.id
    data["revision"] = entity.revision
    data["updatedAt"] = entity.updated_at.astimezone(timezone.utc).isoformat()
    return data


class ReqCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    projectName: str = Field(min_length=1, max_length=120)
    ownerName: str = Field(default="", max_length=80)
    marketOwner: str = Field(default="市场", max_length=40)
    summary: str = Field(min_length=1, max_length=2000)
    constraints: str = Field(default="", max_length=2000)
    attachments: list[str] = Field(default_factory=list, max_length=20)
    dueHint: str = Field(default="", max_length=120)


class ReqPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str | None = Field(default=None, max_length=2000)
    constraints: str | None = Field(default=None, max_length=2000)
    attachments: list[str] | None = None
    schemeNotes: str | None = Field(default=None, max_length=4000)
    status: Literal["draft", "briefed", "changed"] | None = None
    schemeAuthor: str | None = Field(default=None, max_length=40)


class IfaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    projectName: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=120)
    trigger: str = Field(min_length=1, max_length=200)
    deliverable: str = Field(min_length=1, max_length=200)
    slaHours: int = Field(default=24, ge=1, le=720)
    qualityRule: str = Field(default="", max_length=400)
    escalateTo: str = Field(default="项目经理", max_length=40)
    designOwner: str = Field(default="设计", max_length=40)
    purchaseOwner: str = Field(default="采购", max_length=40)
    reqPackageId: str | None = None


class IfacePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["open", "in_progress", "delivered", "overdue", "closed"] | None = None
    note: str | None = Field(default=None, max_length=1000)


class BomCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    projectName: str = Field(min_length=1, max_length=120)
    materialName: str = Field(min_length=1, max_length=120)
    spec: str = Field(default="", max_length=200)
    qty: str = Field(default="1", max_length=40)
    needBy: str = Field(default="", max_length=40)
    supplierHint: str = Field(default="", max_length=120)
    ifaceId: str | None = None
    reqPackageId: str | None = None


class BomPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["pending", "quoted", "ordered", "arrived", "blocked"] | None = None
    eta: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=1000)


def _seed_if_empty() -> None:
    with db_session() as db:
        if list_entities(db, KIND_REQ):
            return
        now = _now()
        due = (datetime.now(timezone.utc) + timedelta(hours=18)).isoformat()
        overdue = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
        req1 = {
            "id": "reqpkg-demo-01",
            "projectName": "嘉元·某智算中心机电一期",
            "ownerName": "甲方项目部",
            "marketOwner": "市场-王敏",
            "bizOwner": "商务-李昂",
            "summary": "机房冷冻水主管改线，要求不停机切换；预制管段优先；造价不突破已批概算 3%。",
            "constraints": "工期：现场切换窗口仅周六 02:00–06:00；噪声与洁净要求按业主要求附录 B。",
            "attachments": ["甲方会议纪要-2026-10-20.pdf", "冷冻水系统示意图-revC.dwg"],
            "dueHint": "交底后 48h 内设计回方案要点",
            "status": "briefed",
            "version": 1,
            "history": [
                {"at": now, "by": "市场-王敏", "action": "录入甲方需求"},
                {"at": now, "by": "商务-李昂", "action": "确认并发布交底包 v1"},
            ],
            "schemeNotes": "",
            "schemeAuthor": "",
            "schemeAt": "",
            "createdAt": now,
        }
        req2 = {
            "id": "reqpkg-demo-02",
            "projectName": "嘉元·预制厂订单 PO-8821",
            "ownerName": "甲方工程部",
            "marketOwner": "市场-王敏",
            "bizOwner": "商务-李昂",
            "summary": "新增两路支管预制，材质与母管一致；要可追溯管段编号。",
            "constraints": "发货不得晚于现场安装前 5 天。",
            "attachments": ["变更口头纪要截图.png"],
            "dueHint": "待商务交底",
            "status": "draft",
            "version": 1,
            "history": [{"at": now, "by": "市场-王敏", "action": "录入草稿，待商务交底"}],
            "schemeNotes": "",
            "schemeAuthor": "",
            "schemeAt": "",
            "createdAt": now,
        }
        put_entity(db, KIND_REQ, req1, owner="demo")
        put_entity(db, KIND_REQ, req2, owner="demo")

        iface1 = {
            "id": "iface-demo-01",
            "projectName": req1["projectName"],
            "name": "BOM/料表交接",
            "trigger": "设计发布冷冻水改线 BOM rev",
            "deliverable": "可采购料表（含规格、数量、需用日期）",
            "slaHours": 24,
            "qualityRule": "料号与图号一一对应；缺项标红",
            "escalateTo": "项目经理-周凯",
            "designOwner": "设计-赵倩",
            "purchaseOwner": "采购-陈旭",
            "reqPackageId": req1["id"],
            "status": "in_progress",
            "dueAt": due,
            "note": "等待设计补齐法兰垫片规格",
            "createdAt": now,
            "history": [{"at": now, "by": "设计-赵倩", "action": "创建契约并进入处理"}],
        }
        iface2 = {
            "id": "iface-demo-02",
            "projectName": req1["projectName"],
            "name": "变更料表补发",
            "trigger": "甲方约束变更后 4h",
            "deliverable": "增量料表 + 作废清单",
            "slaHours": 4,
            "qualityRule": "标注作废旧行号",
            "escalateTo": "项目经理-周凯",
            "designOwner": "设计-赵倩",
            "purchaseOwner": "采购-陈旭",
            "reqPackageId": req1["id"],
            "status": "overdue",
            "dueAt": overdue,
            "note": "超时未交，采购无法下单",
            "createdAt": now,
            "history": [{"at": now, "by": "系统", "action": "演示：标记超时"}],
        }
        put_entity(db, KIND_IFACE, iface1, owner="demo")
        put_entity(db, KIND_IFACE, iface2, owner="demo")

        bom1 = {
            "id": "bomrow-demo-01",
            "projectName": req1["projectName"],
            "materialName": "不锈钢预制管段 DN200",
            "spec": "304 / L=6m / 坡口按图",
            "qty": "12 根",
            "needBy": "2026-11-08",
            "supplierHint": "预制厂 A",
            "ifaceId": iface1["id"],
            "reqPackageId": req1["id"],
            "status": "quoted",
            "eta": "2026-11-05",
            "note": "已询价，待设计确认垫片",
            "createdAt": now,
        }
        bom2 = {
            "id": "bomrow-demo-02",
            "projectName": req1["projectName"],
            "materialName": "法兰垫片 DN200",
            "spec": "规格待设计补齐",
            "qty": "24 片",
            "needBy": "2026-11-08",
            "supplierHint": "",
            "ifaceId": iface1["id"],
            "reqPackageId": req1["id"],
            "status": "blocked",
            "eta": "",
            "note": "催料：等设计规格",
            "createdAt": now,
        }
        put_entity(db, KIND_BOM, bom1, owner="demo")
        put_entity(db, KIND_BOM, bom2, owner="demo")


def _refresh_overdue(db) -> None:
    now = datetime.now(timezone.utc)
    for entity in list_entities(db, KIND_IFACE):
        data = dict(entity.payload)
        due = data.get("dueAt")
        if data.get("status") in {"delivered", "closed"}:
            continue
        if due:
            try:
                due_dt = datetime.fromisoformat(due.replace("Z", "+00:00"))
            except ValueError:
                continue
            if due_dt < now and data.get("status") != "overdue":
                data["status"] = "overdue"
                data["id"] = entity.id
                put_entity(db, KIND_IFACE, data, owner=entity.owner)


def _exceptions(db) -> list[dict]:
    items: list[dict] = []
    for entity in list_entities(db, KIND_REQ):
        p = entity.payload
        if p.get("status") == "draft":
            items.append({
                "id": f"ex-req-draft-{entity.id}",
                "type": "需求未交底",
                "severity": "high",
                "projectName": p.get("projectName"),
                "title": f"{p.get('projectName')} 仍是草稿，商务未发布交底",
                "owner": p.get("bizOwner") or "商务",
                "relatedId": entity.id,
                "relatedKind": KIND_REQ,
            })
        elif p.get("status") in {"briefed", "changed"} and not (p.get("schemeNotes") or "").strip():
            if p.get("status") == "changed":
                title = f"{p.get('projectName')} 方案 v{max(int(p.get('version') or 1)-1, 1)} / 需求 v{p.get('version', 1)}，口径冲突，方案需重写"
                typ = "版本冲突"
            else:
                title = f"{p.get('projectName')} v{p.get('version', 1)} 已交底，设计尚未回写方案要点"
                typ = "方案未回写"
            items.append({
                "id": f"ex-scheme-{entity.id}",
                "type": typ,
                "severity": "medium",
                "projectName": p.get("projectName"),
                "title": title,
                "owner": "设计",
                "relatedId": entity.id,
                "relatedKind": KIND_REQ,
            })
    for entity in list_entities(db, KIND_IFACE):
        p = entity.payload
        if p.get("status") == "overdue":
            items.append({
                "id": f"ex-iface-{entity.id}",
                "type": "料表超时",
                "severity": "high",
                "projectName": p.get("projectName"),
                "title": f"{p.get('name')} 已超时，升级 {p.get('escalateTo')}",
                "owner": p.get("designOwner") or "设计",
                "relatedId": entity.id,
                "relatedKind": KIND_IFACE,
            })
    for entity in list_entities(db, KIND_BOM):
        p = entity.payload
        if p.get("status") == "blocked":
            items.append({
                "id": f"ex-bom-{entity.id}",
                "type": "催料未回",
                "severity": "medium",
                "projectName": p.get("projectName"),
                "title": f"{p.get('materialName')} 阻塞：{p.get('note') or '待设计/供应商回复'}",
                "owner": p.get("supplierHint") or "采购",
                "relatedId": entity.id,
                "relatedKind": KIND_BOM,
            })
    order = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda x: order.get(x.get("severity", "low"), 9))
    return items


@router.get("/board")
def board(_: Actor = Depends(current_session)):
    _seed_if_empty()
    with db_session() as db:
        _refresh_overdue(db)
        return {
            "packages": [_row(e) for e in list_entities(db, KIND_REQ)],
            "contracts": [_row(e) for e in list_entities(db, KIND_IFACE)],
            "bom": [_row(e) for e in list_entities(db, KIND_BOM)],
            "exceptions": _exceptions(db),
        }


@router.post("/packages")
def create_package(body: ReqCreate, actor: Actor = Depends(current_session)):
    now = _now()
    data = {
        "id": _uid("reqpkg"),
        "projectName": body.projectName,
        "ownerName": body.ownerName,
        "marketOwner": body.marketOwner,
        "bizOwner": "",
        "summary": body.summary,
        "constraints": body.constraints,
        "attachments": body.attachments,
        "dueHint": body.dueHint,
        "status": "draft",
        "version": 1,
        "history": [{"at": now, "by": body.marketOwner or actor.role, "action": "录入甲方需求草稿"}],
        "schemeNotes": "",
        "schemeAuthor": "",
        "schemeAt": "",
        "createdAt": now,
    }
    with db_session() as db:
        put_entity(db, KIND_REQ, data, owner=actor.owner)
        return data


@router.patch("/packages/{package_id}")
def patch_package(package_id: str, body: ReqPatch, actor: Actor = Depends(current_session)):
    with db_session() as db:
        entity = get_entity(db, KIND_REQ, package_id)
        data = dict(entity.payload)
        data["id"] = entity.id
        now = _now()
        if body.summary is not None:
            data["summary"] = body.summary
        if body.constraints is not None:
            data["constraints"] = body.constraints
        if body.attachments is not None:
            data["attachments"] = body.attachments
        if body.schemeNotes is not None:
            data["schemeNotes"] = body.schemeNotes
            data["schemeAuthor"] = body.schemeAuthor or actor.role
            data["schemeAt"] = now
            data.setdefault("history", []).append({"at": now, "by": data["schemeAuthor"], "action": "回写方案优化要点"})
        if body.status is not None:
            if body.status == "briefed" and data.get("status") == "draft":
                data["status"] = "briefed"
                data["bizOwner"] = data.get("bizOwner") or "商务"
                data["version"] = int(data.get("version") or 1)
                data.setdefault("history", []).append({"at": now, "by": data["bizOwner"], "action": f"发布交底包 v{data['version']}"})
            elif body.status == "changed":
                data["status"] = "changed"
                data["version"] = int(data.get("version") or 1) + 1
                data["schemeNotes"] = ""
                data["schemeAuthor"] = ""
                data["schemeAt"] = ""
                data.setdefault("history", []).append({"at": now, "by": actor.role, "action": f"需求变更，升版至 v{data['version']}，方案需重写"})
            elif body.status == "draft":
                data["status"] = "draft"
            else:
                data["status"] = body.status
        put_entity(db, KIND_REQ, data, owner=entity.owner)
        return data


@router.post("/contracts")
def create_contract(body: IfaceCreate, actor: Actor = Depends(current_session)):
    now = datetime.now(timezone.utc)
    data = {
        "id": _uid("iface"),
        "projectName": body.projectName,
        "name": body.name,
        "trigger": body.trigger,
        "deliverable": body.deliverable,
        "slaHours": body.slaHours,
        "qualityRule": body.qualityRule,
        "escalateTo": body.escalateTo,
        "designOwner": body.designOwner,
        "purchaseOwner": body.purchaseOwner,
        "reqPackageId": body.reqPackageId,
        "status": "open",
        "dueAt": (now + timedelta(hours=body.slaHours)).isoformat(),
        "note": "",
        "createdAt": now.isoformat(),
        "history": [{"at": now.isoformat(), "by": actor.role, "action": "创建接口契约"}],
    }
    with db_session() as db:
        put_entity(db, KIND_IFACE, data, owner=actor.owner)
        return data


@router.patch("/contracts/{contract_id}")
def patch_contract(contract_id: str, body: IfacePatch, actor: Actor = Depends(current_session)):
    with db_session() as db:
        entity = get_entity(db, KIND_IFACE, contract_id)
        data = dict(entity.payload)
        data["id"] = entity.id
        now = _now()
        if body.status is not None:
            data["status"] = body.status
            data.setdefault("history", []).append({"at": now, "by": actor.role, "action": f"状态 → {body.status}"})
        if body.note is not None:
            data["note"] = body.note
        put_entity(db, KIND_IFACE, data, owner=entity.owner)
        return data


@router.post("/bom")
def create_bom(body: BomCreate, actor: Actor = Depends(current_session)):
    data = {
        "id": _uid("bomrow"),
        "projectName": body.projectName,
        "materialName": body.materialName,
        "spec": body.spec,
        "qty": body.qty,
        "needBy": body.needBy,
        "supplierHint": body.supplierHint,
        "ifaceId": body.ifaceId,
        "reqPackageId": body.reqPackageId,
        "status": "pending",
        "eta": "",
        "note": "",
        "createdAt": _now(),
    }
    with db_session() as db:
        put_entity(db, KIND_BOM, data, owner=actor.owner)
        return data


@router.patch("/bom/{bom_id}")
def patch_bom(bom_id: str, body: BomPatch, actor: Actor = Depends(current_session)):
    with db_session() as db:
        entity = get_entity(db, KIND_BOM, bom_id)
        data = dict(entity.payload)
        data["id"] = entity.id
        if body.status is not None:
            data["status"] = body.status
        if body.eta is not None:
            data["eta"] = body.eta
        if body.note is not None:
            data["note"] = body.note
        put_entity(db, KIND_BOM, data, owner=entity.owner)
        return data
