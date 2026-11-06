from typing import Literal
from pydantic import BaseModel,Field
from .handoff_schemas import Strict,FileOut
class ChangeCreate(Strict):
    title:str=Field(min_length=1,max_length=120)
    reason:str=Field(min_length=1,max_length=2000)
    old_version_id:str;new_version_id:str
    emergency:bool=False
class ChangeAction(Strict):
    revision:int=Field(ge=1)
    action:Literal['impact','approval','publish','ack','plan','execute','verify','request_close','close','revise','cancel','wait']
    version_id:str|None=None
    category:Literal['technical','cost','schedule','quality']|None=None
    has_impact:bool|None=None
    reason:str=Field(default='',max_length=2000)
    target_keys:list[str]=Field(default_factory=list,max_length=500)
    file_ids:list[str]=Field(default_factory=list,max_length=20)
    approval_no:str=Field(default='',max_length=200)
    recipient_ids:list[str]=Field(default_factory=list,max_length=100)
    target_key:str|None=None
    decision:Literal['continue','rework','repair','scrap','cancel']|None=None
    replacement:ChangeCreate|None=None
    waiting:Literal['none','external_approval','external_delivery']='none'
class ChangeMutation(BaseModel):id:str;revision:int
class ChangeOut(BaseModel):
    id:str;project_id:str;revision:int;state:str;number:int;draft:dict;current:dict|None
    required_recipient_ids:list[str];files:list[dict];events:list[dict];versions:list[dict]
class ChangeBoard(BaseModel):cases:list[ChangeOut]

class ChangeFileOut(FileOut):
    restricted:bool
    purpose:str
    version_id:str|None
