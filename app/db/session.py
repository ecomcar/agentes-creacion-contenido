"""
Sesión de base de datos.

`engine_for()` acepta cualquier URL soportada por SQLAlchemy, lo que permite
que las pruebas usen SQLite en memoria y producción use Postgres sin ninguna
rama condicional en el código de negocio.
"""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import get_settings
from .models import Base


def engine_for(url: str | None = None, echo: bool | None = None) -> Engine:
    settings = get_settings()
    url = url or settings.database_url
    kwargs: dict = {"echo": settings.db_echo if echo is None else echo,
                    "future": True}

    if url.startswith("sqlite"):
        # SQLite en memoria necesita una sola conexión compartida, o cada
        # sesión vería una base vacía distinta.
        from sqlalchemy.pool import StaticPool
        kwargs.update(connect_args={"check_same_thread": False},
                      poolclass=StaticPool)
    else:
        kwargs.update(pool_pre_ping=True, pool_size=5, max_overflow=10)

    eng = create_engine(url, **kwargs)

    if url.startswith("sqlite"):
        # SQLite no aplica claves foráneas salvo que se le pida. Sin esto,
        # las pruebas no detectarían referencias rotas que Postgres sí
        # rechazaría en producción.
        @event.listens_for(eng, "connect")
        def _fk_on(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return eng


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def create_all(engine: Engine) -> None:
    """Sólo para pruebas y desarrollo. En producción manda Alembic."""
    Base.metadata.create_all(engine)


def drop_all(engine: Engine) -> None:
    Base.metadata.drop_all(engine)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Transacción con commit al salir y rollback si algo falla."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
