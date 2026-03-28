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
    """Create all tables if they don't exist."""
    Base.metadata.create_all(_get_engine())
    global _SessionFactory
    _SessionFactory = sessionmaker(bind=_get_engine())


def get_session() -> Session:
    """Return a new SQLAlchemy session. Caller is responsible for closing."""
    global _SessionFactory
    if _SessionFactory is None:
        init_db()
    return _SessionFactory()


def db_path() -> Path:
    return _DB_PATH
