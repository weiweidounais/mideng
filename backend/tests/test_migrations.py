"""Fresh and pre-Alembic databases both upgrade without data loss."""
import pytest
from sqlalchemy import create_engine, inspect, text
from app import db
from app.config import config


@pytest.fixture
def migration_engine(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(config, "database_url", f"sqlite:///{tmp_path / 'migration.db'}")
    yield engine
    engine.dispose()


def test_fresh_database_gets_versioned_schema(migration_engine):
    db.init_db()
    assert set(inspect(migration_engine).get_table_names()) == {"entities", "credentials", "login_sessions", "alembic_version"}
    with migration_engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0001_initial"
    assert any(i["name"] == "ix_entity_scope" for i in inspect(migration_engine).get_indexes("entities"))
    db.init_db()
    with migration_engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM alembic_version")).scalar_one() == 1


def test_existing_prototype_tables_are_baselined_without_data_loss(migration_engine):
    db.Base.metadata.create_all(migration_engine)
    with migration_engine.begin() as connection:
        connection.execute(db.Entity.__table__.insert().values(kind="kb", id="preserved", payload={"id": "preserved", "name": "已有知识"}, owner="original-owner"))
        connection.execute(db.Credential.__table__.insert().values(id="connection", encrypted="existing-ciphertext"))
    db.init_db()
    with migration_engine.connect() as connection:
        assert connection.execute(text("SELECT id FROM entities")).scalar_one() == "preserved"
        assert connection.execute(text("SELECT encrypted FROM credentials")).scalar_one() == "existing-ciphertext"
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0001_initial"


def test_incompatible_legacy_schema_is_not_silently_stamped(migration_engine):
    with migration_engine.begin() as connection:
        connection.execute(text("CREATE TABLE entities (id TEXT PRIMARY KEY)"))
    with pytest.raises(RuntimeError, match="不兼容"):
        db.init_db()
    with migration_engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM alembic_version")).scalar_one() == 0
