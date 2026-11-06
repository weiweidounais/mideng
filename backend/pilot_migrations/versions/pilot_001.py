"""Frozen foundation schema; independent of the legacy knowledge migration chain."""
from alembic import op
import sqlalchemy as sa

revision = 'pilot_001'
down_revision = None


def col(name, kind=sa.String(), **kw):
    return sa.Column(name, kind, nullable=False, **kw)


def upgrade():
    op.create_table('pilot_accounts', col('id', primary_key=True), col('username', sa.String(80), unique=True),
        col('display_name', sa.String(80)), col('password_hash'), col('is_admin', sa.Boolean()), col('active', sa.Boolean()))
    op.create_table('pilot_sessions', col('token_hash', primary_key=True),
        sa.Column('account_id', sa.String(), sa.ForeignKey('pilot_accounts.id'), nullable=False), col('csrf'), col('expires_at'))
    op.create_table('pilot_projects', col('id', primary_key=True), col('code', sa.String(80), unique=True),
        col('name', sa.String(120)), sa.Column('owner_id', sa.String(), sa.ForeignKey('pilot_accounts.id'), nullable=False),
        col('revision', sa.Integer()), col('created_at'))
    op.create_table('pilot_memberships', col('id', primary_key=True),
        sa.Column('project_id', sa.String(), sa.ForeignKey('pilot_projects.id'), nullable=False),
        sa.Column('account_id', sa.String(), sa.ForeignKey('pilot_accounts.id'), nullable=False),
        col('roles', sa.JSON()), col('active', sa.Boolean()), col('valid_from'), sa.Column('valid_until', sa.String()),
        col('revision', sa.Integer()), sa.UniqueConstraint('project_id','account_id'))
    op.create_table('pilot_audit', col('id', primary_key=True),
        sa.Column('project_id', sa.String(), sa.ForeignKey('pilot_projects.id')),
        sa.Column('actor_id', sa.String(), sa.ForeignKey('pilot_accounts.id'), nullable=False),
        col('action'), col('object_id'), col('revision', sa.Integer()), col('request_id'), col('at'))
    op.create_table('pilot_idempotency', col('id', primary_key=True),
        sa.Column('actor_id', sa.String(), sa.ForeignKey('pilot_accounts.id'), nullable=False),
        col('action'), col('key', sa.String(100)), col('digest'), col('result', sa.JSON()),
        sa.UniqueConstraint('actor_id','action','key'))
    op.create_table('pilot_outbox', col('id', primary_key=True),
        sa.Column('project_id', sa.String(), sa.ForeignKey('pilot_projects.id'), nullable=False),
        sa.Column('recipient_id', sa.String(), sa.ForeignKey('pilot_accounts.id'), nullable=False),
        col('title'), col('state'), col('attempts', sa.Integer()), col('available_at'))
    op.create_table('pilot_todos', col('id', primary_key=True),
        sa.Column('event_id', sa.String(), sa.ForeignKey('pilot_outbox.id'), nullable=False, unique=True),
        sa.Column('project_id', sa.String(), sa.ForeignKey('pilot_projects.id'), nullable=False),
        sa.Column('recipient_id', sa.String(), sa.ForeignKey('pilot_accounts.id'), nullable=False), col('title'), col('created_at'))


def downgrade():
    raise RuntimeError('业务表禁止自动销毁；恢复请使用经过核验的隔离备份')
