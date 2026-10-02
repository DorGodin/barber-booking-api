from __future__ import annotations

import os

from alembic import context

from app.db import Base, make_engine
from app.models import UTCDateTime  # also registers every table on Base.metadata


def render_item(kind, obj, autogen_context):
    # UTCDateTime is a DateTime in the database. Rendered as itself, a
    # migration would import app.models - which keeps changing after the
    # migration is written.
    if kind == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime()"
    return False


def skip_empty(context, revision, directives):
    # `make migration` with the models unchanged would write a migration that
    # does nothing.
    if (
        context.config.cmd_opts
        and context.config.cmd_opts.autogenerate
        and directives[0].upgrade_ops.is_empty()
    ):
        directives[:] = []
        print("app/models.py matches the migrations - nothing to write")


def run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        # SQLite cannot alter a column in place; batch mode copies the table.
        render_as_batch=True,
        compare_type=True,
        render_item=render_item,
        process_revision_directives=skip_empty,
    )
    with context.begin_transaction():
        context.run_migrations()


connection = context.config.attributes.get("connection")
if connection is not None:
    run(connection)
else:
    # The alembic command line - `make migration` - against DATABASE_URL.
    engine = make_engine(os.environ["DATABASE_URL"])
    with engine.begin() as own:
        run(own)
    engine.dispose()
