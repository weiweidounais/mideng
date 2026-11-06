from datetime import datetime,date,timezone
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel,Field,field_validator
from .handoff_schemas import Strict,BomLine,FileOut

class PurchaseCreate(Strict):
    version_id:str
    title:str=Field(min_length=1,max_length=120)
    note:str=Field(min_length=1,max_length=2000)
    purchase_id:str;quality_id:str;commerce_id:str

class ResultLine(Strict):
    line_no:int=Field(ge=1)
    quantity:Decimal=Field(gt=0,max_digits=18,decimal_places=6)
    eta:date

class PurchaseResult(Strict):
    supplier:str=Field(min_length=1,max_length=200)
    lines:list[ResultLine]=Field(min_length=1,max_length=5000)
    note:str=Field(default='',max_length=2000)

class PurchaseArrival(Strict):
    line_no:int=Field(ge=1)
    quantity:Decimal=Field(gt=0,max_digits=18,decimal_places=6)
    occurred_at:datetime
    @field_validator('occurred_at')
    @classmethod
    def aware(cls,v):
        if v.tzinfo is None:raise ValueError('日期须含时区')
        return v.astimezone(timezone.utc)

class CostLine(Strict):
    name:str=Field(min_length=1,max_length=200)
    amount:Decimal=Field(ge=0,max_digits=18,decimal_places=2)

class PurchaseArchive(Strict):
    contract_no:str=Field(min_length=1,max_length=120)
    currency:Literal['CNY']='CNY'
    tax_basis:Literal['含税','不含税']
    contract_amount:Decimal=Field(gt=0,max_digits=18,decimal_places=2)
    costs:list[CostLine]=Field(min_length=1,max_length=100)
    file_ids:list[str]=Field(min_length=1,max_length=20)

class PurchaseAction(Strict):
    revision:int=Field(ge=1)
    action:Literal['accept_purchase','return_request','resubmit_request','submit_result','approve_purchase','reject_purchase','arrival','pass_quality','fail_quality','rectify','archive']
    reason:str=Field(default='',max_length=2000)
    result:PurchaseResult|None=None
    arrival:PurchaseArrival|None=None
    file_ids:list[str]=Field(default_factory=list,max_length=20)
    archive:PurchaseArchive|None=None

class ProcurementMutation(BaseModel):
    id:str;revision:int

class ProcurementEventOut(BaseModel):
    id:str;action:str;actor_id:str;body:dict;at:str

class ProcurementOut(BaseModel):
    id:str;project_id:str;version_id:str;revision:int;state:str;title:str;note:str
    pm_id:str;purchase_id:str;quality_id:str;commerce_id:str;owner_id:str
    lines:list[BomLine]
    result:PurchaseResult|None
    arrivals:list[dict]
    archive:PurchaseArchive|None
    archive_total:str|None
    due_at:str;overdue:bool;needs_review:bool;created_at:str;updated_at:str
    change_status:str=''
    change_id:str|None=None
    events:list[ProcurementEventOut]
    files:list[FileOut]

class ProcurementBoard(BaseModel):
    orders:list[ProcurementOut]
