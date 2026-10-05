"""Alembic environment. Migrations run through collectors.db.session.migrate()."""

from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import Connection

from collectors.config import database_url
from collectors.db.models import Base

config = context.config
target_metadata = Base.metadata


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=connection.dialect.name == "sqlite",
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url") or database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _configure(connection)
        return
    url = config.get_main_option("sqlalchemy.url") or database_url()
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as conn:
        _configure(conn)
        conn.commit()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
