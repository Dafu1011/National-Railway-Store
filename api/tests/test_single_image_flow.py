from __future__ import annotations

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from fastapi.testclient import TestClient
from PIL import Image

from app.main import create_app
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
                thumbnail = client.get(single_items[0]["thumbnail_url"], headers=auth_header(user_token))
                download = client.get(single_items[0]["download_url"], headers=auth_header(user_token))
                self.assertEqual(thumbnail.status_code, 200)
                self.assertEqual(download.status_code, 200)

    def test_generation_with_multiple_reference_images_records_asset_count(self):
        with TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir)
            with TestClient(app) as client:
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

    def test_failed_generation_releases_two_point_hold_without_charge(self):
        with TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir)
            app.state.single_image_provider_override = FailingSingleImageProvider()
            with TestClient(app) as client:
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
