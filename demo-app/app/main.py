import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    startup_fault = os.environ.get("STARTUP_FAULT", "").lower()
    if startup_fault == "crash":
        logger.error("FATAL: STARTUP_FAULT=crash -- raising exception on startup")
        raise RuntimeError("Deliberate startup crash for scenario testing")
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.error("FATAL: DATABASE_URL environment variable is not set")
        raise RuntimeError("Missing required configuration: DATABASE_URL")
    db_host = urlparse(db_url).hostname or ""
    if db_host.endswith(".invalid"):
        logger.error("FATAL: database DNS lookup failed for %s", db_host)
        raise RuntimeError(
            f"Database DNS resolution failed: no such host {db_host}"
        )
    if os.environ.get("STORAGE_FAULT") == "1":
        logger.warning("Ephemeral storage stress test starting...")
        Path("/tmp/demo-storage-fault").write_bytes(
            b"0" * (32 * 1024 * 1024)
        )
    if os.environ.get("READ_ONLY_FS_FAULT") == "1":
        logger.warning("Read-only filesystem write test starting...")
        Path("runtime-check.txt").write_text("filesystem check")
    logger.info("Demo app starting. DATABASE_URL=%s...", db_url[:20])
    yield
    logger.info("Demo app shutting down")


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    db_url = os.environ.get("DATABASE_URL", "")
    if "unavailable" in db_url:
        raise RuntimeError("Database connection failed: connection refused")
    return {"ready": True}


@app.get("/fault/crash")
def fault_crash():
    logger.error("Unhandled exception in /fault/crash: division by zero")
    raise ZeroDivisionError("Deliberate crash for testing")


@app.get("/fault/oom")
def fault_oom():
    logger.warning("Memory allocation stress test starting...")
    data = [bytearray(1024 * 1024) for _ in range(600)]
    return {"allocated": len(data)}


@app.get("/fault/slow")
def fault_slow():
    logger.info("Slow endpoint called -- sleeping 30s")
    time.sleep(30)
    return {"done": True}
