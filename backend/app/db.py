from contextlib import contextmanager
from datetime import datetime, timezone
from sqlalchemy import create_engine, String, JSON, DateTime, Index, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from fastapi import HTTPException
from .config import config

class Base(DeclarativeBase): pass

class Entity(Base):
    __tablename__ = "entities"
    kind: Mapped[str] = mapped_column(String(30), primary_key=True)
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)
    owner: Mapped[str | None] = mapped_column(String(100), nullable=True)
    parent_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda:datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda:datetime.now(timezone.utc))
    __table_args__ = (Index("ix_entity_scope", "kind", "parent_id", "owner"),)

class Credential(Base):
    __tablename__ = "credentials"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    encrypted: Mapped[str] = mapped_column(String, default="")

class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20))
    csrf: Mapped[str] = mapped_column(String(100))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

engine = create_engine(config.sql_url, connect_args={"check_same_thread":False,"timeout":30} if config.sql_url.startswith("sqlite") else {}, pool_pre_ping=True,pool_size=12,max_overflow=8)
SessionLocal = sessionmaker(engine, expire_on_commit=False)
def init_db():
    from pathlib import Path
    from alembic import command
    from alembic.config import Config as AlembicConfig
    root = Path(__file__).resolve().parents[1]
    migration = AlembicConfig(str(root / "alembic.ini"))
    migration.set_main_option("script_location", str(root / "migrations"))
    with engine.begin() as connection:
        migration.attributes["connection"] = connection
        command.upgrade(migration, "head")
    if config.sql_url.startswith("sqlite"):
        with engine.connect() as c:
            c.exec_driver_sql("PRAGMA journal_mode=WAL")

@contextmanager
def db_session():
    with SessionLocal() as db:
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise

def get_entity(db, kind:str, id:str, required=True):
    row=db.get(Entity,(kind,id))
    if row is None and required: raise HTTPException(404,"记录不存在")
    return row

def list_entities(db,kind:str,parent_id=None,owner=None):
    q=db.query(Entity).filter(Entity.kind==kind)
    if parent_id is not None:q=q.filter(Entity.parent_id==parent_id)
    if owner is not None:q=q.filter(Entity.owner==owner)
    return q.order_by(Entity.created_at.desc()).all()

def put_entity(db,kind:str,data:dict,owner=None,parent_id=None):
    row=get_entity(db,kind,data["id"],False)
    if row:
        row.payload=dict(data);row.revision+=1;row.updated_at=datetime.now(timezone.utc)
        if parent_id is not None:row.parent_id=parent_id
    else:
        row=Entity(kind=kind,id=data["id"],payload=dict(data),owner=owner,parent_id=parent_id);db.add(row)
    db.flush()
    return row
