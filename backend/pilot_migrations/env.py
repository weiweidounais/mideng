from alembic import context
from app.pilot_models import PilotBase
connection = context.config.attributes['connection']
context.configure(connection=connection, target_metadata=PilotBase.metadata)
with context.begin_transaction():
    context.run_migrations()
