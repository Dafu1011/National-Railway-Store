from __future__ import annotations

from base64 import b64decode
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
import re
import socket
import time
from typing import Any, Callable

import httpx


@dataclass(frozen=True)
class KeleConfig:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: int = 120
    extra_headers: dict[str, str] = field(default_factory=dict)


ClientFactory = Callable[..., Any]
UrlFetcher = Callable[[str, int], bytes]
RetrySleep = Callable[[float], None]

RESULT_IMAGE_DOWNLOAD_HEADERS = {
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}


class KeleGptImage2Provider:
    name = "kele-gpt-image-2"

    def __init__(
        self,
        config: KeleConfig,
        client_factory: ClientFactory | None = None,
        url_fetcher: UrlFetcher | None = None,
        retry_sleep: RetrySleep = time.sleep,
        retry_base_delay_seconds: float = 5,
        max_attempts: int = 3,
    ):
        self.config = config
        self._client_factory = client_factory or _default_client_factory
        self._url_fetcher = url_fetcher or _default_url_fetcher
        self._retry_sleep = retry_sleep
        self._retry_base_delay_seconds = retry_base_delay_seconds
        self._max_attempts = max(1, max_attempts)
        self._openai_client: Any | None = None

    def edit_image(self, *, prompt: str, size: str, image_paths: list[Any]) -> bytes:
        self._validate_reference_images(image_paths)
        self._validate_config()
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._create_image(prompt=prompt, size=size, image_paths=image_paths)
                return decode_image_response(response, self._url_fetcher, self.config.timeout_seconds)
            except Exception as exc:
                error = _normalize_provider_exception(exc)
                if attempt >= self._max_attempts or not _is_retryable_provider_error(str(error)):
                    raise error from exc
                self._retry_sleep(_retry_delay_seconds(error, self._retry_base_delay_seconds, attempt, exc))
        raise RuntimeError("KELE_RETRY_EXHAUSTED")

    def _create_image(self, *, prompt: str, size: str, image_paths: list[Any]) -> Any:
        with ExitStack() as stack:
            image_files = [stack.enter_context(Path(path).open("rb")) for path in image_paths]
            return self._get_client().images.edit(
                model=self.config.model,
                image=image_files,
                prompt=prompt,
                size=size,
                n=1,
            )

    def _get_client(self) -> Any:
        if self._openai_client is None:
            kwargs: dict[str, Any] = {
                "base_url": self.config.base_url,
                "api_key": self.config.api_key,
                "timeout": self.config.timeout_seconds,
            }
            if self.config.extra_headers:
                kwargs["default_headers"] = self.config.extra_headers
            self._openai_client = self._client_factory(**kwargs)
        return self._openai_client

    def _validate_config(self) -> None:
        if not self.config.api_key:
            raise RuntimeError("KELE_API_KEY is required before calling Kele GPT-Image-2.")
        if not self.config.base_url:
            raise RuntimeError("KELE_BASE_URL is required before calling Kele GPT-Image-2.")

    def _validate_reference_images(self, image_paths: list[Any]) -> None:
        if not image_paths:
            raise RuntimeError("KELE_REFERENCE_IMAGE_REQUIRED: 请先上传商品图后再生成。")


def decode_image_response(response: Any, url_fetcher: UrlFetcher, timeout_seconds: int) -> bytes:
    candidates: list[Any] = []
    data = _value(response, "data")
    if isinstance(data, list):
        candidates.extend(data)
    elif data is not None:
        candidates.append(data)
    if not candidates:
        candidates.append(response)

    for item in candidates:
        encoded = _value(item, "b64_json") or _value(item, "base64") or _value(item, "image_base64")
        if isinstance(encoded, str) and encoded.strip():
            return b64decode(encoded)
        url = _value(item, "url")
        if isinstance(url, str) and url.strip():
            return url_fetcher(url, timeout_seconds)
    raise RuntimeError("KELE_RESPONSE_IMAGE_MISSING")


