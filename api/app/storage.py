from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import json
import sqlite3
from typing import Any, Iterator
from uuid import uuid4


@dataclass(frozen=True)
class AppStorage:
    db_path: Path
    output_dir: Path
    upload_dir: Path
    asset_dir: Path
    release_dir: Path
    database_url: str = ""

    @classmethod
    def create(cls, data_dir: str | Path) -> "AppStorage":
        root = Path(data_dir)
        root.mkdir(parents=True, exist_ok=True)
        output_dir = root / "outputs"
        upload_dir = root / "uploads"
        asset_dir = root / "assets"
        release_dir = root / "releases"
        output_dir.mkdir(parents=True, exist_ok=True)
        upload_dir.mkdir(parents=True, exist_ok=True)
        asset_dir.mkdir(parents=True, exist_ok=True)
        release_dir.mkdir(parents=True, exist_ok=True)
        app_env = os.getenv("APP_ENV", "development").strip().lower()
        database_url = os.getenv("DATABASE_URL", "").strip()
        production_database_url = database_url if app_env not in {"test", "local"} and is_postgres_database_url(database_url) else ""
        storage = cls(
            db_path=root / "zhifeng.sqlite3",
            output_dir=output_dir,
            upload_dir=upload_dir,
            asset_dir=asset_dir,
            release_dir=release_dir,
            database_url=production_database_url,
        )
        storage.init_schema()
        storage.mark_interrupted_generation_jobs_failed()
        return storage

    @contextmanager
    def connect(self) -> Iterator[Any]:
        connection = self._connect_postgres() if self.database_url else self._connect_sqlite()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _connect_sqlite(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _connect_postgres(self) -> Any:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ModuleNotFoundError as exc:
            raise RuntimeError("psycopg is required when DATABASE_URL points to PostgreSQL") from exc
        connection = psycopg.connect(normalize_postgres_database_url(self.database_url), row_factory=dict_row)
        return PostgresConnectionAdapter(connection)

    def init_schema(self) -> None:
        with self.connect() as connection:
            execute_schema_script(
                connection,
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    email_normalized TEXT UNIQUE,
                    username TEXT NOT NULL DEFAULT '',
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    status TEXT NOT NULL DEFAULT 'pending_verification',
                    email_verified_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    expires_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS refresh_sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    refresh_token_hash TEXT NOT NULL UNIQUE,
                    device_id TEXT NOT NULL DEFAULT '',
                    ip_address TEXT NOT NULL DEFAULT '',
                    user_agent TEXT NOT NULL DEFAULT '',
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS email_verification_tokens (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    email TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    expires_at TEXT NOT NULL,
                    used_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS email_verification_codes (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL,
                    code_hash TEXT NOT NULL,
                    purpose TEXT NOT NULL DEFAULT 'register',
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS password_reset_tokens (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    expires_at TEXT NOT NULL,
                    used_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    user_id TEXT,
                    event_type TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS email_outbox (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    email TEXT NOT NULL,
                    template TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    sent_at TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS products (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    brand TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT '',
                    material TEXT NOT NULL DEFAULT '',
                    color TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    specs_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'confirmed',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    deleted_at TEXT,
                    version INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    style_config_json TEXT NOT NULL DEFAULT '{}',
                    certificate_config_json TEXT NOT NULL DEFAULT '{}',
                    package_config_json TEXT NOT NULL DEFAULT '{}',
                    detail_config_json TEXT NOT NULL DEFAULT '{}',
                    barcode_type TEXT NOT NULL,
                    barcode_value TEXT NOT NULL,
                    barcode_confirmed INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'ready',
                    current_version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    deleted_at TEXT,
                    version INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    FOREIGN KEY (product_id) REFERENCES products(id)
                );

                CREATE TABLE IF NOT EXISTS generation_jobs (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    provider_name TEXT NOT NULL,
                    source_asset_version_id TEXT,
                    error_code TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    FOREIGN KEY (project_id) REFERENCES projects(id)
                );

                CREATE TABLE IF NOT EXISTS generation_outputs (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    output_type TEXT NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    format TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    quality_status TEXT NOT NULL,
                    source_asset_version_id TEXT,
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    FOREIGN KEY (project_id) REFERENCES projects(id),
                    FOREIGN KEY (job_id) REFERENCES generation_jobs(id)
                );

                CREATE TABLE IF NOT EXISTS user_accounts (
                    user_id TEXT PRIMARY KEY,
                    username_snapshot TEXT NOT NULL DEFAULT '',
                    balance_points INTEGER NOT NULL DEFAULT 0,
                    reserved_points INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS account_point_lots (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    total_points INTEGER NOT NULL,
                    remaining_points INTEGER NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS account_transactions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    points INTEGER NOT NULL,
                    balance_after INTEGER NOT NULL,
                    related_job_id TEXT,
                    remark TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS generation_billing_holds (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    job_id TEXT NOT NULL UNIQUE,
                    points INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'reserved',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS upload_sessions (
                    upload_token TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    asset_type TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    requested_content_type TEXT NOT NULL,
                    requested_size_bytes INTEGER NOT NULL,
                    object_key TEXT NOT NULL,
                    file_path TEXT,
                    received_content_type TEXT,
                    received_size_bytes INTEGER,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS assets (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    product_id TEXT,
                    project_id TEXT,
                    asset_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    deleted_at TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    FOREIGN KEY (product_id) REFERENCES products(id),
                    FOREIGN KEY (project_id) REFERENCES projects(id)
                );

                CREATE TABLE IF NOT EXISTS asset_versions (
                    id TEXT PRIMARY KEY,
                    asset_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    filename TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (asset_id) REFERENCES assets(id),
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS app_releases (
                    id TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    channel TEXT NOT NULL DEFAULT 'stable',
                    platform TEXT NOT NULL,
                    arch TEXT NOT NULL DEFAULT 'x64',
                    object_key TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    file_size_bytes INTEGER NOT NULL DEFAULT 0,
                    release_notes_json TEXT NOT NULL DEFAULT '[]',
                    force_update INTEGER NOT NULL DEFAULT 0,
                    min_supported_version TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'draft',
                    published_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            _ensure_column(connection, "generation_jobs", "source_asset_version_id", "TEXT")
            _ensure_column(connection, "generation_jobs", "error_code", "TEXT")
            _ensure_column(connection, "generation_jobs", "error_message", "TEXT")
            _ensure_column(connection, "generation_outputs", "source_asset_version_id", "TEXT")
            _ensure_column(connection, "sessions", "expires_at", "TEXT")
            _ensure_column(connection, "users", "email_normalized", "TEXT")
            _ensure_column(connection, "users", "username", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(connection, "users", "status", "TEXT NOT NULL DEFAULT 'active'")
            _ensure_column(connection, "users", "email_verified_at", "TEXT")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_email_verification_codes_lookup ON email_verification_codes(email, purpose, consumed_at, expires_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_app_releases_lookup ON app_releases(platform, arch, channel, status)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_account_transactions_user_time ON account_transactions(user_id, created_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_account_point_lots_user_expiry ON account_point_lots(user_id, expires_at, remaining_points)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_generation_billing_holds_user_status ON generation_billing_holds(user_id, status)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_generation_outputs_gallery ON generation_outputs(user_id, quality_status, created_at DESC, id DESC)"
            )
            connection.execute("UPDATE users SET email_normalized = lower(email) WHERE email_normalized IS NULL")
            connection.execute(
                "UPDATE users SET status = 'active', email_verified_at = COALESCE(email_verified_at, CAST(CURRENT_TIMESTAMP AS TEXT)) WHERE status IS NULL OR status = ''"
            )
            connection.execute(
                "UPDATE sessions SET expires_at = ? WHERE expires_at IS NULL OR expires_at = ''",
                (_default_auth_expiry(),),
            )

    def mark_interrupted_generation_jobs_failed(self) -> None:
        with self.connect() as connection:
            project_ids = [
                row["project_id"]
                for row in connection.execute(
                    "SELECT DISTINCT project_id FROM generation_jobs WHERE status = 'running'"
                ).fetchall()
            ]
            if not project_ids:
                return
            connection.execute(
                """
                UPDATE generation_jobs
                SET status = 'failed',
                    completed_at = CURRENT_TIMESTAMP,
                    error_code = 'GENERATION_INTERRUPTED',
                    error_message = 'Generation was interrupted by server restart.'
                WHERE status = 'running'
                """
            )
            placeholders = ",".join("?" for _ in project_ids)
            connection.execute(
                f"UPDATE projects SET status = 'failed', updated_at = CURRENT_TIMESTAMP WHERE status = 'generating' AND id IN ({placeholders})",
                project_ids,
            )


def new_id() -> str:
    return str(uuid4())


def _default_auth_expiry() -> str:
    days = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


class PostgresConnectionAdapter:
    dialect = "postgres"

    def __init__(self, connection: Any):
        self.connection = connection

    def execute(self, sql: str, params: Any = None) -> Any:
        return self.connection.execute(to_postgres_sql(sql), params or ())

    def commit(self) -> None:
        self.connection.commit()

    def rollback(self) -> None:
        self.connection.rollback()

    def close(self) -> None:
        self.connection.close()


def row_to_dict(row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def json_loads(value: str) -> Any:
    return json.loads(value)


def _ensure_column(connection: Any, table: str, column: str, definition: str) -> None:
    if getattr(connection, "dialect", "sqlite") == "postgres":
        columns = {
            row["column_name"]
            for row in connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = ?
                """,
                (table,),
            ).fetchall()
        }
    else:
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def execute_schema_script(connection: Any, script: str) -> None:
    if getattr(connection, "dialect", "sqlite") == "postgres":
        for statement in [part.strip() for part in script.split(";")]:
            if statement:
                connection.execute(statement)
        return
    connection.executescript(script)


def is_postgres_database_url(database_url: str) -> bool:
    return database_url.startswith(("postgresql://", "postgresql+", "postgres://"))


def normalize_postgres_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql+asyncpg://"):
        return "postgresql://" + database_url.removeprefix("postgresql+asyncpg://")
    if database_url.startswith("postgresql+psycopg://"):
        return "postgresql://" + database_url.removeprefix("postgresql+psycopg://")
    if database_url.startswith("postgres://"):
        return "postgresql://" + database_url.removeprefix("postgres://")
    return database_url


def to_postgres_sql(sql: str) -> str:
    return sql.replace("?", "%s")
