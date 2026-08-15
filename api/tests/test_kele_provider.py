from __future__ import annotations

from base64 import b64encode
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from app.providers.kele import KeleConfig, KeleGptImage2Provider


class FakeImages:
    def __init__(self, response: object | None = None, failures: list[Exception] | None = None):
        self.response = response
        self.failures = failures or []
        self.calls: list[dict[str, object]] = []
        self.edit_calls: list[dict[str, object]] = []

    def generate(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if self.failures:
            raise self.failures.pop(0)
        return self.response

    def edit(self, **kwargs: object) -> object:
        self.edit_calls.append(kwargs)
        if self.failures:
            raise self.failures.pop(0)
        return self.response


class FakeOpenAIClient:
    def __init__(self, images: FakeImages):
        self.images = images


class KeleProviderTests(unittest.TestCase):
    def test_rejects_missing_reference_image_before_openai_client_call(self):
        calls = 0

        def client_factory(**_kwargs: object) -> FakeOpenAIClient:
            nonlocal calls
            calls += 1
            return FakeOpenAIClient(FakeImages())

        provider = KeleGptImage2Provider(
            KeleConfig(
                base_url="https://code28.ccwu.cc/v1",
                api_key="test-key",
                model="gpt-image-2",
            ),
            client_factory=client_factory,
        )

        with self.assertRaisesRegex(RuntimeError, "KELE_REFERENCE_IMAGE_REQUIRED"):
            provider.edit_image(prompt="generate product main image", size="1024x1024", image_paths=[])
        self.assertEqual(calls, 0)

    def test_edit_image_uses_uploaded_reference_image_with_openai_client(self):
        expected_png = b"\x89PNG\r\n\x1a\nkele-edit-image"
        images = FakeImages(SimpleNamespace(data=[SimpleNamespace(b64_json=b64encode(expected_png).decode("ascii"))]))

        provider = KeleGptImage2Provider(
            KeleConfig(
                base_url="https://code28.ccwu.cc/v1",
                api_key="test-key",
                model="gpt-image-2",
            ),
            client_factory=lambda **_kwargs: FakeOpenAIClient(images),
        )

        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "product.png"
            source.write_bytes(b"uploaded-product-image")
            result = provider.edit_image(prompt="generate product main image", size="1024x1024", image_paths=[source])

        self.assertEqual(result, expected_png)
        self.assertEqual(images.calls, [])
        self.assertEqual(len(images.edit_calls), 1)
        call = images.edit_calls[0]
        self.assertEqual(call["model"], "gpt-image-2")
        self.assertEqual(call["prompt"], "generate product main image")
        self.assertEqual(call["size"], "1024x1024")
        self.assertEqual(call["n"], 1)
        self.assertEqual(Path(call["image"][0].name).name, "product.png")

    def test_rejects_missing_api_key_before_openai_client_call(self):
        calls = 0

        def client_factory(**_kwargs: object) -> FakeOpenAIClient:
            nonlocal calls
            calls += 1
            return FakeOpenAIClient(FakeImages())

        provider = KeleGptImage2Provider(
            KeleConfig(base_url="https://code28.ccwu.cc/v1", api_key="", model="gpt-image-2"),
            client_factory=client_factory,
        )

        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "product.png"
            source.write_bytes(b"uploaded-product-image")
            with self.assertRaisesRegex(RuntimeError, "KELE_API_KEY"):
                provider.edit_image(prompt="generate product main image", size="1024x1024", image_paths=[source])
        self.assertEqual(calls, 0)

    def test_decodes_url_response_by_downloading_generated_image(self):
        images = FakeImages(SimpleNamespace(data=[SimpleNamespace(url="https://cdn.example/generated.png")]))
        seen_urls: list[str] = []

        def url_fetcher(url: str, timeout: int) -> bytes:
            seen_urls.append(f"{url}|{timeout}")
            return b"\x89PNG\r\n\x1a\nurl-image"

        provider = KeleGptImage2Provider(
            KeleConfig(
                base_url="https://code28.ccwu.cc/v1",
                api_key="test-key",
                model="gpt-image-2",
                timeout_seconds=321,
            ),
            client_factory=lambda **_kwargs: FakeOpenAIClient(images),
            url_fetcher=url_fetcher,
        )

        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "product.png"
            source.write_bytes(b"uploaded-product-image")
            result = provider.edit_image(prompt="generate product main image", size="1024x1024", image_paths=[source])

        self.assertEqual(result, b"\x89PNG\r\n\x1a\nurl-image")
        self.assertEqual(seen_urls, ["https://cdn.example/generated.png|321"])

    def test_retries_retryable_kele_http_errors(self):
        expected_png = b"\x89PNG\r\n\x1a\nretried-kele-image"
        images = FakeImages(
            SimpleNamespace(data=[SimpleNamespace(b64_json=b64encode(expected_png).decode("ascii"))]),
            failures=[RuntimeError("KELE_HTTP_429: upstream busy")],
        )
        sleeps: list[float] = []
        provider = KeleGptImage2Provider(
            KeleConfig(base_url="https://code28.ccwu.cc/v1", api_key="test-key", model="gpt-image-2"),
            client_factory=lambda **_kwargs: FakeOpenAIClient(images),
            retry_sleep=sleeps.append,
            retry_base_delay_seconds=0,
        )

        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "product.png"
            source.write_bytes(b"uploaded-product-image")
            result = provider.edit_image(prompt="generate product main image", size="1024x1024", image_paths=[source])

        self.assertEqual(result, expected_png)
        self.assertEqual(len(images.edit_calls), 2)
        self.assertEqual(images.calls, [])
        self.assertEqual(sleeps, [0])

    def test_reports_timeout_after_retries_exhausted(self):
        images = FakeImages(failures=[TimeoutError("The read operation timed out"), TimeoutError("The read operation timed out")])
        provider = KeleGptImage2Provider(
            KeleConfig(base_url="https://code28.ccwu.cc/v1", api_key="test-key", model="gpt-image-2"),
            client_factory=lambda **_kwargs: FakeOpenAIClient(images),
            retry_sleep=lambda _seconds: None,
            retry_base_delay_seconds=0,
            max_attempts=2,
        )

        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "product.png"
            source.write_bytes(b"uploaded-product-image")
            with self.assertRaisesRegex(RuntimeError, "KELE_TIMEOUT"):
                provider.edit_image(prompt="generate product main image", size="1024x1024", image_paths=[source])


if __name__ == "__main__":
    unittest.main()
