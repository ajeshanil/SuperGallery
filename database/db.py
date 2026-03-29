import os
from pathlib import Path
from sqlalchemy import create_engine, event as sa_event
from sqlalchemy.orm import sessionmaker, Session

from .models import Base

_DATA_DIR = Path.home() / ".supergallery"
_DB_PATH = _DATA_DIR / "gallery.db"

_engine = None
_SessionFactory = None


def _get_engine():
    global _engine
    if _engine is None:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{_DB_PATH}",
            echo=False,
            connect_args={"check_same_thread": False, "timeout": 30},
        )

        @sa_event.listens_for(_engine, "connect")
        def _set_pragmas(dbapi_conn, _rec):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=10000")
            cur.close()

    return _engine


def init_db() -> None:
    """Create all tables if they don't exist, and apply lightweight column migrations."""
    engine = _get_engine()
    Base.metadata.create_all(engine)
    global _SessionFactory
    _SessionFactory = sessionmaker(bind=engine)

    # SQLite doesn't support ALTER COLUMN — add new nullable columns if missing
    from sqlalchemy import text as _sa_text
    with engine.connect() as _conn:
        _cols = [row[1] for row in _conn.execute(_sa_text("PRAGMA table_info(photos)"))]
        if "dhash" not in _cols:
            _conn.execute(_sa_text("ALTER TABLE photos ADD COLUMN dhash TEXT"))
            _conn.commit()


def get_session() -> Session:
    """Return a new SQLAlchemy session. Caller is responsible for closing."""
    global _SessionFactory
    if _SessionFactory is None:
        init_db()
    return _SessionFactory()


def db_path() -> Path:
    return _DB_PATH
