"""F5 trace identities and append-only facts."""
from sqlalchemy import String,Integer,JSON,Boolean,ForeignKey,ForeignKeyConstraint,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from .pilot_models import PilotBase,utcnow
class TraceTemplate(PilotBase):
    __tablename__='trace_templates'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    project_id:Mapped[str]=mapped_column(ForeignKey('pilot_projects.id'))
    name:Mapped[str]=mapped_column(String)
    scope:Mapped[str]=mapped_column(String)
    welding:Mapped[bool]=mapped_column(Boolean)
    pressure:Mapped[bool]=mapped_column(Boolean)
    basis:Mapped[str]=mapped_column(String)
    approved_by:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
    approved_at:Mapped[str]=mapped_column(String,default=utcnow)
class TraceOrder(PilotBase):
    __tablename__='trace_orders'
    __table_args__=(UniqueConstraint('id','project_id'),UniqueConstraint('project_id','code'),ForeignKeyConstraint(['version_id','project_id'],['handoff_versions.id','handoff_versions.project_id']))
    id:Mapped[str]=mapped_column(String,primary_key=True)
    project_id:Mapped[str]=mapped_column(String)
    version_id:Mapped[str]=mapped_column(String)
    code:Mapped[str]=mapped_column(String)
    pm_id:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
    factory_id:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
    site_id:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
    quality_id:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
    created_at:Mapped[str]=mapped_column(String,default=utcnow)
class Spool(PilotBase):
    __tablename__='trace_spools'
    __table_args__=(UniqueConstraint('id','project_id'),UniqueConstraint('project_id','code'),ForeignKeyConstraint(['order_id','project_id'],['trace_orders.id','trace_orders.project_id']))
    id:Mapped[str]=mapped_column(String,primary_key=True)
    project_id:Mapped[str]=mapped_column(String)
    order_id:Mapped[str]=mapped_column(String)
    template_id:Mapped[str]=mapped_column(ForeignKey('trace_templates.id'))
    code:Mapped[str]=mapped_column(String)
    revision:Mapped[int]=mapped_column(Integer,default=1)
    state:Mapped[str]=mapped_column(String,default='registered')
    parents:Mapped[list]=mapped_column(JSON,default=list)
    created_by:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
    created_at:Mapped[str]=mapped_column(String,default=utcnow)
    updated_at:Mapped[str]=mapped_column(String,default=utcnow)
class TraceWeld(PilotBase):
    __tablename__='trace_welds'
    __table_args__=(UniqueConstraint('project_id','code'),ForeignKeyConstraint(['spool_id','project_id'],['trace_spools.id','trace_spools.project_id']))
    id:Mapped[str]=mapped_column(String,primary_key=True)
    project_id:Mapped[str]=mapped_column(String)
    spool_id:Mapped[str]=mapped_column(String)
    code:Mapped[str]=mapped_column(String)
class TraceRecord(PilotBase):
    __tablename__='trace_records'
    __table_args__=(ForeignKeyConstraint(['spool_id','project_id'],['trace_spools.id','trace_spools.project_id']),)
    id:Mapped[str]=mapped_column(String,primary_key=True)
    project_id:Mapped[str]=mapped_column(String)
    spool_id:Mapped[str]=mapped_column(String)
    kind:Mapped[str]=mapped_column(String)
    data:Mapped[dict]=mapped_column(JSON)
    file_ids:Mapped[list]=mapped_column(JSON,default=list)
    source:Mapped[str]=mapped_column(String)
    occurred_at:Mapped[str]=mapped_column(String)
    received_at:Mapped[str]=mapped_column(String,default=utcnow)
    actor_id:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
    corrects_id:Mapped[str|None]=mapped_column(ForeignKey('trace_records.id'),nullable=True)
class TraceEvent(PilotBase):
    __tablename__='trace_events'
    __table_args__=(ForeignKeyConstraint(['spool_id','project_id'],['trace_spools.id','trace_spools.project_id']),)
    id:Mapped[str]=mapped_column(String,primary_key=True)
    project_id:Mapped[str]=mapped_column(String)
    spool_id:Mapped[str]=mapped_column(String)
    action:Mapped[str]=mapped_column(String)
    body:Mapped[dict]=mapped_column(JSON,default=dict)
    actor_id:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
    at:Mapped[str]=mapped_column(String,default=utcnow)
class TraceFile(PilotBase):
    __tablename__='trace_files'
    __table_args__=(ForeignKeyConstraint(['spool_id','project_id'],['trace_spools.id','trace_spools.project_id']),)
    id:Mapped[str]=mapped_column(String,primary_key=True)
    project_id:Mapped[str]=mapped_column(String)
    spool_id:Mapped[str]=mapped_column(String)
    name:Mapped[str]=mapped_column(String)
    sha256:Mapped[str]=mapped_column(String)
    size:Mapped[int]=mapped_column(Integer)
    media_type:Mapped[str]=mapped_column(String)
    path:Mapped[str]=mapped_column(String)
    created_by:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))

class TemplatePhoto(PilotBase):
    __tablename__='trace_template_photos'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    project_id:Mapped[str]=mapped_column(ForeignKey('pilot_projects.id'))
    name:Mapped[str]=mapped_column(String)
    sha256:Mapped[str]=mapped_column(String)
    size:Mapped[int]=mapped_column(Integer)
    media_type:Mapped[str]=mapped_column(String)
    path:Mapped[str]=mapped_column(String)
    created_by:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
    created_at:Mapped[str]=mapped_column(String,default=utcnow)
class TemplatePhotoLink(PilotBase):
    __tablename__='trace_template_photo_links'
    template_id:Mapped[str]=mapped_column(ForeignKey('trace_templates.id'),primary_key=True)
    photo_id:Mapped[str]=mapped_column(ForeignKey('trace_template_photos.id'),primary_key=True,unique=True)
    actor_id:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
    at:Mapped[str]=mapped_column(String,default=utcnow)
