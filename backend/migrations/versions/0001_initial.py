"""Initial schema, compatible with databases from the pre-Alembic prototype.

Revision ID: 0001_initial
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    # Existing deployments created these same tables with SQLAlchemy create_all.
    # Keep their data and let Alembic record this baseline after validation.
    if "entities" not in existing:
        op.create_table("entities",
            sa.Column("kind", sa.String(30), nullable=False),
            sa.Column("id", sa.String(100), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("owner", sa.String(100), nullable=True),
            sa.Column("parent_id", sa.String(100), nullable=True),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("kind", "id"))
    else:
        columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("entities")}
        required = {"kind", "id", "payload", "owner", "parent_id", "revision", "created_at", "updated_at"}
        if not required.issubset(columns):
            raise RuntimeError("现有 entities 表与初始版本不兼容，请先备份并检查数据库")
    indexes = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("entities")}
    if "ix_entity_scope" not in indexes:
        op.create_index("ix_entity_scope", "entities", ["kind", "parent_id", "owner"])
    if "credentials" not in existing:
        op.create_table("credentials",
            sa.Column("id", sa.String(100), nullable=False),
            sa.Column("encrypted", sa.String(), nullable=False),
            sa.PrimaryKeyConstraint("id"))
    elif not {"id", "encrypted"}.issubset({c["name"] for c in sa.inspect(op.get_bind()).get_columns("credentials")}):
        raise RuntimeError("现有 credentials 表与初始版本不兼容")
    if "login_sessions" not in existing:
        op.create_table("login_sessions",
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("owner", sa.String(100), nullable=False),
            sa.Column("role", sa.String(20), nullable=False),
            sa.Column("csrf", sa.String(100), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("token_hash"))
    elif not {"token_hash", "owner", "role", "csrf", "expires_at"}.issubset({c["name"] for c in sa.inspect(op.get_bind()).get_columns("login_sessions")}):
        raise RuntimeError("现有 login_sessions 表与初始版本不兼容")


def downgrade():
    op.drop_table("login_sessions")
    op.drop_table("credentials")
    op.drop_index("ix_entity_scope", table_name="entities")
    op.drop_table("entities")
