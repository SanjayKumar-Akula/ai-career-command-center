"""Dev helper: read-only comparison of the connected database against the models.

Prints the dialect, the Alembic revision, and any table/column/index drift so a
production database can be inspected without changing anything: this script binds
SQLAlchemy itself and only ever issues SELECTs and catalog reads -- it never
calls db.create_all(), never stamps a revision, and never prints the connection
string (only the dialect and database name).

Usage (uses DATABASE_URL when set, otherwise the local SQLite file):
    python scripts/check_db_schema.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask  # noqa: E402
from sqlalchemy import func, inspect, select, table  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from models import BASE_REVISION, db, normalize_database_url  # noqa: E402

# Bind the models without running init_db(), so this stays strictly read-only.
app = Flask(__name__)
raw_url = os.environ.get("DATABASE_URL")
uri = normalize_database_url(raw_url)
if not uri:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    uri = "sqlite:///" + os.path.join(base_dir, "career_center.db").replace("\\", "/")
app.config["SQLALCHEMY_DATABASE_URI"] = uri
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
if uri.startswith(("postgresql://", "postgresql+")):
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True, "pool_recycle": 300}
db.init_app(app)


def alembic_revision(engine) -> str:
    """Read the recorded revision without creating the version table."""
    from alembic.runtime.migration import MigrationContext

    try:
        with engine.connect() as conn:
            return MigrationContext.configure(conn).get_current_revision() or "(none recorded)"
    except Exception as exc:  # pragma: no cover
        return f"(unreadable: {exc.__class__.__name__})"


def row_count(engine, name: str) -> int:
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(table(name))).scalar()


with app.app_context():
    engine = db.engine
    url = make_url(uri)
    metadata = db.metadata
    expected = set(metadata.tables)
    present = set(inspect(engine).get_table_names())
    data_tables = {t for t in present if t not in {"alembic_version"}}

    print(f"dialect     : {url.get_dialect().name} (driver: {url.get_driver_name()})")
    print(f"database    : {url.database}")
    print(f"revision    : {alembic_revision(engine)}   [baseline {BASE_REVISION}]")
    print(f"tables      : {len(data_tables)} present / {len(expected)} expected")

    missing = sorted(expected - present)
    extra = sorted(data_tables - expected)
    print(f"missing     : {missing or 'none'}")
    print(f"extra       : {extra or 'none'}")

    column_problems = []
    for name in sorted(expected & present):
        actual = {c["name"] for c in inspect(engine).get_columns(name)}
        defined = set(metadata.tables[name].columns.keys())
        absent = sorted(defined - actual)     # model wants it, database lacks it
        surplus = sorted(actual - defined)    # database has more (harmless)
        if absent:
            column_problems.append((name, absent))
        status = "OK" if not absent and not surplus else "DRIFT"
        print(f"  {name.ljust(24)} columns: {len(actual):>2} actual, "
              f"{len(defined):>2} defined  missing={absent or '-'} extra={surplus or '-'} {status}")

    print(f"indexes     : {sum(len(i['column_names']) for i in inspect(engine).get_indexes('users'))}"
          f" indexed columns on `users`")

    print("row counts (read-only):")
    for name in sorted(data_tables):
        try:
            print(f"  {name.ljust(24)} {row_count(engine, name)}")
        except Exception as exc:  # pragma: no cover
            print(f"  {name.ljust(24)} (unreadable: {exc.__class__.__name__})")

    revision = alembic_revision(engine)
    has_revision = not revision.startswith("(none recorded")
    drift = bool(missing) or bool(column_problems)
    if drift:
        if column_problems:
            for name, absent in column_problems:
                print(f"  -> {name} is missing {', '.join(absent)}")
        print("\nVERDICT: schema does NOT match the models.")
        print(f"         Do not re-run {BASE_REVISION}. Add the smallest additive migration "
              "that closes the gap:")
        print("           flask db revision -m \"...\"   then   flask db upgrade")
    elif not has_revision:
        print("\nVERDICT: schema complete, but Alembic has no revision recorded.")
        print(f"         Safe fix: flask db stamp {BASE_REVISION}  (adds one row, changes no data)")
        print("         The app also does this automatically on start-up.")
    else:
        print("\nVERDICT: schema complete and stamped; `flask db upgrade` is a no-op.")
