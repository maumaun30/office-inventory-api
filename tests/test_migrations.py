from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from app.database import Base
from tests.conftest import TEST_DATABASE_URL


def migration_url(tmp_path, name: str) -> str:
    return TEST_DATABASE_URL or f"sqlite:///{tmp_path / name}"


def alembic_config(url: str) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["configure_logger"] = False
    return cfg


def test_migrations_match_models(tmp_path):
    cfg = alembic_config(migration_url(tmp_path, "migrated.db"))
    command.upgrade(cfg, "head")
    try:
        engine = create_engine(cfg.get_main_option("sqlalchemy.url"))
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn, opts={"compare_type": True})
            diff = compare_metadata(ctx, Base.metadata)
        engine.dispose()
    finally:
        command.downgrade(cfg, "base")
    assert diff == [], f"Models changed without a migration: {diff}"


def test_downgrade_to_base(tmp_path):
    cfg = alembic_config(migration_url(tmp_path, "roundtrip.db"))
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
