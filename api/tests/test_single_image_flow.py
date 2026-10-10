from __future__ import annotations

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import Mock

from fastapi.testclient import TestClient
from PIL import Image

from app.main import create_app
from app.providers.kele import KeleGptImage2Provider
from app.providers.single_image import KeleSingleImageProvider, SingleGeneratedImage
from tests.test_account_billing import auth_header, make_admin, recharge
from tests.test_phase_one_flow import verified_token


class SingleImageFlowTests(unittest.TestCase):
    def test_prompt_only_generation_charges_two_points_and_appears_in_gallery(self):
        with TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir)
            with TestClient(app) as client:
                admin_token = verified_token(client, "single-admin@qq.com")
                user_token = verified_token(client, "single-user@qq.com")
                make_admin(app, "single-admin@qq.com")
                user = client.get("/api/v1/users/me", headers=auth_header(user_token)).json()
                recharge(client, admin_token, user["id"])

                response = client.post(
                    "/api/v1/single-image-jobs",
                    headers=auth_header(user_token),
                    json={"prompt": "生成一张白底商品海报", "asset_version_ids": []},
                )

                self.assertEqual(response.status_code, 202, response.text)
                job = wait_for_single_image_status(client, auth_header(user_token), response.json()["id"], {"completed"})
                self.assertEqual(job["status"], "completed")
                self.assertEqual(len(job["outputs"]), 1)
                self.assertEqual((job["outputs"][0]["width"], job["outputs"][0]["height"]), (800, 800))
                account = client.get("/api/v1/account/me", headers=auth_header(user_token)).json()
                self.assertEqual(account["balance_points"], 9998)
                self.assertEqual(account["reserved_points"], 0)
                transactions = client.get("/api/v1/account/transactions", headers=auth_header(user_token)).json()["items"]
                self.assertEqual(transactions[0]["type"], "generation_charge")
                self.assertEqual(transactions[0]["points"], -2)

                gallery = client.get("/api/v1/gallery/outputs", headers=auth_header(user_token)).json()["items"]
                single_items = [item for item in gallery if item.get("source") == "single_image"]
                self.assertEqual(len(single_items), 1)
                self.assertEqual(single_items[0]["output_type"], "single")
                self.assertEqual((single_items[0]["width"], single_items[0]["height"]), (800, 800))
                thumbnail = client.get(single_items[0]["thumbnail_url"], headers=auth_header(user_token))
                download = client.get(single_items[0]["download_url"], headers=auth_header(user_token))
                self.assertEqual(thumbnail.status_code, 200)
                self.assertEqual(download.status_code, 200)
                with Image.open(BytesIO(download.content)) as image:
                    self.assertEqual(image.size, (800, 800))
                    self.assertEqual(image.format, "PNG")
                with Image.open(BytesIO(thumbnail.content)) as image:
                    self.assertEqual(image.size, (320, 320))

    def test_generation_with_multiple_reference_images_records_asset_count(self):
        with TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir)
            provider = Mock(spec=KeleGptImage2Provider)
            raw = BytesIO()
            Image.new("RGB", (1600, 800), "navy").save(raw, format="PNG")
            provider.edit_image.return_value = raw.getvalue()
            app.state.single_image_provider_override = KeleSingleImageProvider(provider)
            with TestClient(app) as client:
                # Provider overrides execute synchronously; keep the background worker out of this request.
                app.state.generation_queue.stop()
                admin_token = verified_token(client, "single-ref-admin@qq.com")
                user_token = verified_token(client, "single-ref-user@qq.com")
                make_admin(app, "single-ref-admin@qq.com")
                user = client.get("/api/v1/users/me", headers=auth_header(user_token)).json()
                recharge(client, admin_token, user["id"])
                headers = auth_header(user_token)
                first_asset = upload_single_reference(client, headers, "first.png")
                second_asset = upload_single_reference(client, headers, "second.png")

                response = client.post(
                    "/api/v1/single-image-jobs",
                    headers=headers,
                    json={
                        "prompt": "参考两张图片生成一个新场景",
                        "asset_version_ids": [first_asset["version_id"], second_asset["version_id"]],
                    },
                )

                self.assertEqual(response.status_code, 202, response.text)
                job = wait_for_single_image_status(client, headers, response.json()["id"], {"completed"})
                self.assertEqual(job["reference_asset_count"], 2)
                self.assertEqual(job["outputs"][0]["output_type"], "single")
                output = job["outputs"][0]
                self.assertEqual((output["width"], output["height"]), (800, 800))
                download = client.get(output["download_url"], headers=headers)
                self.assertEqual(download.status_code, 200)
                with Image.open(BytesIO(download.content)) as image:
                    self.assertEqual(image.size, (800, 800))
                    self.assertEqual(image.getpixel((400, 100)), (255, 255, 255))
                    self.assertEqual(image.getpixel((400, 400)), (0, 0, 128))
                with app.state.storage.connect() as connection:
                    stored = connection.execute(
                        "SELECT width, height FROM single_image_outputs WHERE id = ? AND user_id = ?",
                        (output["id"], user["id"]),
                    ).fetchone()
                self.assertEqual((stored["width"], stored["height"]), (800, 800))
                self.assertEqual(provider.edit_image.call_count, 1)
                self.assertEqual(len(provider.edit_image.call_args.kwargs["image_paths"]), 2)
                provider.generate_image.assert_not_called()
                account = client.get("/api/v1/account/me", headers=headers).json()
                self.assertEqual(account["balance_points"], 9998)
                self.assertEqual(account["reserved_points"], 0)

    def test_single_image_output_folder_uses_safe_username_time_and_job_suffix(self):
        captured_job_ids: list[str] = []

        class CapturingSingleImageProvider:
            name = "capturing-single-image-provider"

            def generate_single_image(self, *, output_dir, job_id, prompt, reference_image_paths):
                captured_job_ids.append(job_id)
                job_dir = output_dir / "single-image" / job_id
                job_dir.mkdir(parents=True, exist_ok=True)
                path = job_dir / "single.png"
                Image.new("RGB", (800, 800), "white").save(path)
                return SingleGeneratedImage(output_type="single", width=800, height=800, path=path)

        with TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir)
            app.state.single_image_provider_override = CapturingSingleImageProvider()
            with TestClient(app) as client:
                app.state.generation_queue.stop()
                admin_token = verified_token(client, "single-folder-admin@qq.com")
                user_token = verified_token(client, "single-folder-user@qq.com")
                make_admin(app, "single-folder-admin@qq.com")
                user = client.get("/api/v1/users/me", headers=auth_header(user_token)).json()
                recharge(client, admin_token, user["id"])

                response = client.post(
                    "/api/v1/single-image-jobs",
                    headers=auth_header(user_token),
                    json={"prompt": "生成一张白底商品海报", "asset_version_ids": []},
                )

                self.assertEqual(response.status_code, 202, response.text)
                job_id = response.json()["id"]
                self.assertEqual(response.json()["status"], "completed")
                self.assertEqual(len(captured_job_ids), 1)
                self.assertNotEqual(captured_job_ids[0], job_id)
                self.assertRegex(captured_job_ids[0], rf"^single-folder-user_\d{{8}}_\d{{6}}_{job_id.replace('-', '')[:8]}$")

    def test_failed_generation_releases_two_point_hold_without_charge(self):
        with TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir)
            app.state.single_image_provider_override = FailingSingleImageProvider()
            with TestClient(app) as client:
                app.state.generation_queue.stop()
                admin_token = verified_token(client, "single-fail-admin@qq.com")
                user_token = verified_token(client, "single-fail-user@qq.com")
                make_admin(app, "single-fail-admin@qq.com")
                user = client.get("/api/v1/users/me", headers=auth_header(user_token)).json()
                recharge(client, admin_token, user["id"])

                response = client.post(
                    "/api/v1/single-image-jobs",
                    headers=auth_header(user_token),
                    json={"prompt": "这次生成会失败", "asset_version_ids": []},
                )

                self.assertEqual(response.status_code, 202, response.text)
                job = wait_for_single_image_status(client, auth_header(user_token), response.json()["id"], {"failed"})
                self.assertEqual(job["status"], "failed")
                account = client.get("/api/v1/account/me", headers=auth_header(user_token)).json()
                self.assertEqual(account["balance_points"], 10000)
                self.assertEqual(account["reserved_points"], 0)
                transactions = client.get("/api/v1/account/transactions", headers=auth_header(user_token)).json()["items"]
                self.assertNotIn("generation_charge", {item["type"] for item in transactions})

    def test_invalid_output_file_or_metadata_fails_without_publishing_or_charging(self):
        class InvalidOutputProvider:
            name = "invalid-single-output"

            def __init__(self, actual_size, reported_size, file_format):
                self.actual_size = actual_size
                self.reported_size = reported_size
                self.file_format = file_format

            def generate_single_image(self, *, output_dir, job_id, **_kwargs):
                folder = output_dir / "single-image" / job_id
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / "single.png"
                if self.file_format == "invalid":
                    path.write_bytes(b"not-an-image")
                else:
                    Image.new("RGB", self.actual_size, "white").save(path, format=self.file_format)
                return SingleGeneratedImage(
                    output_type="single", width=self.reported_size[0], height=self.reported_size[1], path=path,
                )

        cases = (
            ((1024, 1024), (800, 800), "PNG"),
            ((800, 800), (1024, 1024), "PNG"),
            ((800, 800), (800, 800), "JPEG"),
            ((800, 800), (800, 800), "invalid"),
        )
        with TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir)
            with TestClient(app) as client:
                # Each invalid provider is tested on the synchronous override route only.
                app.state.generation_queue.stop()
                admin_token = verified_token(client, "single-invalid-admin@qq.com")
                user_token = verified_token(client, "single-invalid-user@qq.com")
                make_admin(app, "single-invalid-admin@qq.com")
                headers = auth_header(user_token)
                user = client.get("/api/v1/users/me", headers=headers).json()
                recharge(client, admin_token, user["id"])
                for actual_size, reported_size, file_format in cases:
                    with self.subTest(actual_size=actual_size, reported_size=reported_size, file_format=file_format):
                        app.state.single_image_provider_override = InvalidOutputProvider(actual_size, reported_size, file_format)
                        response = client.post(
                            "/api/v1/single-image-jobs", headers=headers,
                            json={"prompt": "校验输出真实尺寸", "asset_version_ids": []},
                        )
                        self.assertEqual(response.status_code, 202, response.text)
                        job = response.json()
                        self.assertEqual(job["status"], "failed")
                        self.assertEqual(job["error_code"], "IMAGE_PROVIDER_FAILED")
                        self.assertEqual(job["outputs"], [])
                        with app.state.storage.connect() as connection:
                            output_count = connection.execute(
                                "SELECT COUNT(*) FROM single_image_outputs WHERE job_id = ? AND user_id = ?",
                                (job["id"], user["id"]),
                            ).fetchone()[0]
                        self.assertEqual(output_count, 0)
                        account = client.get("/api/v1/account/me", headers=headers).json()
                        self.assertEqual(account["balance_points"], 10000)
                        self.assertEqual(account["reserved_points"], 0)
                        transactions = client.get("/api/v1/account/transactions", headers=headers).json()["items"]
                        self.assertNotIn("generation_charge", {item["type"] for item in transactions})


