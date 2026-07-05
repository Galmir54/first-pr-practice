import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config, db
from .poller import poller_loop
from .routers import devices, readings, summary, tariff

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    task = asyncio.create_task(poller_loop())
    yield
    task.cancel()


app = FastAPI(title="Energie-Dashboard", lifespan=lifespan)

app.include_router(devices.router, prefix="/api/devices", tags=["devices"])
app.include_router(readings.router, prefix="/api/devices", tags=["readings"])
app.include_router(tariff.router, prefix="/api/tariff", tags=["tariff"])
app.include_router(summary.router, prefix="/api/summary", tags=["summary"])

app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(str(config.STATIC_DIR / "index.html"))
