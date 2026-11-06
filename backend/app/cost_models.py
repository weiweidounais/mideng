"""F6 financial facts, persistent import jobs and immutable publications."""
from sqlalchemy import String,Integer,JSON,ForeignKey,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from .pilot_models import PilotBase,utcnow
class CostProfile(PilotBase):
 __tablename__='cost_profiles'
 __table_args__=(UniqueConstraint('project_id','source_system','number'),)
 id:Mapped[str]=mapped_column(String,primary_key=True)
 project_id:Mapped[str]=mapped_column(ForeignKey('pilot_projects.id'))
 source_system:Mapped[str]=mapped_column(String)
 number:Mapped[int]=mapped_column(Integer)
 body:Mapped[dict]=mapped_column(JSON)
 actor_id:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
 at:Mapped[str]=mapped_column(String,default=utcnow)
class CostSource(PilotBase):
 __tablename__='cost_sources'
 id:Mapped[str]=mapped_column(String,primary_key=True)
 project_id:Mapped[str]=mapped_column(ForeignKey('pilot_projects.id'))
 purpose:Mapped[str]=mapped_column(String)
 name:Mapped[str]=mapped_column(String)
 sha256:Mapped[str]=mapped_column(String)
 size:Mapped[int]=mapped_column(Integer)
 media_type:Mapped[str]=mapped_column(String)
 path:Mapped[str]=mapped_column(String)
 actor_id:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
 at:Mapped[str]=mapped_column(String,default=utcnow)
class CostBatch(PilotBase):
 __tablename__='cost_batches'
 id:Mapped[str]=mapped_column(String,primary_key=True)
 project_id:Mapped[str]=mapped_column(ForeignKey('pilot_projects.id'))
 source_id:Mapped[str]=mapped_column(ForeignKey('cost_sources.id'))
 profile_id:Mapped[str]=mapped_column(ForeignKey('cost_profiles.id'))
 revision:Mapped[int]=mapped_column(Integer,default=1)
 state:Mapped[str]=mapped_column(String,default='queued_parse')
 meta:Mapped[dict]=mapped_column(JSON)
 columns:Mapped[list]=mapped_column(JSON,default=list)
 rows:Mapped[list]=mapped_column(JSON,default=list)
 mapping:Mapped[dict]=mapped_column(JSON,default=dict)
 normalized:Mapped[list]=mapped_column(JSON,default=list)
 errors:Mapped[list]=mapped_column(JSON,default=list)
 differences:Mapped[dict]=mapped_column(JSON,default=dict)
 checked_generation:Mapped[int|None]=mapped_column(Integer,nullable=True)
 claim_id:Mapped[str|None]=mapped_column(String,nullable=True)
 lease_until:Mapped[str|None]=mapped_column(String,nullable=True)
 attempts:Mapped[int]=mapped_column(Integer,default=0)
 actor_id:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
 confirmed_by:Mapped[str|None]=mapped_column(ForeignKey('pilot_accounts.id'),nullable=True)
 at:Mapped[str]=mapped_column(String,default=utcnow)
 updated_at:Mapped[str]=mapped_column(String,default=utcnow)
class CostLine(PilotBase):
 __tablename__='cost_lines'
 __table_args__=(UniqueConstraint('project_id','source_system','source_key','period','line_version'),)
 id:Mapped[str]=mapped_column(String,primary_key=True)
 project_id:Mapped[str]=mapped_column(ForeignKey('pilot_projects.id'))
 source_system:Mapped[str]=mapped_column(String)
 source_key:Mapped[str]=mapped_column(String)
 period:Mapped[str]=mapped_column(String)
 line_version:Mapped[str]=mapped_column(String)
 digest:Mapped[str]=mapped_column(String)
 body:Mapped[dict]=mapped_column(JSON)
class CostBatchLine(PilotBase):
 __tablename__='cost_batch_lines'
 batch_id:Mapped[str]=mapped_column(ForeignKey('cost_batches.id'),primary_key=True)
 line_id:Mapped[str]=mapped_column(ForeignKey('cost_lines.id'),primary_key=True)
class CostBook(PilotBase):
 __tablename__='cost_books'
 project_id:Mapped[str]=mapped_column(ForeignKey('pilot_projects.id'),primary_key=True)
 revision:Mapped[int]=mapped_column(Integer,default=1)
class CostBudget(PilotBase):
 __tablename__='cost_budgets'
 id:Mapped[str]=mapped_column(String,primary_key=True)
 project_id:Mapped[str]=mapped_column(ForeignKey('pilot_projects.id'))
 body:Mapped[dict]=mapped_column(JSON)
 actor_id:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
 at:Mapped[str]=mapped_column(String,default=utcnow)
class CostCalendar(PilotBase):
 __tablename__='cost_calendars'
 id:Mapped[str]=mapped_column(String,primary_key=True)
 project_id:Mapped[str]=mapped_column(ForeignKey('pilot_projects.id'))
 body:Mapped[dict]=mapped_column(JSON)
 actor_id:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
 at:Mapped[str]=mapped_column(String,default=utcnow)
class CostClose(PilotBase):
 __tablename__='cost_closes'
 id:Mapped[str]=mapped_column(String,primary_key=True)
 project_id:Mapped[str]=mapped_column(ForeignKey('pilot_projects.id'))
 revision:Mapped[int]=mapped_column(Integer,default=1)
 state:Mapped[str]=mapped_column(String,default='draft')
 inputs:Mapped[dict]=mapped_column(JSON)
 body:Mapped[dict]=mapped_column(JSON)
 generation:Mapped[int]=mapped_column(Integer)
 publication_id:Mapped[str|None]=mapped_column(String,nullable=True)
 actor_id:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
 at:Mapped[str]=mapped_column(String,default=utcnow)
 updated_at:Mapped[str]=mapped_column(String,default=utcnow)
class CostSnapshot(PilotBase):
 __tablename__='cost_snapshots'
 __table_args__=(UniqueConstraint('project_id','period','currency','tax_basis','number'),)
 id:Mapped[str]=mapped_column(String,primary_key=True)
 project_id:Mapped[str]=mapped_column(ForeignKey('pilot_projects.id'))
 close_id:Mapped[str]=mapped_column(ForeignKey('cost_closes.id'))
 period:Mapped[str]=mapped_column(String)
 currency:Mapped[str]=mapped_column(String)
 tax_basis:Mapped[str]=mapped_column(String)
 number:Mapped[int]=mapped_column(Integer)
 previous_id:Mapped[str|None]=mapped_column(ForeignKey('cost_snapshots.id'),nullable=True)
 body:Mapped[dict]=mapped_column(JSON)
 actor_id:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
 at:Mapped[str]=mapped_column(String,default=utcnow)
class CostEvent(PilotBase):
 __tablename__='cost_events'
 id:Mapped[str]=mapped_column(String,primary_key=True)
 project_id:Mapped[str]=mapped_column(ForeignKey('pilot_projects.id'))
 object_id:Mapped[str]=mapped_column(String)
 action:Mapped[str]=mapped_column(String)
 body:Mapped[dict]=mapped_column(JSON,default=dict)
 actor_id:Mapped[str]=mapped_column(ForeignKey('pilot_accounts.id'))
 at:Mapped[str]=mapped_column(String,default=utcnow)
