"""The committed history store: every table as sorted JSONL under data/db/.

Without DATABASE_URL, each run rebuilds a SQLite database from these files, runs the jobs, and
writes them back, so git holds the full history and no hosted database is needed. With
DATABASE_URL set, Postgres is the source of truth and these files are a readable backup.
Rows are sorted by primary key and keys are sorted, so a day's run produces a small diff.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from sqlalchemy import Date, DateTime, Table, delete, select
from sqlalchemy.orm import Session

from collectors.config import HISTORY_DIR
from collectors.db.models import JOB_RUNS_KEPT, NOT_IN_HISTORY, Base, JobRun

# Columns kept in the database but left out of the public history files. Tracebacks contain
# file paths from whichever machine ran the job; the one-line summary is enough in git.
PRIVATE_COLUMNS = {"job_runs": {"error"}}


def _tables() -> list[Table]:
    return [t for t in Base.metadata.sorted_tables if t.name not in NOT_IN_HISTORY]


def _encode(value: Any) -> Any:
    if isinstance(value, dt.datetime):
        return value.replace(microsecond=0).isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, float):
        return round(value, 3)
    raise TypeError(f"cannot encode {type(value).__name__}")


def _decoder(table: Table) -> dict[str, Any]:
    decoders: dict[str, Any] = {}
    for column in table.columns:
        if isinstance(column.type, DateTime):
            decoders[column.name] = dt.datetime.fromisoformat
        elif isinstance(column.type, Date):
            decoders[column.name] = dt.date.fromisoformat
    return decoders


def dump(session: Session, out_dir: Path = HISTORY_DIR) -> dict[str, int]:
    """Write every history table to <out_dir>/<table>.jsonl. Returns row counts."""
    out_dir.mkdir(parents=True, exist_ok=True)
    keep_from = session.scalars(
        select(JobRun.id).order_by(JobRun.id.desc()).offset(JOB_RUNS_KEPT - 1).limit(1)
    ).first()
    if keep_from is not None:
        session.execute(delete(JobRun).where(JobRun.id < keep_from))
        session.flush()

    counts: dict[str, int] = {}
    for table in _tables():
        keys = [table.c[c.name] for c in table.primary_key.columns]
        hidden = PRIVATE_COLUMNS.get(table.name, set())
        columns = [c for c in table.columns if c.name not in hidden]
        rows = session.execute(select(*columns).order_by(*keys)).mappings().all()
        lines = [
            json.dumps(
                {k: (_encode(v) if isinstance(v, (dt.date, float)) else v) for k, v in row.items()},
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            for row in rows
        ]
        path = out_dir / f"{table.name}.jsonl"
        path.write_text("".join(line + "\n" for line in lines), encoding="utf-8", newline="\n")
        counts[table.name] = len(lines)
    return counts


def hydrate(session: Session, in_dir: Path = HISTORY_DIR) -> dict[str, int]:
    """Load every <table>.jsonl into an empty database, in foreign-key order. Returns row counts."""
    counts: dict[str, int] = {}
    for table in _tables():
        path = in_dir / f"{table.name}.jsonl"
        if not path.exists():
            continue
        decoders = _decoder(table)
        known = {c.name for c in table.columns}
        rows: list[dict[str, Any]] = []
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                raw = json.loads(line)
                rows.append(
                    {
                        k: (decoders[k](v) if k in decoders and v is not None else v)
                        for k, v in raw.items()
                        if k in known  # tolerate columns dropped by a later migration
                    }
                )
        for start in range(0, len(rows), 500):
            session.execute(table.insert(), rows[start : start + 500])
        counts[table.name] = len(rows)
    session.flush()
    return counts


def is_empty(session: Session) -> bool:
    from collectors.db.models import Org

    return session.scalars(select(Org.slug).limit(1)).first() is None
