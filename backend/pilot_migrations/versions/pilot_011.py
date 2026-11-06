"""Add project-scoped knowledge and rule applications without changing business facts."""
from alembic import op
from app.knowledge_models import Library,KnowledgeDocument,RuleApplication,RuleRun
revision='pilot_011'
down_revision='pilot_010'
branch_labels=None
depends_on=None
def upgrade():
    for model in (Library,KnowledgeDocument,RuleApplication,RuleRun):
        model.__table__.create(op.get_bind())
def downgrade():
    raise RuntimeError('知识原件与运行记录保留；回退使用一致备份')
