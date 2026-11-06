"""Keep old todo records while adding project-object-version navigation."""
from alembic import op
import sqlalchemy as sa
revision='pilot_004'
down_revision='pilot_003'

def upgrade():
    for table in ['pilot_outbox','pilot_todos']:
        for name in ['target_kind','target_id','version_id']:
            op.add_column(table,sa.Column(name,sa.String(),nullable=True))

def downgrade():
    raise RuntimeError('待办来源与版本记录不可自动销毁')
