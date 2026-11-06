"""Versioned business records, all linked through project-scoped foreign keys."""
from sqlalchemy import String, Integer, Boolean, JSON, ForeignKey, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .pilot_models import PilotBase, utcnow


class Document(PilotBase):
    __tablename__ = 'handoff_documents'
    __table_args__ = (UniqueConstraint('id','project_id'),
        ForeignKeyConstraint(['parent_id','project_id'],['handoff_documents.id','handoff_documents.project_id']),
        ForeignKeyConstraint(['source_version_id','project_id'],['handoff_versions.id','handoff_versions.project_id']))
    id: Mapped[str] = mapped_column(String,primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey('pilot_projects.id'))
    kind: Mapped[str] = mapped_column(String)
    parent_id: Mapped[str|None] = mapped_column(String,nullable=True)
    source_version_id: Mapped[str|None] = mapped_column(String,nullable=True)
    draft: Mapped[dict] = mapped_column(JSON)
    withdrawn_versions: Mapped[list] = mapped_column(JSON,default=list)
    has_draft: Mapped[bool] = mapped_column(Boolean,default=True)
    revision: Mapped[int] = mapped_column(Integer,default=1)
    version_no: Mapped[int] = mapped_column(Integer,default=0)
    created_by: Mapped[str] = mapped_column(ForeignKey('pilot_accounts.id'))
    updated_by: Mapped[str] = mapped_column(ForeignKey('pilot_accounts.id'))
    created_at: Mapped[str] = mapped_column(String,default=utcnow)
    updated_at: Mapped[str] = mapped_column(String,default=utcnow)


class Version(PilotBase):
    __tablename__ = 'handoff_versions'
    __table_args__ = (UniqueConstraint('document_id','number'),UniqueConstraint('id','project_id'),
        ForeignKeyConstraint(['document_id','project_id'],['handoff_documents.id','handoff_documents.project_id']),
        ForeignKeyConstraint(['source_version_id','project_id'],['handoff_versions.id','handoff_versions.project_id']))
    id: Mapped[str] = mapped_column(String,primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey('pilot_projects.id'))
    document_id: Mapped[str] = mapped_column(String)
    source_version_id: Mapped[str|None] = mapped_column(String,nullable=True)
    previous_id: Mapped[str|None] = mapped_column(ForeignKey('handoff_versions.id'),nullable=True)
    number: Mapped[int] = mapped_column(Integer)
    body: Mapped[dict] = mapped_column(JSON)
    attachments: Mapped[list] = mapped_column(JSON)
    recipients: Mapped[list] = mapped_column(JSON)
    diff_summary: Mapped[str] = mapped_column(String)
    published_by: Mapped[str] = mapped_column(ForeignKey('pilot_accounts.id'))
    published_at: Mapped[str] = mapped_column(String,default=utcnow)


class Attachment(PilotBase):
    __tablename__ = 'handoff_files'
    id: Mapped[str] = mapped_column(String,primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey('pilot_projects.id'))
    kind: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    media_type: Mapped[str] = mapped_column(String)
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String)
    created_by: Mapped[str] = mapped_column(ForeignKey('pilot_accounts.id'))
    created_at: Mapped[str] = mapped_column(String,default=utcnow)


