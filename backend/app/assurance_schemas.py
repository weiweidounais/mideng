from datetime import datetime,timezone
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,field_validator
class Strict(BaseModel):model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
class ExceptionAction(Strict):
 revision:int=Field(ge=1)
 action:Literal['assign','read','remind','waive','recheck']
 owner_id:str|None=None
 reason:str=Field(default='',max_length=2000)
 approval_no:str=Field(default='',max_length=200)
 until:datetime|None=None
 file_ids:list[str]=Field(default_factory=list,max_length=10)
 @field_validator('until')
 @classmethod
 def aware(cls,v):
  if v and v.tzinfo is None:raise ValueError('期限须含时区')
  return v.astimezone(timezone.utc) if v else None
class ExportCreate(Strict):
 confirmed:bool=False
 include_sensitive:bool=False
 reason:str=Field(min_length=1,max_length=2000)
class Mutation(BaseModel):id:str;revision:int
class ContractOut(BaseModel):id:str;name:str;version:int;body:dict;effective_at:str
class ExceptionOut(BaseModel):
 id:str;object_id:str;source_version:str;source_kind:str;rule_id:str;rule_version:int;owner_id:str;title:str;financial:bool;state:str;revision:int;detected_at:str;due_at:str|None;resolved_at:str|None;waiver_until:str|None;waiver:dict;events:list[dict];files:list[dict];can_manage:bool
class ExportOut(BaseModel):id:str;state:str;revision:int;include_sensitive:bool;error:str;at:str;completed_at:str|None;sha256:str|None
class BoardOut(BaseModel):exceptions:list[ExceptionOut];exports:list[ExportOut];contracts:list[ContractOut]
