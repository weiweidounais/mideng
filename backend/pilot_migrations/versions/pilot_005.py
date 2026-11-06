"""V2 procurement: PM request/review, receipt quality, private commercial archive."""
from alembic import op
import sqlalchemy as sa
revision='pilot_005'
down_revision='pilot_004'

def upgrade():
    op.create_table('procurement_orders',
        sa.Column('id',sa.String(),primary_key=True),sa.Column('project_id',sa.String(),sa.ForeignKey('pilot_projects.id'),nullable=False),
        sa.Column('version_id',sa.String(),nullable=False),sa.Column('revision',sa.Integer(),nullable=False),sa.Column('state',sa.String(),nullable=False),
        sa.Column('title',sa.String(),nullable=False),sa.Column('note',sa.String(),nullable=False),
        *[sa.Column(k,sa.String(),sa.ForeignKey('pilot_accounts.id'),nullable=False) for k in ['pm_id','purchase_id','quality_id','commerce_id']],
        sa.Column('lines',sa.JSON(),nullable=False),sa.Column('result',sa.JSON(),nullable=True),sa.Column('arrivals',sa.JSON(),nullable=False),sa.Column('archive',sa.JSON(),nullable=True),
        *[sa.Column(k,sa.String(),nullable=False) for k in ['due_at','created_at','updated_at']],
        sa.UniqueConstraint('id','project_id'),sa.UniqueConstraint('version_id','project_id'),sa.ForeignKeyConstraint(['version_id','project_id'],['handoff_versions.id','handoff_versions.project_id']))
    op.create_table('procurement_events',sa.Column('id',sa.String(),primary_key=True),sa.Column('project_id',sa.String(),nullable=False),sa.Column('order_id',sa.String(),nullable=False),sa.Column('action',sa.String(),nullable=False),sa.Column('actor_id',sa.String(),sa.ForeignKey('pilot_accounts.id'),nullable=False),sa.Column('body',sa.JSON(),nullable=False),sa.Column('at',sa.String(),nullable=False),sa.ForeignKeyConstraint(['order_id','project_id'],['procurement_orders.id','procurement_orders.project_id']))
    op.create_table('procurement_files',sa.Column('id',sa.String(),primary_key=True),sa.Column('project_id',sa.String(),sa.ForeignKey('pilot_projects.id'),nullable=False),sa.Column('order_id',sa.String(),sa.ForeignKey('procurement_orders.id'),nullable=False),sa.Column('purpose',sa.String(),nullable=False),sa.Column('name',sa.String(),nullable=False),sa.Column('sha256',sa.String(),nullable=False),sa.Column('size',sa.Integer(),nullable=False),sa.Column('media_type',sa.String(),nullable=False),sa.Column('path',sa.String(),nullable=False),sa.Column('created_by',sa.String(),sa.ForeignKey('pilot_accounts.id'),nullable=False))
    for action in ['UPDATE','DELETE']:
        op.execute(f"CREATE TRIGGER procurement_events_no_{action.lower()} BEFORE {action} ON procurement_events BEGIN SELECT RAISE(ABORT,'immutable procurement event'); END")

def downgrade():raise RuntimeError('采购证据不可自动销毁')