class Contract(PilotBase):
    __tablename__ = 'handoff_contracts'
    __table_args__ = (UniqueConstraint('id','project_id'),
        ForeignKeyConstraint(['version_id','project_id'],['handoff_versions.id','handoff_versions.project_id']))
    id: Mapped[str] = mapped_column(String,primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey('pilot_projects.id'))
    version_id: Mapped[str] = mapped_column(String)
    recipient_id: Mapped[str] = mapped_column(ForeignKey('pilot_accounts.id'))
    proxies: Mapped[list] = mapped_column(JSON,default=list)
    created_by: Mapped[str] = mapped_column(ForeignKey('pilot_accounts.id'))
    deliverable: Mapped[str] = mapped_column(String)
    quality_rule: Mapped[str] = mapped_column(String)
    require_arrival: Mapped[bool] = mapped_column(Boolean,default=False)
    sla_hours: Mapped[int] = mapped_column(Integer)
    triggered_at: Mapped[str] = mapped_column(String)
    original_due_at: Mapped[str] = mapped_column(String)
    due_at: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String,default='draft')
    paused_at: Mapped[str|None] = mapped_column(String,nullable=True)
    pause_seconds: Mapped[int] = mapped_column(Integer,default=0)
    return_count: Mapped[int] = mapped_column(Integer,default=0)
    revision: Mapped[int] = mapped_column(Integer,default=1)
    updated_by: Mapped[str] = mapped_column(ForeignKey('pilot_accounts.id'))
    created_at: Mapped[str] = mapped_column(String,default=utcnow)
    updated_at: Mapped[str] = mapped_column(String,default=utcnow)


class MaterialRow(PilotBase):
    __tablename__ = 'handoff_rows'
    __table_args__ = (UniqueConstraint('id','project_id'),UniqueConstraint('contract_id','line_no'),
        ForeignKeyConstraint(['contract_id','project_id'],['handoff_contracts.id','handoff_contracts.project_id']))
    id: Mapped[str] = mapped_column(String,primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey('pilot_projects.id'))
    contract_id: Mapped[str] = mapped_column(String)
    line_no: Mapped[int] = mapped_column(Integer)
    material: Mapped[str] = mapped_column(String)
    spec: Mapped[str] = mapped_column(String)
    quantity: Mapped[str] = mapped_column(String)
    unit: Mapped[str] = mapped_column(String)
    need_by: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String,default='pending')
    eta: Mapped[str|None] = mapped_column(String,nullable=True)
    blocked: Mapped[bool] = mapped_column(Boolean,default=False)
    note: Mapped[str] = mapped_column(String,default='')
    revision: Mapped[int] = mapped_column(Integer,default=1)
    created_by: Mapped[str] = mapped_column(ForeignKey('pilot_accounts.id'))
    updated_by: Mapped[str] = mapped_column(ForeignKey('pilot_accounts.id'))
    created_at: Mapped[str] = mapped_column(String,default=utcnow)
    updated_at: Mapped[str] = mapped_column(String,default=utcnow)


class Arrival(PilotBase):
    __tablename__ = 'handoff_arrivals'
    __table_args__ = (ForeignKeyConstraint(['row_id','project_id'],['handoff_rows.id','handoff_rows.project_id']),)
    id: Mapped[str] = mapped_column(String,primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey('pilot_projects.id'))
    row_id: Mapped[str] = mapped_column(String)
    quantity: Mapped[str] = mapped_column(String)
    occurred_at: Mapped[str] = mapped_column(String)
    created_by: Mapped[str] = mapped_column(ForeignKey('pilot_accounts.id'))
    created_at: Mapped[str] = mapped_column(String,default=utcnow)


class BusinessEvent(PilotBase):
    __tablename__ = 'handoff_events'
    id: Mapped[str] = mapped_column(String,primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey('pilot_projects.id'))
    object_id: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    body: Mapped[dict] = mapped_column(JSON)
    actor_id: Mapped[str] = mapped_column(ForeignKey('pilot_accounts.id'))
    at: Mapped[str] = mapped_column(String,default=utcnow)


class Issue(PilotBase):
    __tablename__ = 'handoff_issues'
    __table_args__ = (UniqueConstraint('project_id','object_id','rule'),)
    id: Mapped[str] = mapped_column(String,primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey('pilot_projects.id'))
    object_id: Mapped[str] = mapped_column(String)
    rule: Mapped[str] = mapped_column(String)
    owner_id: Mapped[str] = mapped_column(ForeignKey('pilot_accounts.id'))
    title: Mapped[str] = mapped_column(String)
    active: Mapped[bool] = mapped_column(Boolean,default=True)
    detected_at: Mapped[str] = mapped_column(String,default=utcnow)
    closed_at: Mapped[str|None] = mapped_column(String,nullable=True)
