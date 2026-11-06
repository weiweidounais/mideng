"""Project-scoped knowledge facts; legacy knowledge tables remain intact."""
from sqlalchemy import String,Integer,ForeignKey,JSON,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from .pilot_models import PilotBase,utcnow

class Library(PilotBase):
    __tablename__='knowledge_libraries'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    project_id:Mapped[str]=mapped_column(ForeignKey('pilot_projects.id'))
    owner_id:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
    name:Mapped[str]=mapped_column(String)
    readers:Mapped[list]=mapped_column(JSON,default=list)
    restricted:Mapped[bool]=mapped_column(default=True)
    revision:Mapped[int]=mapped_column(Integer,default=1)
    created_at:Mapped[str]=mapped_column(String,default=utcnow)

class KnowledgeDocument(PilotBase):
    __tablename__='knowledge_documents'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    project_id:Mapped[str]=mapped_column(ForeignKey('pilot_projects.id'))
    library_id:Mapped[str]=mapped_column(ForeignKey('knowledge_libraries.id'))
    actor_id:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
    name:Mapped[str]=mapped_column(String)
    path:Mapped[str]=mapped_column(String)
    sha256:Mapped[str]=mapped_column(String)
    size:Mapped[int]=mapped_column(Integer)
    state:Mapped[str]=mapped_column(String,default='queued')
    revision:Mapped[int]=mapped_column(Integer,default=1)
    chunks:Mapped[list]=mapped_column(JSON,default=list)
    warnings:Mapped[list]=mapped_column(JSON,default=list)
    error:Mapped[str]=mapped_column(String,default='')
    attempts:Mapped[int]=mapped_column(Integer,default=0)
    lease_until:Mapped[str|None]=mapped_column(String,nullable=True)
    created_at:Mapped[str]=mapped_column(String,default=utcnow)

class RuleApplication(PilotBase):
    __tablename__='knowledge_applications'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    project_id:Mapped[str]=mapped_column(ForeignKey('pilot_projects.id'))
    library_id:Mapped[str]=mapped_column(ForeignKey('knowledge_libraries.id'))
    actor_id:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
    revision:Mapped[int]=mapped_column(Integer,default=1)
    definition:Mapped[dict]=mapped_column(JSON)
    published:Mapped[dict|None]=mapped_column(JSON,nullable=True)
    versions:Mapped[list]=mapped_column(JSON,default=list)

class RuleRun(PilotBase):
    __tablename__='knowledge_runs'
    id:Mapped[str]=mapped_column(String,primary_key=True)
    project_id:Mapped[str]=mapped_column(ForeignKey('pilot_projects.id'))
    library_id:Mapped[str]=mapped_column(ForeignKey('knowledge_libraries.id'))
    application_id:Mapped[str]=mapped_column(ForeignKey('knowledge_applications.id'))
    actor_id:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
    result:Mapped[dict]=mapped_column(JSON)
    created_at:Mapped[str]=mapped_column(String,default=utcnow)
