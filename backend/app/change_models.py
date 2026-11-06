from sqlalchemy import String,Integer,JSON,Boolean,ForeignKey,ForeignKeyConstraint,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from .pilot_models import PilotBase,utcnow
class ChangeCase(PilotBase):
    __tablename__='change_cases'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    project_id:Mapped[str]=mapped_column(ForeignKey('pilot_projects.id'))
    revision:Mapped[int]=mapped_column(Integer,default=1)
    number:Mapped[int]=mapped_column(Integer,default=0)
    state:Mapped[str]=mapped_column(String,default='analysis')
    draft:Mapped[dict]=mapped_column(JSON)
    current_version_id:Mapped[str|None]=mapped_column(String,nullable=True)
    created_by:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
    updated_at:Mapped[str]=mapped_column(String,default=utcnow)
class ChangeVersion(PilotBase):
    __tablename__='change_versions'
    __table_args__=(UniqueConstraint('case_id','number'),)
    id:Mapped[str]=mapped_column(String,primary_key=True)
    project_id:Mapped[str]=mapped_column(ForeignKey('pilot_projects.id'))
    case_id:Mapped[str]=mapped_column(ForeignKey('change_cases.id'))
    number:Mapped[int]=mapped_column(Integer)
    body:Mapped[dict]=mapped_column(JSON)
    published_at:Mapped[str]=mapped_column(String,default=utcnow)
class ChangeAck(PilotBase):
    __tablename__='change_acks'
    __table_args__=(UniqueConstraint('version_id','actor_id'),)
    id:Mapped[str]=mapped_column(String,primary_key=True)
    version_id:Mapped[str]=mapped_column(ForeignKey('change_versions.id'))
    actor_id:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
    at:Mapped[str]=mapped_column(String,default=utcnow)
class ChangeDisposition(PilotBase):
    __tablename__='change_dispositions'
    __table_args__=(UniqueConstraint('version_id','target_key'),)
    id:Mapped[str]=mapped_column(String,primary_key=True)
    project_id:Mapped[str]=mapped_column(ForeignKey('pilot_projects.id'))
    version_id:Mapped[str]=mapped_column(ForeignKey('change_versions.id'))
    target_key:Mapped[str]=mapped_column(String)
    decision:Mapped[str]=mapped_column(String)
    executor_id:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
    reason:Mapped[str]=mapped_column(String)
    file_ids:Mapped[list]=mapped_column(JSON,default=list)
    submitted_at:Mapped[str|None]=mapped_column(String,nullable=True)
    verified_at:Mapped[str|None]=mapped_column(String,nullable=True)
    verified_by:Mapped[str|None]=mapped_column(String,nullable=True)
class ChangeEvent(PilotBase):
    __tablename__='change_events'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    project_id:Mapped[str]=mapped_column(ForeignKey('pilot_projects.id'))
    case_id:Mapped[str]=mapped_column(ForeignKey('change_cases.id'))
    actor_id:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
    action:Mapped[str]=mapped_column(String)
    body:Mapped[dict]=mapped_column(JSON)
    at:Mapped[str]=mapped_column(String,default=utcnow)
class ChangeFile(PilotBase):
    __tablename__='change_files'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    project_id:Mapped[str]=mapped_column(ForeignKey('pilot_projects.id'))
    case_id:Mapped[str]=mapped_column(ForeignKey('change_cases.id'))
    version_id:Mapped[str|None]=mapped_column(String,nullable=True)
    purpose:Mapped[str]=mapped_column(String)
    restricted:Mapped[bool]=mapped_column(Boolean,default=False)
    name:Mapped[str]=mapped_column(String)
    sha256:Mapped[str]=mapped_column(String)
    size:Mapped[int]=mapped_column(Integer)
    media_type:Mapped[str]=mapped_column(String)
    path:Mapped[str]=mapped_column(String)
    created_by:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
