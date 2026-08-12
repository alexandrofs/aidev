from typing import AsyncGenerator, Optional
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker, AsyncEngine
from .config import settings

_engine: Optional[AsyncEngine] = None
_async_session_local: Optional[async_sessionmaker[AsyncSession]] = None


def get_engine() -> AsyncEngine:
    """Retorna a instância singleton do AsyncEngine, criando-a lazily na primeira invocação."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.get_database_url(), echo=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Retorna a fábrica de AsyncSession, criando-a lazily."""
    global _async_session_local
    if _async_session_local is None:
        _async_session_local = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            class_=AsyncSession
        )
    return _async_session_local


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Injeta a sessão assíncrona gerenciada para FastAPI."""
    session_factory = get_sessionmaker()
    async with session_factory() as session:
        yield session
