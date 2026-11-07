from datetime import datetime,date,timezone
from decimal import Decimal
from typing import Literal,Any
from pydantic import BaseModel,ConfigDict,Field,field_validator

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)

class ReqData(Strict):
    title:str=Field(min_length=1,max_length=120)
    summary:str=Field(min_length=1,max_length=8000)
    constraints:str=Field(default='',max_length=4000)
    source:str=Field(min_length=1,max_length=1000)
    attachment_ids:list[str]=Field(default_factory=list,max_length=20)
    brief_due_at:datetime|None=None
    reply_due_at:datetime|None=None
    @field_validator('brief_due_at','reply_due_at')
    @classmethod
    def utc(cls,v):
        if v and v.tzinfo is None:raise ValueError('日期须含时区')
        return v.astimezone(timezone.utc) if v else v

class BomLine(Strict):
    material:str=Field(min_length=1,max_length=120)
    spec:str=Field(min_length=1,max_length=200)
    quantity:Decimal=Field(gt=0,max_digits=18,decimal_places=6)
    unit:str=Field(min_length=1,max_length=20)
    need_by:date

class SchemeData(Strict):
    title:str=Field(min_length=1,max_length=120)
    notes:str=Field(min_length=1,max_length=8000)
    risks:str=Field(default='',max_length=4000)
    bom:list[BomLine]=Field(default_factory=list,max_length=5000)
    attachment_ids:list[str]=Field(default_factory=list,max_length=20)
    review_reason:str=Field(default='',max_length=1000)

class DocCreate(Strict):
    kind:Literal['requirement','scheme']
    parent_id:str|None=None
    source_version_id:str|None=None
    body:ReqData|SchemeData

class DocPatch(Strict):
    revision:int=Field(ge=1)
    body:ReqData|SchemeData
    source_version_id:str|None=None

class Revision(Strict):
    revision:int=Field(ge=1)

class Withdraw(Revision):
    reason:str=Field(min_length=1,max_length=1000)

class Publish(Revision):
    recipient_ids:list[str]=Field(min_length=1,max_length=100)
    diff_summary:str=Field(min_length=1,max_length=1000)

class ContractCreate(Strict):
    version_id:str
    recipient_id:str
    proxies:list[str]=Field(default_factory=list,max_length=20)
    deliverable:str=Field(min_length=1,max_length=1000)
    quality_rule:str=Field(min_length=1,max_length=1000)
    sla_hours:int=Field(default=24,ge=1,le=720)
    require_arrival:bool=False

class ContractAction(Revision):
    action:Literal['issue','submit','accept','return','close','pause','resume','cancel','reschedule']
    reason:str=Field(default='',max_length=1000)
    due_at:datetime|None=None
    @field_validator('due_at')
    @classmethod
    def utc(cls,v):
        if v and v.tzinfo is None:raise ValueError('日期须含时区')
        return v.astimezone(timezone.utc) if v else v

class RowPatch(Revision):
    state:Literal['pending','quoted','ordered','arrived']
    eta:date|None=None
    blocked:bool=False
    note:str=Field(default='',max_length=1000)

class ArrivalCreate(Revision):
    quantity:Decimal=Field(gt=0,max_digits=18,decimal_places=6)
    occurred_at:datetime
    @field_validator('occurred_at')
    @classmethod
    def utc(cls,v):
        if v.tzinfo is None:raise ValueError('日期须含时区')
        return v.astimezone(timezone.utc)

class FileOut(BaseModel):
    id:str;name:str;sha256:str;size:int;media_type:str

class VersionOut(BaseModel):
    id:str;document_id:str;number:int;source_version_id:str|None;previous_id:str|None
    body:ReqData|SchemeData
    attachments:list[FileOut]
    recipients:list[str]
    diff_summary:str
    published_by:str;published_at:str
    current:bool
    withdrawn:bool

class DocOut(BaseModel):
    id:str;kind:str;parent_id:str|None;source_version_id:str|None
    revision:int;has_draft:bool;version_no:int;needs_review:bool
    draft:ReqData|SchemeData|None
    draft_files:list[FileOut]=Field(default_factory=list)
    versions:list[VersionOut]
    created_by:str

class ContractOut(BaseModel):
    id:str;version_id:str;recipient_id:str;proxies:list[str];created_by:str
    deliverable:str;quality_rule:str;require_arrival:bool;sla_hours:int
    triggered_at:str;original_due_at:str;due_at:str;state:str;paused_at:str|None
    pause_seconds:int;return_count:int;revision:int;overdue:bool;needs_review:bool

class RowOut(BaseModel):
    id:str;contract_id:str;line_no:int;material:str;spec:str;quantity:str;unit:str;need_by:str
    arrived:str;state:str;eta:str|None;blocked:bool;note:str;revision:int

class ArrivalOut(BaseModel):
    id:str;row_id:str;quantity:str;occurred_at:str;created_by:str;created_at:str

class IssueOut(BaseModel):
    id:str;object_id:str;rule:str;owner_id:str;title:str;active:bool;detected_at:str|None;closed_at:str|None

class EventOut(BaseModel):
    id:str;object_id:str;action:str;body:dict[str,Any];actor_id:str;at:str

class BoardOut(BaseModel):
    documents:list[DocOut];contracts:list[ContractOut];rows:list[RowOut];arrivals:list[ArrivalOut]
    issues:list[IssueOut];events:list[EventOut]

class PreviewError(BaseModel):
    row:int;field:str;message:str

class BomPreviewOut(BaseModel):
    rows:list[BomLine];errors:list[PreviewError]
