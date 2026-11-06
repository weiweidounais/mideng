"""Typed, project-scoped foundation tables; legacy knowledge schema is preserved."""
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Boolean, ForeignKey, UniqueConstraint, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow():
    return datetime.now(timezone.utc).isoformat()


class PilotBase(DeclarativeBase):
    pass


class Account(PilotBase):
    __tablename__ = 'pilot_accounts'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    display_name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Session(PilotBase):
    __tablename__ = 'pilot_sessions'
    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey('pilot_accounts.id'))
    csrf: Mapped[str] = mapped_column(String)
    expires_at: Mapped[str] = mapped_column(String)


class Project(PilotBase):
    __tablename__ = 'pilot_projects'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    owner_id: Mapped[str] = mapped_column(ForeignKey('pilot_accounts.id'))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class Membership(PilotBase):
    __tablename__ = 'pilot_memberships'
    __table_args__ = (UniqueConstraint('project_id', 'account_id'),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey('pilot_projects.id'))
    account_id: Mapped[str] = mapped_column(ForeignKey('pilot_accounts.id'))
    roles: Mapped[list] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    valid_from: Mapped[str] = mapped_column(String)
    valid_until: Mapped[str | None] = mapped_column(String, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class Audit(PilotBase):
    __tablename__ = 'pilot_audit'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey('pilot_projects.id'), nullable=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey('pilot_accounts.id'))
    action: Mapped[str] = mapped_column(String)
    actor_roles: Mapped[list] = mapped_column(JSON, default=list)
    object_id: Mapped[str] = mapped_column(String)
    revision: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[str] = mapped_column(String)
    at: Mapped[str] = mapped_column(String, default=utcnow)


class Idempotency(PilotBase):
    __tablename__ = 'pilot_idempotency'
    __table_args__ = (UniqueConstraint('actor_id', 'action', 'key'),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey('pilot_accounts.id'))
    action: Mapped[str] = mapped_column(String)
    key: Mapped[str] = mapped_column(String(100))
    digest: Mapped[str] = mapped_column(String)
    result: Mapped[dict] = mapped_column(JSON)


class Outbox(PilotBase):
    __tablename__ = 'pilot_outbox'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey('pilot_projects.id'))
    recipient_id: Mapped[str] = mapped_column(ForeignKey('pilot_accounts.id'))
    title: Mapped[str] = mapped_column(String)
    target_kind: Mapped[str|None] = mapped_column(String,nullable=True)
    target_id: Mapped[str|None] = mapped_column(String,nullable=True)
    version_id: Mapped[str|None] = mapped_column(String,nullable=True)
    state: Mapped[str] = mapped_column(String, default='pending')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[str] = mapped_column(String, default=utcnow)


class Todo(PilotBase):
    __tablename__ = 'pilot_todos'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey('pilot_outbox.id'), unique=True)
    project_id: Mapped[str] = mapped_column(ForeignKey('pilot_projects.id'))
    recipient_id: Mapped[str] = mapped_column(ForeignKey('pilot_accounts.id'))
    title: Mapped[str] = mapped_column(String)
    target_kind: Mapped[str|None] = mapped_column(String,nullable=True)
    target_id: Mapped[str|None] = mapped_column(String,nullable=True)
    version_id: Mapped[str|None] = mapped_column(String,nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
