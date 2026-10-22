from contextlib import asynccontextmanager

import yaml
from fastapi import FastAPI
from psycopg_pool import ConnectionPool

from app.clients import ModelClient
from app.db import Database
from app.observability import instrument, setup_logging
from app.routes import router
from app.settings import Settings


def create_app() -> FastAPI:
    settings = Settings()
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        with open(settings.labels_path) as fh:
            app.state.labels = yaml.safe_load(fh)["labels"]
        pool = ConnectionPool(settings.database_url, min_size=1, max_size=5, open=False)
        pool.open(wait=False)  # don't block startup: /health reports the DB state
        app.state.db = Database(pool)
        app.state.model_client = ModelClient(
            settings.model_service_url,
            settings.model_service_token,
            settings.model_call_timeout_seconds,
        )
        yield
        app.state.model_client.close()
        pool.close()

    app = FastAPI(lifespan=lifespan)
    app.state.settings = settings
    app.include_router(router)
    instrument(app)
    return app


app = create_app()
