"""Snapshot effective roles at the time of the audit event; retain unknown history."""
from alembic import op
import sqlalchemy as sa
revision = 'pilot_002'
down_revision = 'pilot_001'


def upgrade():
    op.add_column('pilot_audit', sa.Column('actor_roles', sa.JSON(), nullable=False, server_default='[]'))


def downgrade():
    raise RuntimeError('不得销毁历史审计身份；请使用隔离恢复流程')
