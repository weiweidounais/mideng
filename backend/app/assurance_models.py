"""Versioned contracts, durable exceptions and scoped export jobs."""
from sqlalchemy import String,Integer,JSON,ForeignKey,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from .pilot_models import PilotBase,utcnow
class DataContract(PilotBase):
 __tablename__='assurance_contracts'
 id:Mapped[str]=mapped_column(String,primary_key=True)
 name:Mapped[str]=mapped_column(String)
 version:Mapped[int]=mapped_column(Integer)
 body:Mapped[dict]=mapped_column(JSON)
 effective_at:Mapped[str]=mapped_column(String,default=utcnow)
class ExceptionCase(PilotBase):
 __tablename__='assurance_exceptions'
 __table_args__=(UniqueConstraint('project_id','object_id','source_version','rule_id'),)
 id:Mapped[str]=mapped_column(String,primary_key=True)
 project_id:Mapped[str]=mapped_column(ForeignKey('pilot_projects.id'))
 object_id:Mapped[str]=mapped_column(String)
 source_version:Mapped[str]=mapped_column(String)
 source_kind:Mapped[str]=mapped_column(String)
 rule_id:Mapped[str]=mapped_column(String)
 rule_version:Mapped[int]=mapped_column(Integer,default=1)
 owner_id:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
 title:Mapped[str]=mapped_column(String)
 financial:Mapped[int]=mapped_column(Integer,default=0)
 state:Mapped[str]=mapped_column(String,default='open')
 revision:Mapped[int]=mapped_column(Integer,default=1)
 detected_at:Mapped[str]=mapped_column(String,default=utcnow)
 due_at:Mapped[str|None]=mapped_column(String,nullable=True)
 resolved_at:Mapped[str|None]=mapped_column(String,nullable=True)
 waiver_until:Mapped[str|None]=mapped_column(String,nullable=True)
 waiver:Mapped[dict]=mapped_column(JSON,default=dict)
class ExceptionEvent(PilotBase):
 __tablename__='assurance_events'
 id:Mapped[str]=mapped_column(String,primary_key=True)
 project_id:Mapped[str]=mapped_column(ForeignKey('pilot_projects.id'))
 exception_id:Mapped[str]=mapped_column(ForeignKey('assurance_exceptions.id'))
 actor_id:Mapped[str|None]=mapped_column(ForeignKey('pilot_accounts.id'),nullable=True)
 action:Mapped[str]=mapped_column(String)
 body:Mapped[dict]=mapped_column(JSON,default=dict)
 at:Mapped[str]=mapped_column(String,default=utcnow)
class ExceptionFile(PilotBase):
 __tablename__='assurance_files'
 id:Mapped[str]=mapped_column(String,primary_key=True)
 project_id:Mapped[str]=mapped_column(ForeignKey('pilot_projects.id'))
 exception_id:Mapped[str]=mapped_column(ForeignKey('assurance_exceptions.id'))
 name:Mapped[str]=mapped_column(String)
 sha256:Mapped[str]=mapped_column(String)
 size:Mapped[int]=mapped_column(Integer)
 path:Mapped[str]=mapped_column(String)
 media_type:Mapped[str]=mapped_column(String)
 created_by:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
class EvidenceExport(PilotBase):
 __tablename__='assurance_exports'
 id:Mapped[str]=mapped_column(String,primary_key=True)
 project_id:Mapped[str]=mapped_column(ForeignKey('pilot_projects.id'))
 actor_id:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
 roles:Mapped[list]=mapped_column(JSON)
 include_sensitive:Mapped[int]=mapped_column(Integer,default=0)
 state:Mapped[str]=mapped_column(String,default='queued')
 revision:Mapped[int]=mapped_column(Integer,default=1)
 claim_id:Mapped[str|None]=mapped_column(String,nullable=True)
 lease_until:Mapped[str|None]=mapped_column(String,nullable=True)
 attempts:Mapped[int]=mapped_column(Integer,default=0)
 path:Mapped[str|None]=mapped_column(String,nullable=True)
 sha256:Mapped[str|None]=mapped_column(String,nullable=True)
 error:Mapped[str]=mapped_column(String,default='')
 at:Mapped[str]=mapped_column(String,default=utcnow)
 completed_at:Mapped[str|None]=mapped_column(String,nullable=True)
