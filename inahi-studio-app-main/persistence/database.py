"""Environment configuration and bounded compatibility adapter for legacy SQL."""

import os
from pathlib import Path
import re
import sqlite3
from datetime import date, datetime

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.pool import NullPool


def configured_url(legacy_path=None):
    from runtime_environment import validate, database_guard
    validate()
    raw = os.environ.get("DATABASE_URL", "").strip()
    if raw:
        try:
            url = make_url(raw)
        except Exception:
            raise ValueError("DATABASE_URL inválida") from None
        if url.drivername in ("postgres", "postgresql", "postgresql+psycopg"):
            if not url.host or not url.database:
                raise ValueError("PostgreSQL requiere host y base explícitos")
            database_guard(url)
            return url.set(drivername="postgresql+psycopg")
        if url.drivername != "sqlite" or url.host or not url.database or url.query:
            raise ValueError("Solo se admiten SQLite y PostgreSQL; configuración inválida")
        database_guard(url)
        return url
    path = legacy_path or os.environ.get("DATABASE_PATH")
    if not path:
        raise ValueError("Configura DATABASE_URL o DATABASE_PATH")
    url = URL.create("sqlite", database=str(path))
    database_guard(url)
    return url


class DeferredPostgresEngine:
    """Delay loading native DBAPI libraries until explicit connection, not configuration.

    Connection errors (including OS-blocked drivers) propagate unchanged; no fallback
    to SQLite and no changes to operating-system library policy.
    """
    hide_parameters = True

    def __init__(self, url):
        self.url = url
        self.dialect = url.get_dialect()()
        self._engine = None

    def _load(self):
        if self._engine is None:
            self._engine = create_engine(self.url, poolclass=NullPool, hide_parameters=True)
        return self._engine

    def connect(self):
        return self._load().connect()

    def begin(self):
        return self._load().begin()

    def dispose(self):
        if self._engine is not None:
            self._engine.dispose()


def make_engine(url):
    """Create a lazy engine; neither connect nor create schema here."""
    if url.get_backend_name() == "postgresql":
        return DeferredPostgresEngine(url)
    engine = create_engine(url, poolclass=NullPool, hide_parameters=True)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def sqlite_options(dbapi, _record):
            dbapi.isolation_level = None
            dbapi.execute("PRAGMA foreign_keys=ON")
            dbapi.execute("PRAGMA busy_timeout=15000")

        @event.listens_for(engine, "begin")
        def sqlite_transaction(connection):
            # Explicit BEGIN includes DDL in rollback, including Python's legacy sqlite mode.
            connection.exec_driver_sql("BEGIN")
    return engine


def connect(legacy_path=None, readonly=False):
    url = configured_url(legacy_path)
    if url.get_backend_name() == "sqlite":
        filename = url.database
        if readonly:
            if filename == ":memory:" or not Path(filename).is_file():
                raise ValueError("Dry run requiere una base SQLite existente")
            filename = Path(filename).resolve().as_uri() + "?mode=ro"
        c = sqlite3.connect(filename, uri=readonly, timeout=15)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=15000")
        if readonly:
            c.execute("PRAGMA query_only=ON")
        return c
    engine = make_engine(url)
    try:
        connection = engine.connect()
    except SQLAlchemyError:
        engine.dispose()
        raise sqlite3.OperationalError("No se pudo conectar con la base configurada") from None
    bridge = Connection(connection, engine=engine)
    if readonly:
        bridge.execute("SET TRANSACTION READ ONLY")
    return bridge


def has_table(c, name):
    if isinstance(c, Connection):
        return inspect(c.bind).has_table(name)
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def columns(c, name):
    if isinstance(c, Connection):
        return {item["name"] for item in inspect(c.bind).get_columns(name)}
    if not re.fullmatch(r"[a-z_]+", name):
        raise ValueError("Identificador inválido")
    return {row["name"] for row in c.execute(f"PRAGMA table_info({name})")}


def bind_parameters(sql, parameters):
    """Convert qmarks outside quoted literals to named bound parameters (never interpolate values)."""
    out, quote, index, offset = [], None, 0, 0
    while offset < len(sql):
        char = sql[offset]
        if quote:
            out.append(char)
            if char == quote:
                if offset + 1 < len(sql) and sql[offset + 1] == quote:
                    out.append(quote)
                    offset += 1
                else:
                    quote = None
        elif char in ("'", '"'):
            quote = char
            out.append(char)
        elif char == "?":
            out.append(f":p{index}")
            index += 1
        else:
            out.append(char)
        offset += 1
    if index != len(parameters):
        raise ValueError("Número de parámetros SQL incorrecto")
    return "".join(out), {f"p{i}": value for i, value in enumerate(parameters)}


class Row(dict):
    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


def legacy_value(value):
    return value.isoformat() if isinstance(value, (date, datetime)) else value


class Result:
    def __init__(self, result, returning_id=False):
        self.rowcount = result.rowcount
        self.lastrowid = None
        self.rows = []
        if returning_id:
            row = result.fetchone()
            self.lastrowid = row[0] if row else None
        elif result.returns_rows:
            self.rows = [Row({k: legacy_value(v) for k, v in row.items()}) for row in result.mappings()]
        else:
            self.lastrowid = getattr(result, "lastrowid", None)

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows

    def __iter__(self):
        return iter(self.fetchall())


class Connection:
    """SQLAlchemy unit of work with the small interface the legacy services require."""
    def __init__(self, bind, engine=None, owned=True):
        self.bind, self.engine, self.owned = bind, engine, owned
        self.dialect = bind.dialect.name

    def execute(self, sql, parameters=()):
        returning = False
        if self.dialect == "postgresql":
            if sql.strip().upper() == "BEGIN IMMEDIATE":
                sql = "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"
            # Identity-returning tables are an explicit schema allowlist.
            from persistence.models import ID_TABLES
            match = re.match(r"\s*INSERT\s+INTO\s+([a-z_]+)\b", sql, re.I)
            if match and match[1].lower() in ID_TABLES and "RETURNING" not in sql.upper():
                sql = sql.rstrip().rstrip(";") + " RETURNING id"
                returning = True
        statement, values = bind_parameters(sql, parameters)
        try:
            return Result(self.bind.execute(text(statement), values), returning)
        except IntegrityError:
            raise sqlite3.IntegrityError("Restricción de integridad incumplida") from None
        except SQLAlchemyError:
            raise sqlite3.OperationalError("Operación de base de datos fallida") from None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *_args):
        if self.owned:
            try:
                self.bind.rollback() if exc_type else self.bind.commit()
            finally:
                self.close()
        return False

    def close(self):
        if self.owned:
            self.bind.close()
            if self.engine is not None:
                self.engine.dispose()