class FailingSingleImageProvider:
    name = "failing-single-image-provider"

    def generate_single_image(self, **_kwargs: object) -> object:
        raise RuntimeError("single image provider failed")


def upload_single_reference(client: TestClient, headers: dict[str, str], filename: str) -> dict[str, object]:
    image_bytes = make_png_bytes()
    presign = client.post(
        "/api/v1/uploads/presign",
        headers=headers,
        json={
            "asset_type": "single_image_reference",
            "filename": filename,
            "content_type": "image/png",
            "size_bytes": len(image_bytes),
        },
    )
    assert presign.status_code == 201, presign.text
    upload = presign.json()
    put_response = client.put(upload["upload_url"], headers=upload["headers"], content=image_bytes)
    assert put_response.status_code == 204, put_response.text
    complete = client.post("/api/v1/uploads/complete", headers=headers, json={"upload_token": upload["upload_token"]})
    assert complete.status_code == 201, complete.text
    return complete.json()


def make_png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (128, 128), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def wait_for_single_image_status(
    client: TestClient,
    headers: dict[str, str],
    job_id: str,
    statuses: set[str],
) -> dict[str, object]:
    deadline = time.time() + 5
    last_payload: dict[str, object] | None = None
    while time.time() < deadline:
        response = client.get(f"/api/v1/single-image-jobs/{job_id}", headers=headers)
        assert response.status_code == 200, response.text
        last_payload = response.json()
        if last_payload["status"] in statuses:
            return last_payload
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not reach {statuses}; last={last_payload}")


if __name__ == "__main__":
    unittest.main()
