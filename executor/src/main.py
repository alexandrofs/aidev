import sys
import signal
import asyncio
import logging
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from executor.src.config import settings
from executor.src.sandbox import DockerSandboxManager
from executor.src.worker import ExecutorWorker
from persistence.src.repository import EventRepository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("ai-dev-executor")


async def main() -> None:
    logger.info("Inicializando serviço ai-dev-executor...")
    db_url = settings.async_database_url
    logger.info(f"Conectando ao banco de dados: {settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}")

    engine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

    async with session_factory() as session:
        repo = EventRepository(session)
        sandbox_manager = DockerSandboxManager(settings=settings)
        worker = ExecutorWorker(repo=repo, sandbox_manager=sandbox_manager, settings=settings)

        loop = asyncio.get_running_loop()
        stop_signals = (signal.SIGINT, signal.SIGTERM)

        def _signal_handler(sig_name: str) -> None:
            logger.info(f"Sinal {sig_name} recebido. Solicitando encerramento gracioso...")
            worker.stop()

        for sig in stop_signals:
            try:
                loop.add_signal_handler(sig, _signal_handler, sig.name)
            except NotImplementedError:
                # Windows ou ambiente sem suporte a add_signal_handler no event loop
                signal.signal(sig, lambda s, f: worker.stop())

        try:
            logger.info(f"Iniciando Worker ID: {settings.WORKER_ID}")
            await worker.start()
        except asyncio.CancelledError:
            logger.info("Task do worker cancelada.")
        finally:
            logger.info("Fechando conexões com o banco de dados...")
            await engine.dispose()
            logger.info("Encerramento gracioso do ai-dev-executor concluído.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Serviço interrompido via KeyboardInterrupt.")
