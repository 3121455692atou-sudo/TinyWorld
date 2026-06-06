from __future__ import annotations

from pathlib import Path
from typing import Iterator

from sqlalchemy import event, inspect, text
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import DATA_DIR, settings
from .models import Base


def _connect_args(url: str) -> dict:
    if not url.startswith("sqlite"):
        return {}
    return {"check_same_thread": False, "timeout": 30}


def _make_engine(url: str):
    created = create_engine(url, connect_args=_connect_args(url))
    if url.startswith("sqlite"):
        @event.listens_for(created, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()
    return created


engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def configure_database(database_url: str | None = None) -> None:
    global engine, SessionLocal
    url = database_url or settings.database_url
    if url.startswith("sqlite:///"):
        path = Path(url.removeprefix("sqlite:///"))
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
    engine = _make_engine(url)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(drop: bool = False) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if drop:
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    _migrate_sqlite()


def _migrate_sqlite() -> None:
    if not str(engine.url).startswith("sqlite"):
        return
    columns = {column["name"] for column in inspect(engine).get_columns("agents")}
    additions = {
        "model_provider_name": "VARCHAR(80)",
        "model_name": "VARCHAR(120)",
        "llm_base_url": "VARCHAR(300)",
        "llm_api_key": "TEXT",
        "custom_system_prompt": "TEXT",
        "user_configured_name": "BOOLEAN DEFAULT 0",
        "age_stage": "VARCHAR(24) DEFAULT 'adult'",
        "wallet_json": "JSON DEFAULT '{}'",
        "work_json": "JSON DEFAULT '{}'",
        "family_json": "JSON DEFAULT '{}'",
        "law_json": "JSON DEFAULT '{}'",
        "trauma_json": "JSON DEFAULT '{}'",
        "desires_json": "JSON DEFAULT '{}'",
        "morality_json": "JSON DEFAULT '{}'",
        "tool_learning_json": "JSON DEFAULT '{}'",
    }
    with engine.begin() as conn:
        for name, ddl in additions.items():
            if name not in columns:
                conn.execute(text(f"ALTER TABLE agents ADD COLUMN {name} {ddl}"))
        conn.execute(
            text(
                """
                UPDATE events
                SET importance = 1, color_class = 'muted', no_state_changed = 1
                WHERE event_type IN ('llm_config_changed', 'agent_profile_changed')
                """
            )
        )
        conn.execute(text("DROP TRIGGER IF EXISTS normalize_trivial_config_events_insert"))
        conn.execute(
            text(
                """
                CREATE TRIGGER normalize_trivial_config_events_insert
                AFTER INSERT ON events
                WHEN NEW.event_type IN ('llm_config_changed', 'agent_profile_changed')
                BEGIN
                    UPDATE events
                    SET importance = 1, color_class = 'muted', no_state_changed = 1
                    WHERE event_id = NEW.event_id;
                END
                """
            )
        )
        conn.execute(text("DROP TRIGGER IF EXISTS normalize_trivial_config_events_update"))
        conn.execute(
            text(
                """
                CREATE TRIGGER normalize_trivial_config_events_update
                AFTER UPDATE OF event_type, importance, color_class, no_state_changed ON events
                WHEN NEW.event_type IN ('llm_config_changed', 'agent_profile_changed')
                     AND (NEW.importance != 1 OR NEW.color_class != 'muted' OR NEW.no_state_changed != 1)
                BEGIN
                    UPDATE events
                    SET importance = 1, color_class = 'muted', no_state_changed = 1
                    WHERE event_id = NEW.event_id;
                END
                """
            )
        )


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
