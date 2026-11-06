from datetime import datetime,date,timezone
from typing import Literal
from decimal import Decimal
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
from .handoff_schemas import FileOut
class Strict(BaseModel):model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
class Scope(Strict):
 period:str=Field(pattern=r'^\d{4}-(0[1-9]|1[0-2])$')
 currency:str=Field(pattern=r'^[A-Z]{3}$')
 tax_basis:Literal['含税','不含税']
 @field_validator('period')
 @classmethod
 def period_valid(cls,v):
  if date.fromisoformat(v+'-01').year>=9999:raise ValueError('期间超出支持范围')
  return v
class ProfileCreate(Strict):
 source_system:str=Field(min_length=1,max_length=80)
 name:str=Field(min_length=1,max_length=120)
 subjects:dict[str,str]=Field(min_length=1,max_length=2000)
 wbs:dict[str,str]=Field(min_length=1,max_length=2000)
 key_mode:Literal['id','composite']='id'
 key_fields:list[Literal['document_no','document_line','entry_date','business_id']]=Field(default_factory=list)
 estimate_policy:Literal['separate','include']='separate'
 basis:str=Field(min_length=1,max_length=2000)
 @model_validator(mode='after')
 def valid_maps(self):
  if any(not k.strip() or not v.strip() or len(k)>200 or len(v)>200 for m in [self.subjects,self.wbs] for k,v in m.items()):raise ValueError('映射源编码与归集编码须非空且不超过200字')
  if self.key_mode=='composite' and not {'document_no','document_line','entry_date'}<=set(self.key_fields):raise ValueError('组合键须明确凭证号、行号和日期，不能猜测去重')
  if len(self.key_fields)!=len(set(self.key_fields)):raise ValueError('组合键字段不可重复')
  return self
class UploadMeta(Scope):
 profile_id:str
 mode:Literal['increment','replace']
 replace_ids:list[str]=Field(default_factory=list,max_length=100)
 reason:str=Field(min_length=1,max_length=2000)
 exported_at:datetime
 data_cutoff:datetime
 corrects_batch_id:str|None=None
 @model_validator(mode='after')
 def times(self):
  if self.exported_at.tzinfo is None or self.data_cutoff.tzinfo is None or self.data_cutoff>self.exported_at or self.exported_at>datetime.now(timezone.utc):raise ValueError('导出/截止时间须含时区，截止不晚于导出，导出不晚于现在')
  if self.mode=='replace' and not self.replace_ids:raise ValueError('替换须明确选择旧批次范围')
  if self.mode=='increment' and self.replace_ids:raise ValueError('增量不能暗中替换批次')
  if len(set(self.replace_ids))!=len(self.replace_ids):raise ValueError('替换范围不可重复')
  self.exported_at=self.exported_at.astimezone(timezone.utc);self.data_cutoff=self.data_cutoff.astimezone(timezone.utc)
  return self
class BatchAction(Strict):
 revision:int=Field(ge=1)
 action:Literal['mapping','recheck','commit','withdraw']
 mapping:dict[str,str]=Field(default_factory=dict,max_length=40)
 confirmed:bool=False
 reason:str=Field(default='',max_length=2000)
class CalendarCreate(Strict):
 name:str=Field(min_length=1,max_length=120)
 start:date
 end:date
 workdays:list[date]=Field(min_length=1,max_length=400)
 basis:str=Field(min_length=1,max_length=2000)
 @model_validator(mode='after')
 def coverage(self):
  if not 0<=(self.end-self.start).days<=400 or len(set(self.workdays))!=len(self.workdays) or any(not self.start<=d<=self.end for d in self.workdays):raise ValueError('须确认有效日历范围、唯一工作日，其余覆盖日为非工作日')
  return self
class BudgetCreate(Strict):
 currency:str=Field(pattern=r'^[A-Z]{3}$')
 tax_basis:Literal['含税','不含税']
 kind:Literal['baseline','adjustment']
 amount:str=Field(pattern=r'^-?\d{1,14}(\.\d{1,2})?$')
 approval_no:str=Field(min_length=1,max_length=200)
 basis:str=Field(min_length=1,max_length=2000)
 file_ids:list[str]=Field(min_length=1,max_length=20)
 change_id:str|None=None
class CloseCreate(Scope):
 calendar_id:str|None=None
 control_total:str|None=Field(default=None,pattern=r'^-?\d{1,14}(\.\d{1,2})?$')
 control_basis:str=Field(default='',max_length=2000)
 allow_partial:bool=False
 partial_reason:str=Field(default='',max_length=2000)
 revenue:str|None=Field(default=None,pattern=r'^-?\d{1,14}(\.\d{1,2})?$')
 revenue_comparable:bool=False
 revenue_basis:str=Field(default='',max_length=2000)
 revenue_file_ids:list[str]=Field(default_factory=list,max_length=20)
 correction_of:str|None=None
 reason:str=Field(min_length=1,max_length=2000)
class CloseAction(Strict):
 revision:int=Field(ge=1)
 action:Literal['refresh','submit_review','publish','cancel']
 confirmed:bool=False
 reason:str=Field(default='',max_length=2000)
 replacement:CloseCreate|None=None
class Mutation(BaseModel):id:str;revision:int
class BatchOut(BaseModel):
 id:str;revision:int;state:str;meta:dict;profile_id:str;source_id:str;columns:list[str];mapping:dict
 errors:list[dict];differences:dict;rows:list[dict];normalized:list[dict];actor_id:str;confirmed_by:str|None
class CloseOut(BaseModel):id:str;revision:int;state:str;inputs:dict;body:dict;publication_id:str|None
class PublishedOut(BaseModel):id:str;number:int;previous_id:str|None;body:dict;actor_id:str;at:str;is_current:bool
class BoardOut(BaseModel):
 can_finance:bool;can_summary:bool
 profiles:list[dict];calendars:list[dict];budgets:list[dict];files:list[FileOut];batches:list[BatchOut];closes:list[CloseOut];snapshots:list[PublishedOut];changes:list[dict]
