"""Scoped polling worker. Interrupted dispatch is reconciled, never resent."""

import argparse
import asyncio

from sqlalchemy import select

from app.config import get_settings
from app.database import create_database_engine, create_session_factory
from app.models import ExecutionAttempt
from app.security.tenant_context import apply_tenant_context, assert_runtime_role
from app.services.execution import expire_attempts, process_attempt


async def work(*, clients: list[str], once: bool) -> None:
    settings = get_settings()
    if settings.is_production and (not clients or settings.configuration_issues()):
        raise ValueError("Provision a production-ready worker and explicit client scope")
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    try:
        while True:
            async with factory() as db:
                await apply_tenant_context(
                    db,
                    client_ids=clients,
                    is_execution_worker=True,
                    is_platform_admin=not settings.is_production and not clients,
                )
                await assert_runtime_role(db)
                await expire_attempts(db)
                job = await db.scalar(
                    select(ExecutionAttempt.id)
                    .where(ExecutionAttempt.status == "QUEUED")
                    .order_by(ExecutionAttempt.created_at, ExecutionAttempt.id)
                    .limit(1)
                )
                if job:
                    await process_attempt(db, job, settings)
            if once:
                return
            await asyncio.sleep(1)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Process HighStudio ERP execution attempts")
    parser.add_argument("--client-id", action="append", default=[])
    parser.add_argument("--once", action="store_true")
    arguments = parser.parse_args()
    asyncio.run(work(clients=arguments.client_id, once=arguments.once))


if __name__ == "__main__":
    main()
