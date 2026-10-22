from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.model import ModelHolder, load_in_background
from app.observability import instrument, setup_logging
from app.routes import router
from app.settings import Settings


def create_app() -> FastAPI:
    settings = Settings()
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        load_in_background(app.state.holder, settings)  # /health answers 503 until ready
        yield

    app = FastAPI(lifespan=lifespan)
    app.state.holder = ModelHolder()
    app.include_router(router)
    instrument(app)
    return app


app = create_app()
