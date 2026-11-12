import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config, db, maintenance, waste
from .poller import poller_loop
from .routers import devices, readings, summary, tariff
from .routers import waste as waste_router

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    tasks = [
        asyncio.create_task(poller_loop()),
        asyncio.create_task(maintenance.maintenance_loop()),
        asyncio.create_task(waste.waste_loop()),
    ]
    yield
    maintenance.request_stop()
    for task in tasks:
        task.cancel()


app = FastAPI(title="Energie-Dashboard", lifespan=lifespan)

app.include_router(devices.router, prefix="/api/devices", tags=["devices"])
app.include_router(readings.router, prefix="/api/devices", tags=["readings"])
app.include_router(tariff.router, prefix="/api/tariff", tags=["tariff"])
app.include_router(summary.router, prefix="/api/summary", tags=["summary"])
app.include_router(waste_router.router, prefix="/api/waste", tags=["waste"])

app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(str(config.STATIC_DIR / "index.html"))
