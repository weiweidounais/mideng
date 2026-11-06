from datetime import datetime,timezone
from typing import Literal
from pydantic import BaseModel,Field,field_validator,ConfigDict
from .handoff_schemas import FileOut
class Strict(BaseModel):model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
Code=str
class PhotoIds(Strict):
    photo_ids:list[str]=Field(default_factory=list,max_length=10)
    @field_validator('photo_ids')
    @classmethod
    def unique_photos(cls,v):
        if len(v)!=len(set(v)):raise ValueError('照片不可重复')
        return v
class TemplateCreate(PhotoIds):
    name:str=Field(min_length=1,max_length=120)
    scope:str=Field(min_length=1,max_length=2000)
    welding:bool
    pressure:bool
    basis:str=Field(min_length=1,max_length=2000)
class OrderCreate(Strict):
    code:str=Field(min_length=1,max_length=80,pattern=r'^[a-zA-Z0-9_.-]+$')
    version_id:str
    factory_id:str;site_id:str;quality_id:str
class SpoolCreate(Strict):
    code:str=Field(min_length=1,max_length=80,pattern=r'^[a-zA-Z0-9_.-]+$')
    order_id:str;template_id:str
class FactData(Strict):
    batch:str=Field(default='',max_length=200)
    equipment:str=Field(default='',max_length=200)
    weld_code:str=Field(default='',max_length=80)
    welder_code:str=Field(default='',max_length=200)
    consumable_batch:str=Field(default='',max_length=200)
    location:str=Field(default='',max_length=500)
    description:str=Field(default='',max_length=2000)
    reference:str=Field(default='',max_length=500)
class RecordCreate(Strict):
    revision:int=Field(ge=1)
    kind:Literal['material','weld','fabrication','repair','pressure']
    data:FactData
    file_ids:list[str]=Field(default_factory=list,max_length=30)
    source:Literal['manual','template_import']='manual'
    occurred_at:datetime
    corrects_id:str|None=None
    correction_reason:str=Field(default='',max_length=2000)
    @field_validator('occurred_at')
    @classmethod
    def real_time(cls,v):
        if v.tzinfo is None or v>datetime.now(timezone.utc):raise ValueError('发生时间须含时区且不能晚于现在')
        return v.astimezone(timezone.utc)
class SpoolAction(Strict):
    revision:int=Field(ge=1)
    action:Literal['start','submit_inspection','inspect','ship','install','confirm_pressure','complete','scrap','label']
    reason:str=Field(default='',max_length=2000)
    passed:bool|None=None
    file_ids:list[str]=Field(default_factory=list,max_length=30)
    weld_ids:list[str]=Field(default_factory=list,max_length=500)
    location:str=Field(default='',max_length=500)
    reference:str=Field(default='',max_length=500)
    occurred_at:datetime|None=None
    @field_validator('occurred_at')
    @classmethod
    def real_time(cls,v):return RecordCreate.real_time(v) if v else None
class Parent(Strict):id:str;revision:int=Field(ge=1)
class Reshape(Strict):
    parents:list[Parent]=Field(min_length=1,max_length=20)
    codes:list[str]=Field(min_length=1,max_length=20)
    reason:str=Field(min_length=1,max_length=2000)
    @field_validator('codes')
    @classmethod
    def codes_valid(cls,vs):
        import re
        if len(set(vs))!=len(vs) or any(not re.fullmatch(r'[a-zA-Z0-9_.-]{1,80}',v) for v in vs):raise ValueError('编码须有效且不可重复')
        return vs
class Mutation(BaseModel):id:str;revision:int
class ReshapeOut(BaseModel):ids:list[str]
class TemplatePhotoOut(FileOut):linked_by:str;linked_at:str
class TemplateOut(TemplateCreate):
    id:str;approved_by:str;approved_at:str
    photos:list[TemplatePhotoOut]=Field(default_factory=list)
class OrderOut(OrderCreate):id:str;pm_id:str;created_at:str
class RecordOut(BaseModel):
    id:str;kind:str;data:dict;file_ids:list[str];source:str;occurred_at:str;received_at:str;actor_id:str;corrects_id:str|None
class SpoolOut(BaseModel):
    id:str;project_id:str;order_id:str;template_id:str;code:str;revision:int;state:str;parents:list[str];children:list[str]
    records:list[RecordOut];events:list[dict];welds:list[dict];files:list[FileOut]
    missing:list[str];source_ok:bool;source_status:str;owner_id:str;change_id:str|None
class TraceBoard(BaseModel):templates:list[TemplateOut];orders:list[OrderOut];spools:list[SpoolOut];metrics:dict
class LabelOut(BaseModel):id:str;revision:int;locator:str
