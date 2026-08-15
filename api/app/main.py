from pathlib import Path
import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.account import router as account_router
from app.api.phase_one import router as phase_one_router
from app.api.standards import router as standards_router
from app.api.updates import router as updates_router
from app.core.object_storage import load_object_storage_config
from app.core.runtime_services import build_runtime_services
from app.storage import AppStorage
from app.workers.generation_queue import GenerationQueue


def create_app(data_dir: str | Path | None = None, *, load_env: bool = False) -> FastAPI:
    if load_env:
        load_local_env(Path.cwd() / ".env")
        load_local_env(Path(__file__).resolve().parents[1] / ".env")
    resolved_data_dir = data_dir or os.getenv("ZHIFENG_DATA_DIR", ".zhifeng-data")
    app = FastAPI(title="Zhifeng Image API", version="0.1.0")
    app.state.storage = AppStorage.create(resolved_data_dir)
    app.state.runtime_services = build_runtime_services()
    app.state.generation_queue = GenerationQueue(app.state.storage, app.state.runtime_services)
    app.state.object_storage_config = load_object_storage_config()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8080"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(phase_one_router)
    app.include_router(account_router)
    app.include_router(standards_router)
    app.include_router(updates_router)
    app.router.on_startup.append(app.state.generation_queue.start)
    app.router.on_shutdown.append(app.state.generation_queue.stop)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "live"}

    @app.get("/health/ready")
    async def ready() -> dict[str, str]:
        return {"status": "ready"}

    @app.get("/api/v1/health/live")
    async def api_v1_live() -> dict[str, str]:
        return {"status": "live"}

    @app.get("/api/v1/health/ready")
    async def api_v1_ready() -> dict[str, str]:
        return {"status": "ready"}

    return app


def load_local_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def should_load_local_env_for_process() -> bool:
    return not any(marker in argument for argument in sys.argv for marker in ("pytest", "unittest"))


app = create_app(load_env=should_load_local_env_for_process())
