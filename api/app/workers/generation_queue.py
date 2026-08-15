from __future__ import annotations

import os
import threading
import time
from typing import Any

from app.storage import AppStorage


class GenerationQueue:
    def __init__(self, storage: AppStorage, runtime_services: Any):
        self.storage = storage
        self.runtime_services = runtime_services
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        if self._threads:
            return
        worker_count = configured_positive_int(
            "GENERATION_WORKER_CONCURRENCY",
            configured_positive_int("PROVIDER_MAX_CONCURRENCY", 2),
        )
        self._stop_event.clear()
        for index in range(worker_count):
            thread = threading.Thread(
                target=self._run,
                name=f"generation-queue-{index + 1}",
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        for thread in self._threads:
            thread.join(timeout=5)
        self._threads.clear()

    def notify(self) -> None:
        self._wake_event.set()

    def _run(self) -> None:
        from app.api import phase_one

        while not self._stop_event.is_set():
            processed = phase_one.process_next_queued_generation_job(
                self.storage,
                self.runtime_services,
            )
            if processed:
                continue
            self._wake_event.wait(configured_positive_float("GENERATION_QUEUE_POLL_SECONDS", 0.25))
            self._wake_event.clear()


def configured_positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def configured_positive_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default
