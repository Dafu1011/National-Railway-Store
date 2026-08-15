from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import json
import os
import threading
import time
from typing import Any, Iterator


@dataclass
class LocalRuntimeServices:
    locks: dict[str, float] = field(default_factory=dict)
    counters: dict[str, tuple[int, float]] = field(default_factory=dict)
    slots: dict[str, tuple[int, float]] = field(default_factory=dict)
    cache: dict[str, tuple[str, float]] = field(default_factory=dict)
    mutex: threading.Lock = field(default_factory=threading.Lock)

    @contextmanager
    def lock(self, key: str, ttl_seconds: int = 30) -> Iterator[None]:
        expires_at = time.time() + ttl_seconds
        with self.mutex:
            existing = self.locks.get(key)
            if existing and existing > time.time():
                raise RuntimeError(f"LOCK_BUSY:{key}")
            self.locks[key] = expires_at
        try:
            yield
        finally:
            with self.mutex:
                if self.locks.get(key) == expires_at:
                    self.locks.pop(key, None)

    def hit_rate_limit(self, key: str, *, limit: int, window_seconds: int) -> bool:
        now = time.time()
        with self.mutex:
            count, reset_at = self.counters.get(key, (0, now + window_seconds))
            if reset_at <= now:
                count, reset_at = 0, now + window_seconds
            count += 1
            self.counters[key] = (count, reset_at)
            return count > limit

    def get_cache_json(self, key: str) -> Any | None:
        now = time.time()
        with self.mutex:
            cached = self.cache.get(key)
            if cached is None:
                return None
            raw_value, expires_at = cached
            if expires_at <= now:
                self.cache.pop(key, None)
                return None
        return json.loads(raw_value)

    def set_cache_json(self, key: str, value: Any, *, ttl_seconds: int) -> None:
        with self.mutex:
            self.cache[key] = (json.dumps(value, ensure_ascii=False), time.time() + ttl_seconds)

    def delete_cache(self, key: str) -> None:
        with self.mutex:
            self.cache.pop(key, None)

    @contextmanager
    def slot(self, key: str, *, limit: int, ttl_seconds: int = 600) -> Iterator[None]:
        if limit <= 0:
            raise RuntimeError(f"SLOT_BUSY:{key}")
        now = time.time()
        expires_at = now + ttl_seconds
        with self.mutex:
            count, reset_at = self.slots.get(key, (0, expires_at))
            if reset_at <= now:
                count, reset_at = 0, expires_at
            if count >= limit:
                raise RuntimeError(f"SLOT_BUSY:{key}")
            self.slots[key] = (count + 1, expires_at)
        try:
            yield
        finally:
            with self.mutex:
                current_count, current_reset_at = self.slots.get(key, (0, expires_at))
                next_count = max(current_count - 1, 0)
                if next_count:
                    self.slots[key] = (next_count, current_reset_at)
                else:
                    self.slots.pop(key, None)


class RedisRuntimeServices:
    def __init__(self, redis_url: str):
        from redis import Redis

        self.client = Redis.from_url(redis_url, decode_responses=True)

    @contextmanager
    def lock(self, key: str, ttl_seconds: int = 30) -> Iterator[None]:
        lock = self.client.lock(key, timeout=ttl_seconds, blocking_timeout=0)
        if not lock.acquire(blocking=False):
            raise RuntimeError(f"LOCK_BUSY:{key}")
        try:
            yield
        finally:
            # The redis-py lock token check prevents deleting another worker's renewed lock.
            lock.release()

    def hit_rate_limit(self, key: str, *, limit: int, window_seconds: int) -> bool:
        count = self.client.incr(key)
        if count == 1:
            self.client.expire(key, window_seconds)
        return int(count) > limit

    def get_cache_json(self, key: str) -> Any | None:
        raw_value = self.client.get(key)
        if raw_value is None:
            return None
        return json.loads(raw_value)

    def set_cache_json(self, key: str, value: Any, *, ttl_seconds: int) -> None:
        self.client.set(key, json.dumps(value, ensure_ascii=False), ex=ttl_seconds)

    def delete_cache(self, key: str) -> None:
        self.client.delete(key)

    @contextmanager
    def slot(self, key: str, *, limit: int, ttl_seconds: int = 600) -> Iterator[None]:
        if limit <= 0:
            raise RuntimeError(f"SLOT_BUSY:{key}")
        count = int(self.client.incr(key))
        if count == 1:
            self.client.expire(key, ttl_seconds)
        if count > limit:
            self.client.decr(key)
            raise RuntimeError(f"SLOT_BUSY:{key}")
        try:
            yield
        finally:
            # Expiring counters protect against leaked slots if a worker is killed mid-generation.
            remaining = int(self.client.decr(key))
            if remaining <= 0:
                self.client.delete(key)


def build_runtime_services() -> LocalRuntimeServices | RedisRuntimeServices:
    redis_url = os.getenv("REDIS_URL", "").strip()
    app_env = os.getenv("APP_ENV", "development").lower()
    if not redis_url or app_env in {"test", "local"}:
        return LocalRuntimeServices()
    try:
        return RedisRuntimeServices(redis_url)
    except ModuleNotFoundError:
        if app_env == "production":
            raise
        # 桌面本地调试允许降级到内存锁；生产环境必须安装并连接 Redis。
        return LocalRuntimeServices()
