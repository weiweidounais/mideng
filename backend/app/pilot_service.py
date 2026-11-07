"""Transactional account/project foundation, no model/provider imports or calls."""
import hashlib
import json
import secrets
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from pwdlib import PasswordHash
from sqlalchemy import create_engine, event, select, update, text
from sqlalchemy.orm import sessionmaker
from .pilot_models import Account, Project, Membership, Audit, Idempotency, Outbox, Todo, utcnow

hasher = PasswordHash.recommended()
ROLES = ['市场', '商务', '设计', '采购', '项目经理', '工厂', '现场', '质量', '财务', '管理员']
ACTIONS = {'project.edit': {'项目经理', '管理员'}, 'audit.read': {'项目经理', '管理员'},
           'quality.release': {'质量'}, 'cost.publish': {'财务'}, 'cost.detail': {'财务'}}


def business_roles(roles):
    """Effective workflow capabilities; persisted memberships and audit roles stay unchanged."""
    return list(ROLES) if '管理员' in roles else list(roles)


def workflow_admin(store, db, actor, pid):
    # A technical account flag never bypasses active project membership.
    return '管理员' in store.membership(db, actor, pid)[1].roles


def uid():
    return uuid.uuid4().hex


def fail(status, code, message, **extra):
    raise HTTPException(status, {'code': code, 'message': message, **extra})


def account_view(a):
    return {'id': a.id, 'username': a.username, 'display_name': a.display_name, 'is_admin': a.is_admin}


def project_view(p, roles):
    return {'id': p.id, 'code': p.code, 'name': p.name, 'revision': p.revision, 'roles': roles,
            'actions': [k for k, allowed in ACTIONS.items() if allowed.intersection(business_roles(roles))]}


def member_view(m, a):
    return {'id': m.id, 'account_id': m.account_id, 'username': a.username, 'display_name': a.display_name,
            'roles': m.roles, 'active': m.active, 'valid_from': m.valid_from, 'valid_until': m.valid_until,
            'revision': m.revision}


class Store:
    def __init__(self, url):
        args = {'check_same_thread': False, 'timeout': 30} if url.startswith('sqlite') else {}
        self.engine = create_engine(url, connect_args=args)
        if url.startswith('sqlite'):
            @event.listens_for(self.engine, 'connect')
            def pragmas(connection, _):
                connection.execute('PRAGMA foreign_keys=ON')
                connection.execute('PRAGMA journal_mode=WAL')
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def migrate(self):
        cfg = Config()
        cfg.set_main_option('script_location', str(Path(__file__).resolve().parents[1] / 'pilot_migrations'))
        # This is a separate database and migration chain.
        with self.engine.begin() as connection:
            cfg.attributes['connection'] = connection
            command.upgrade(cfg, 'head')

    @contextmanager
    def transaction(self, write=False):
        with self.sessions() as db:
            try:
                if write and self.engine.dialect.name == 'sqlite':
                    db.execute(text('BEGIN IMMEDIATE'))
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def membership(self, db, actor, pid, action=None):
        p = db.get(Project, pid)
        m = db.scalar(select(Membership).where(Membership.project_id == pid, Membership.account_id == actor.id))
        now = utcnow()
        if not p or not m or not m.active or m.valid_from > now or (m.valid_until and m.valid_until <= now):
            fail(404, 'NOT_ACCESSIBLE', '项目不存在或无访问权限')
        if action and not ACTIONS[action].intersection(business_roles(m.roles)):
            fail(403, 'ACTION_FORBIDDEN', '当前项目岗位无此操作权限')
        return p, m

    def audit(self, db, actor, action, oid, revision, request_id, pid=None):
        m = db.scalar(select(Membership).where(Membership.project_id == pid, Membership.account_id == actor.id)) if pid else None
        roles = list(m.roles) if m else (['系统管理员'] if actor.is_admin else [])
        db.add(Audit(id=uid(), project_id=pid, actor_id=actor.id, actor_roles=roles, action=action, object_id=oid,
                     revision=revision, request_id=request_id))

    def mutation(self, db, actor, action, key, payload, execute):
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        old = db.scalar(select(Idempotency).where(Idempotency.actor_id == actor.id,
                        Idempotency.action == action, Idempotency.key == key))
        if old:
            if old.digest != digest:
                fail(409, 'IDEMPOTENCY_CONFLICT', '同一请求编号用于不同内容，请核对原提交结果')
            return old.result
        result = execute()
        db.flush()
        db.add(Idempotency(id=uid(), actor_id=actor.id, action=action, key=key, digest=digest, result=result))
        return result

    def deliver(self, db, e):
        if not db.scalar(select(Todo).where(Todo.event_id == e.id)):
            db.add(Todo(id=uid(), event_id=e.id, project_id=e.project_id, recipient_id=e.recipient_id, title=e.title,target_kind=e.target_kind,target_id=e.target_id,version_id=e.version_id))
        db.flush()

    def drain(self):
        """Todo creation and done status are atomic; retry count is itself durable."""
        with self.transaction(write=True) as db:
            events = db.scalars(select(Outbox).where(Outbox.state == 'pending', Outbox.available_at <= utcnow()).limit(100)).all()
            for e in events:
                e.attempts += 1
                try:
                    with db.begin_nested():
                        self.deliver(db, e)
                        e.state = 'done'
                        db.flush()
                except Exception:
                    e.state = 'failed' if e.attempts >= 3 else 'pending'
                    e.available_at = (datetime.now(timezone.utc) + timedelta(seconds=(60, 300, 900)[min(e.attempts - 1, 2)])).isoformat()
            return len(events)
