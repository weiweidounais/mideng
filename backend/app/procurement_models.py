"""V2 procurement workflow; existing V1 handoff facts remain untouched."""
from sqlalchemy import String,Integer,JSON,ForeignKey,ForeignKeyConstraint,UniqueConstraint,Boolean
from sqlalchemy.orm import Mapped,mapped_column
from .pilot_models import PilotBase,utcnow

class PurchaseOrder(PilotBase):
    __tablename__='procurement_orders'
    __table_args__=(UniqueConstraint('id','project_id'),UniqueConstraint('version_id','project_id'),ForeignKeyConstraint(['version_id','project_id'],['handoff_versions.id','handoff_versions.project_id']))
    id:Mapped[str]=mapped_column(String,primary_key=True)
    project_id:Mapped[str]=mapped_column(ForeignKey('pilot_projects.id'))
    version_id:Mapped[str]=mapped_column(String)
    revision:Mapped[int]=mapped_column(Integer,default=1)
    state:Mapped[str]=mapped_column(String,default='requested')
    title:Mapped[str]=mapped_column(String)
    note:Mapped[str]=mapped_column(String)
    pm_id:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
    purchase_id:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
    quality_id:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
    commerce_id:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
    lines:Mapped[list]=mapped_column(JSON)
    result:Mapped[dict|None]=mapped_column(JSON,nullable=True)
    arrivals:Mapped[list]=mapped_column(JSON,default=list)
    archive:Mapped[dict|None]=mapped_column(JSON,nullable=True)
    due_at:Mapped[str]=mapped_column(String)
    created_at:Mapped[str]=mapped_column(String,default=utcnow)
    updated_at:Mapped[str]=mapped_column(String,default=utcnow)

class PurchaseEvent(PilotBase):
    __tablename__='procurement_events'
    __table_args__=(ForeignKeyConstraint(['order_id','project_id'],['procurement_orders.id','procurement_orders.project_id']),)
    id:Mapped[str]=mapped_column(String,primary_key=True)
    project_id:Mapped[str]=mapped_column(String)
    order_id:Mapped[str]=mapped_column(String)
    action:Mapped[str]=mapped_column(String)
    actor_id:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
    body:Mapped[dict]=mapped_column(JSON)
    at:Mapped[str]=mapped_column(String,default=utcnow)

class PurchaseFile(PilotBase):
    __tablename__='procurement_files'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    project_id:Mapped[str]=mapped_column(ForeignKey('pilot_projects.id'))
    order_id:Mapped[str]=mapped_column(ForeignKey('procurement_orders.id'))
    purpose:Mapped[str]=mapped_column(String)
    name:Mapped[str]=mapped_column(String)
    sha256:Mapped[str]=mapped_column(String)
    size:Mapped[int]=mapped_column(Integer)
    media_type:Mapped[str]=mapped_column(String)
    path:Mapped[str]=mapped_column(String)
    created_by:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