def _value(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _default_client_factory(**kwargs: Any) -> Any:
    from openai import OpenAI

    return OpenAI(**kwargs)


def _default_url_fetcher(url: str, timeout: int) -> bytes:
    try:
        response = httpx.get(
            url,
            timeout=timeout,
            follow_redirects=True,
            headers=RESULT_IMAGE_DOWNLOAD_HEADERS,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        detail = _response_body_snippet(exc.response)
        raise RuntimeError(f"KELE_RESULT_DOWNLOAD_HTTP_{status_code}: {detail}") from exc
    except httpx.TimeoutException as exc:
        raise RuntimeError(f"KELE_RESULT_DOWNLOAD_TIMEOUT: {exc}") from exc
    except httpx.RequestError as exc:
        raise RuntimeError(f"KELE_RESULT_DOWNLOAD_NETWORK_ERROR: {exc}") from exc

    content = response.content
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if not content:
        raise RuntimeError("KELE_RESULT_DOWNLOAD_EMPTY")
    if content_type and not content_type.startswith("image/") and not _looks_like_image(content):
        detail = _response_body_snippet(response)
        raise RuntimeError(
            f"KELE_RESULT_DOWNLOAD_NOT_IMAGE: status={response.status_code} content_type={content_type} body={detail}"
        )
    return content


def _is_retryable_provider_error(message: str) -> bool:
    return (
        message.startswith("KELE_HTTP_429")
        or message.startswith("KELE_HTTP_500")
        or message.startswith("KELE_HTTP_502")
        or message.startswith("KELE_HTTP_503")
        or message.startswith("KELE_HTTP_504")
        or message.startswith("KELE_HTTP_524")
        or message.startswith("KELE_NETWORK_ERROR")
        or message.startswith("KELE_TIMEOUT")
        or message.startswith("KELE_RESULT_DOWNLOAD_HTTP_429")
        or message.startswith("KELE_RESULT_DOWNLOAD_HTTP_500")
        or message.startswith("KELE_RESULT_DOWNLOAD_HTTP_502")
        or message.startswith("KELE_RESULT_DOWNLOAD_HTTP_503")
        or message.startswith("KELE_RESULT_DOWNLOAD_HTTP_504")
        or message.startswith("KELE_RESULT_DOWNLOAD_HTTP_524")
        or message.startswith("KELE_RESULT_DOWNLOAD_NETWORK_ERROR")
        or message.startswith("KELE_RESULT_DOWNLOAD_TIMEOUT")
    )


def _retry_delay_seconds(error: RuntimeError, base_delay_seconds: float, attempt: int, source_exc: Exception) -> float:
    exponential_delay = base_delay_seconds * (2 ** (attempt - 1))
    retry_after = _provider_retry_after_seconds(str(error))
    if retry_after is None:
        retry_after = _response_retry_after_seconds(getattr(source_exc, "response", None))
    if retry_after is None:
        return exponential_delay
    return max(exponential_delay, retry_after)


def _provider_retry_after_seconds(message: str) -> float | None:
    match = re.search(r"['\"]retry_after['\"]\s*:\s*([0-9]+(?:\.[0-9]+)?)", message)
    if match is None:
        return None
    return float(match.group(1))


def _response_retry_after_seconds(response: Any) -> float | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    retry_after = None
    if hasattr(headers, "get"):
        retry_after = headers.get("retry-after") or headers.get("Retry-After")
    if retry_after is None:
        return None
    try:
        return float(retry_after)
    except (TypeError, ValueError):
        return None


def _normalize_provider_exception(exc: Exception) -> RuntimeError:
    if isinstance(exc, RuntimeError) and str(exc).startswith("KELE_"):
        return exc
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return RuntimeError(f"KELE_HTTP_{status_code}: {exc}")
    if isinstance(exc, httpx.HTTPStatusError):
        return RuntimeError(f"KELE_RESULT_DOWNLOAD_HTTP_{exc.response.status_code}: {_response_body_snippet(exc.response)}")
    if isinstance(exc, httpx.TimeoutException):
        return RuntimeError(f"KELE_RESULT_DOWNLOAD_TIMEOUT: {exc}")
    if isinstance(exc, httpx.RequestError):
        return RuntimeError(f"KELE_RESULT_DOWNLOAD_NETWORK_ERROR: {exc}")
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return RuntimeError(f"KELE_TIMEOUT: {exc}")
    if isinstance(exc, RuntimeError):
        return exc
    return RuntimeError(f"KELE_ERROR: {exc}")


def _looks_like_image(content: bytes) -> bool:
    return (
        content.startswith(b"\x89PNG\r\n\x1a\n")
        or content.startswith(b"\xff\xd8\xff")
        or content.startswith(b"GIF87a")
        or content.startswith(b"GIF89a")
        or content.startswith(b"RIFF") and content[8:12] == b"WEBP"
        or content.startswith(b"BM")
        or content.startswith(b"II*\x00")
        or content.startswith(b"MM\x00*")
    )


def _response_body_snippet(response: httpx.Response, limit: int = 200) -> str:
    text_value = getattr(response, "text", None)
    if isinstance(text_value, str):
        text = text_value
    else:
        content = getattr(response, "content", b"")
        text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else ""
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] or f"status={response.status_code}"
