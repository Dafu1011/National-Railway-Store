from io import BytesIO
import os
import time
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient
from PIL import Image

from app.api import phase_one
from app.main import create_app
from app.providers.real_image import GeneratedImage


class PhaseOneFlowTests(unittest.TestCase):
    def test_email_registration_uses_mail_code_before_account_creation(self):
        with TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir)
            with TestClient(app) as client:
                missing_code_register = client.post(
                    "/api/v1/auth/register",
                    json={
                        "username": "验证用户",
                        "email": "verify-me@qq.com",
                        "verification_code": "000000",
                        "password": "StrongPass123",
                    },
                )
                self.assertEqual(missing_code_register.status_code, 400)
                self.assertEqual(missing_code_register.json()["detail"]["code"], "EMAIL_CODE_INVALID")

                send_code_response = client.post(
                    "/api/v1/auth/registration-code",
                    json={"email": "verify-me@qq.com"},
                )
                self.assertEqual(send_code_response.status_code, 202)
                send_code_payload = send_code_response.json()
                self.assertEqual(send_code_payload["email"], "verify-me@qq.com")
                self.assertEqual(len(send_code_payload["debug_code"]), 6)

                wrong_code_register = client.post(
                    "/api/v1/auth/register",
                    json={
                        "username": "验证用户",
                        "email": "verify-me@qq.com",
                        "verification_code": "111111",
                        "password": "StrongPass123",
                    },
                )
                self.assertEqual(wrong_code_register.status_code, 400)
                self.assertEqual(wrong_code_register.json()["detail"]["code"], "EMAIL_CODE_INVALID")

                register_response = client.post(
                    "/api/v1/auth/register",
                    json={
                        "username": "验证用户",
                        "email": "verify-me@qq.com",
                        "verification_code": send_code_payload["debug_code"],
                        "password": "StrongPass123",
                    },
                )
                self.assertEqual(register_response.status_code, 201)
                register_payload = register_response.json()
                self.assertEqual(register_payload["user"]["email"], "verify-me@qq.com")
                self.assertEqual(register_payload["user"]["username"], "验证用户")
                self.assertTrue(register_payload["user"]["email_verified"])
                self.assertIn("access_token", register_payload)

                login_response = client.post(
                    "/api/v1/auth/login",
                    json={"email": "verify-me@qq.com", "password": "StrongPass123"},
                )
                self.assertEqual(login_response.status_code, 200)
                self.assertIn("access_token", login_response.json())
                refresh_cookie = login_response.cookies.get("zhifeng_refresh_token")
                self.assertIsNotNone(refresh_cookie)
                set_cookie = login_response.headers.get("set-cookie", "")
                self.assertIn("HttpOnly", set_cookie)
                self.assertIn("SameSite", set_cookie)

                refresh_response = client.post("/api/v1/auth/refresh")
                self.assertEqual(refresh_response.status_code, 200)
                self.assertIn("access_token", refresh_response.json())

                logout_response = client.post("/api/v1/auth/logout")
                self.assertEqual(logout_response.status_code, 204)

                refresh_after_logout = client.post("/api/v1/auth/refresh")
                self.assertEqual(refresh_after_logout.status_code, 401)

                unsupported_email = client.post(
                    "/api/v1/auth/registration-code",
                    json={"email": "someone@example.com"},
                )
                self.assertEqual(unsupported_email.status_code, 400)
                self.assertEqual(unsupported_email.json()["detail"]["code"], "EMAIL_DOMAIN_UNSUPPORTED")

    def test_password_login_refresh_session_defaults_to_seven_days(self):
        original = os.environ.get("REFRESH_TOKEN_EXPIRE_DAYS")
        os.environ.pop("REFRESH_TOKEN_EXPIRE_DAYS", None)
        try:
            with TemporaryDirectory() as data_dir:
                app = create_app(data_dir=data_dir)
                with TestClient(app) as client:
                    verified_token(client, "seven-day-login@example.com")

                    with app.state.storage.connect() as connection:
                        row = connection.execute("SELECT created_at, expires_at FROM refresh_sessions").fetchone()

                    created_at = parse_dt(row["created_at"])
                    expires_at = parse_dt(row["expires_at"])
                    self.assertGreater(expires_at - created_at, timedelta(days=6, hours=23))
                    self.assertLess(expires_at - created_at, timedelta(days=7, minutes=1))
        finally:
            if original is None:
                os.environ.pop("REFRESH_TOKEN_EXPIRE_DAYS", None)
            else:
                os.environ["REFRESH_TOKEN_EXPIRE_DAYS"] = original

    def test_refresh_extends_login_window_from_current_use(self):
        with TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir)
            with TestClient(app) as client:
                verified_token(client, "sliding-refresh@example.com")
                with app.state.storage.connect() as connection:
                    connection.execute(
                        "UPDATE refresh_sessions SET expires_at = ?",
                        ((datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),),
                    )

                response = client.post("/api/v1/auth/refresh")

                self.assertEqual(response.status_code, 200)
                self.assertIn("Max-Age=604800", response.headers.get("set-cookie", ""))
                with app.state.storage.connect() as connection:
                    row = connection.execute("SELECT expires_at FROM refresh_sessions ORDER BY expires_at DESC LIMIT 1").fetchone()
                self.assertGreater(parse_dt(row["expires_at"]), datetime.now(timezone.utc) + timedelta(days=6, hours=23))

    def test_authenticated_api_use_extends_access_session_window(self):
        with TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir)
            with TestClient(app) as client:
                token = verified_token(client, "sliding-access@example.com")
                with app.state.storage.connect() as connection:
                    connection.execute(
                        "UPDATE sessions SET expires_at = ? WHERE token = ?",
                        ((datetime.now(timezone.utc) + timedelta(days=1)).isoformat(), token),
                    )

                response = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})

                self.assertEqual(response.status_code, 200)
                with app.state.storage.connect() as connection:
                    row = connection.execute("SELECT expires_at FROM sessions WHERE token = ?", (token,)).fetchone()
                self.assertGreater(parse_dt(row["expires_at"]), datetime.now(timezone.utc) + timedelta(days=6, hours=23))

    def test_expired_access_session_requires_password_login(self):
        with TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir)
            with TestClient(app) as client:
                token = verified_token(client, "expired-access@example.com")
                with app.state.storage.connect() as connection:
                    connection.execute(
                        "UPDATE sessions SET expires_at = ? WHERE token = ?",
                        ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), token),
                    )

                response = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})

                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()["detail"]["code"], "AUTH_REQUIRED")

    def test_expired_refresh_session_requires_password_login(self):
        with TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir)
            with TestClient(app) as client:
                verified_token(client, "expired-refresh@example.com")
                with app.state.storage.connect() as connection:
                    connection.execute(
                        "UPDATE refresh_sessions SET expires_at = ?",
                        ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),),
                    )

                response = client.post("/api/v1/auth/refresh")

                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()["detail"]["code"], "REFRESH_INVALID")

    def test_password_reset_with_email_code_changes_password_and_revokes_refresh_sessions(self):
        with TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir)
            with TestClient(app) as client:
                old_token = verified_token(client, "reset-password@example.com", password="OldPass123")
                user = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {old_token}"}).json()

                code_response = client.post("/api/v1/auth/password-reset-code", json={"email": "reset-password@qq.com"})
                self.assertEqual(code_response.status_code, 202)
                reset_response = client.post(
                    "/api/v1/auth/reset-password",
                    json={
                        "email": "reset-password@qq.com",
                        "verification_code": code_response.json()["debug_code"],
                        "new_password": "NewPass123",
                    },
                )
                self.assertEqual(reset_response.status_code, 200)
                self.assertEqual(reset_response.json()["email"], "reset-password@qq.com")

                old_token_response = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {old_token}"})
                self.assertEqual(old_token_response.status_code, 401)
                old_login = client.post("/api/v1/auth/login", json={"email": "reset-password@qq.com", "password": "OldPass123"})
                self.assertEqual(old_login.status_code, 401)
                new_login = client.post("/api/v1/auth/login", json={"email": "reset-password@qq.com", "password": "NewPass123"})
                self.assertEqual(new_login.status_code, 200)
                with app.state.storage.connect() as connection:
                    old_refresh = connection.execute(
                        "SELECT revoked_at FROM refresh_sessions WHERE user_id = ? ORDER BY created_at ASC LIMIT 1",
                        (user["id"],),
                    ).fetchone()
                self.assertIsNotNone(old_refresh["revoked_at"])

    def test_upload_object_keys_are_namespaced_by_user_material_library(self):
        with TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir)
            with TestClient(app) as client:
                token = verified_token(client, "library-owner@example.com")
                headers = {"Authorization": f"Bearer {token}"}
                png = make_png_bytes()

                presign = client.post(
                    "/api/v1/uploads/presign",
                    headers=headers,
                    json={
                        "asset_type": "product_original",
                        "filename": "cup.png",
                        "content_type": "image/png",
                        "size_bytes": len(png),
                    },
                )

                self.assertEqual(presign.status_code, 201)
                user_id = client.get("/api/v1/users/me", headers=headers).json()["id"]
                self.assertTrue(presign.json()["object_key"].startswith(f"users/{user_id}/materials/pending/"))

    def test_generation_requires_uploaded_product_original_asset(self):
        with TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir)
            with TestClient(app) as client:
                token = verified_token(client, "asset-required@example.com")
                headers = {"Authorization": f"Bearer {token}"}
                product = client.post(
                    "/api/v1/products",
                    headers=headers,
                    json={"name": "Asset Required Cup", "brand": "Zhifeng", "model": "A1"},
                ).json()
                project = client.post(
                    "/api/v1/projects",
                    headers=headers,
                    json={
                        "product_id": product["id"],
                        "name": "Asset Required Project",
                        "barcode": {"barcode_type": "EAN_13", "raw_value": "4006381333931", "confirmed": True},
                    },
                ).json()

                response = client.post(f"/api/v1/projects/{project['id']}/generate", headers=headers)

                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["detail"]["code"], "PRODUCT_ORIGINAL_ASSET_REQUIRED")

    def test_uploading_product_original_asset_unblocks_generation(self):
        with TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir)
            with TestClient(app) as client:
                token = verified_token(client, "asset-flow@example.com")
                headers = {"Authorization": f"Bearer {token}"}
                product = client.post(
                    "/api/v1/products",
                    headers=headers,
                    json={"name": "Uploaded Cup", "brand": "Zhifeng", "model": "A2"},
                ).json()

                png = make_png_bytes()
                presign = client.post(
                    "/api/v1/uploads/presign",
                    headers=headers,
                    json={
                        "asset_type": "product_original",
                        "filename": "cup.png",
                        "content_type": "image/png",
                        "size_bytes": len(png),
                    },
                )
                self.assertEqual(presign.status_code, 201)
                presign_payload = presign.json()
                upload = client.put(
                    presign_payload["upload_url"],
                    content=png,
                    headers={"content-type": "image/png"},
                )
                self.assertEqual(upload.status_code, 204)
                complete = client.post(
                    "/api/v1/uploads/complete",
                    headers=headers,
                    json={"upload_token": presign_payload["upload_token"], "product_id": product["id"]},
                )
                self.assertEqual(complete.status_code, 201)
                self.assertEqual(complete.json()["asset_type"], "product_original")

                project = client.post(
                    "/api/v1/projects",
                    headers=headers,
                    json={
                        "product_id": product["id"],
                        "name": "Uploaded Asset Project",
                        "barcode": {"barcode_type": "EAN_13", "raw_value": "4006381333931", "confirmed": True},
                    },
                ).json()
                grant_test_points(app, product["user_id"])
                generation_response = client.post(f"/api/v1/projects/{project['id']}/generate", headers=headers)

                self.assertEqual(generation_response.status_code, 202)
                generation = wait_for_generation_status(client, headers, generation_response.json()["id"], {"completed"})
                self.assertEqual(len(generation["outputs"]), 5)
                self.assertEqual(generation["source_asset"]["asset_type"], "product_original")

    def test_phase_one_user_can_generate_and_download_five_images(self):
        with TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir)
            with TestClient(app) as client:

                token = verified_token(client, "alice@example.com")
                headers = {"Authorization": f"Bearer {token}"}

                product_response = client.post(
                    "/api/v1/products",
                    headers=headers,
                    json={
                        "name": "智枫测试水杯",
                        "brand": "智枫",
                        "model": "ZF-CUP-800",
                        "category": "日用品",
                        "material": "不锈钢",
                        "color": "银色",
                        "description": "用于验证一期五图生成流程的测试商品。",
                        "specs": [{"key": "容量", "value": "800", "unit": "ml"}],
                    },
                )
                self.assertEqual(product_response.status_code, 201)
                product_id = product_response.json()["id"]
                upload_product_original(client, headers, product_id)

                barcode_response = client.post(
                    "/api/v1/barcodes/validate",
                    headers=headers,
                    json={"barcode_type": "EAN_13", "raw_value": "4006381333931"},
                )
                self.assertEqual(barcode_response.status_code, 200)
                self.assertIs(barcode_response.json()["can_confirm"], True)

                project_response = client.post(
                    "/api/v1/projects",
                    headers=headers,
                    json={
                        "product_id": product_id,
                        "name": "默认五图项目",
                        "style_config": {"tone": "clean"},
                        "certificate_config": {"standard": "GB/T 29606", "inspector": "QC-01"},
                        "package_config": {"box_material": "kraft"},
                        "detail_config": {"selling_points": ["保温", "易清洁", "耐用"]},
                        "barcode": {"barcode_type": "EAN_13", "raw_value": "4006381333931", "confirmed": True},
                    },
                )
                self.assertEqual(project_response.status_code, 201)
                project = project_response.json()

                grant_test_points(app, product_id=product_id)
                generation_response = client.post(f"/api/v1/projects/{project['id']}/generate", headers=headers)
                self.assertEqual(generation_response.status_code, 202)
                generation = wait_for_generation_status(client, headers, generation_response.json()["id"], {"completed"})
                self.assertEqual(generation["status"], "completed")
                self.assertEqual(len(generation["outputs"]), 5)

                expected_sizes = {
                    "main": (800, 800),
                    "certificate": (800, 800),
                    "package": (800, 800),
                    "detail": (800, 2400),
                    "scene": (800, 800),
                }
                output_types = {output["output_type"] for output in generation["outputs"]}
                self.assertEqual(output_types, set(expected_sizes))

                for output in generation["outputs"]:
                    self.assertEqual(output["width"], expected_sizes[output["output_type"]][0])
                    self.assertEqual(output["height"], expected_sizes[output["output_type"]][1])
                    self.assertEqual(output["quality_status"], "passed")

                first_output_id = generation["outputs"][0]["id"]
                image_response = client.get(f"/api/v1/outputs/{first_output_id}/download", headers=headers)
                self.assertEqual(image_response.status_code, 200)
                self.assertEqual(image_response.headers["content-type"], "image/png")

                with Image.open(BytesIO(image_response.content)) as generated:
                    self.assertEqual(generated.size, (800, 800))
                    self.assertEqual(generated.format, "PNG")

    def test_generation_request_returns_before_slow_provider_finishes(self):
        class SlowProvider:
            name = "slow-provider"

            def generate_five_images(self, **kwargs):
                time.sleep(0.35)
                job_dir = kwargs["output_dir"] / kwargs["job_id"]
                job_dir.mkdir(parents=True, exist_ok=True)
                generated = []
                for output_type, width, height in phase_one.OUTPUT_SPECS:
                    path = job_dir / f"{output_type}.png"
                    Image.new("RGB", (width, height), "white").save(path)
                    generated.append(GeneratedImage(output_type=output_type, width=width, height=height, path=path))
                return generated

        original_provider_factory = phase_one.build_image_generation_provider
        phase_one.build_image_generation_provider = lambda: SlowProvider()
        try:
            with TemporaryDirectory() as data_dir:
                app = create_app(data_dir=data_dir)
                with TestClient(app) as client:
                    token = verified_token(client, "async-generate@example.com")
                    headers = {"Authorization": f"Bearer {token}"}
                    product = client.post(
                        "/api/v1/products",
                        headers=headers,
                        json={"name": "Async Cup", "brand": "Zhifeng", "model": "Q1"},
                    ).json()
                    upload_product_original(client, headers, product["id"])
                    project = client.post(
                        "/api/v1/projects",
                        headers=headers,
                        json={
                            "product_id": product["id"],
                            "name": "Async Project",
                            "barcode": {"barcode_type": "EAN_13", "raw_value": "4006381333931", "confirmed": True},
                        },
                    ).json()
                    grant_test_points(app, product["user_id"])

                    started_at = time.monotonic()
                    response = client.post(f"/api/v1/projects/{project['id']}/generate", headers=headers)
                    elapsed = time.monotonic() - started_at

                    self.assertEqual(response.status_code, 202)
                    self.assertLess(elapsed, 0.2)
                    payload = response.json()
                    self.assertIn(payload["status"], {"queued", "running"})
                    self.assertEqual(payload["outputs"], [])
        finally:
            phase_one.build_image_generation_provider = original_provider_factory

    def test_cross_user_cannot_generate_another_users_project(self):
        with TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir)
            with TestClient(app) as client:

                alice = verified_token(client, "alice@example.com")
                bob = verified_token(client, "bob@example.com")

                product = client.post(
                    "/api/v1/products",
                    headers={"Authorization": f"Bearer {alice}"},
                    json={"name": "隔离测试商品", "brand": "智枫", "model": "A1", "category": "测试"},
                ).json()
                project = client.post(
                    "/api/v1/projects",
                    headers={"Authorization": f"Bearer {alice}"},
                    json={
                        "product_id": product["id"],
                        "name": "隔离测试项目",
                        "barcode": {"barcode_type": "EAN_13", "raw_value": "4006381333931", "confirmed": True},
                    },
                ).json()

                response = client.post(
                    f"/api/v1/projects/{project['id']}/generate",
                    headers={"Authorization": f"Bearer {bob}"},
                )

                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json()["detail"]["code"], "RESOURCE_ACCESS_DENIED")

    def test_failed_provider_generation_is_recorded_for_diagnostics(self):
        class FailingProvider:
            name = "failing-provider"

            def generate_five_images(self, **_kwargs):
                raise RuntimeError("KELE_HTTP_429: upstream busy")

        original_provider_factory = phase_one.build_image_generation_provider
        phase_one.build_image_generation_provider = lambda: FailingProvider()
        try:
            with TemporaryDirectory() as data_dir:
                app = create_app(data_dir=data_dir)
                with TestClient(app) as client:
                    token = verified_token(client, "failed-provider@example.com")
                    headers = {"Authorization": f"Bearer {token}"}
                    product = client.post(
                        "/api/v1/products",
                        headers=headers,
                        json={"name": "Provider Failure Cup", "brand": "Zhifeng", "model": "F1"},
                    ).json()
                    upload_product_original(client, headers, product["id"])
                    project = client.post(
                        "/api/v1/projects",
                        headers=headers,
                        json={
                            "product_id": product["id"],
                            "name": "Provider Failure Project",
                            "barcode": {"barcode_type": "EAN_13", "raw_value": "4006381333931", "confirmed": True},
                        },
                    ).json()

                    grant_test_points(app, product["user_id"])
                    with self.assertLogs(phase_one.logger, level="ERROR") as captured_logs:
                        response = client.post(f"/api/v1/projects/{project['id']}/generate", headers=headers)
                        failed_job = wait_for_generation_status(client, headers, response.json()["id"], {"failed"})

                    self.assertEqual(response.status_code, 202)
                    self.assertEqual(failed_job["status"], "failed")
                    self.assertIn("Image provider failed", "\n".join(captured_logs.output))
                    with app.state.storage.connect() as connection:
                        columns = {row["name"] for row in connection.execute("PRAGMA table_info(generation_jobs)")}
                        self.assertIn("error_code", columns)
                        self.assertIn("error_message", columns)
                        rows = connection.execute(
                            "SELECT status, provider_name, error_code, error_message FROM generation_jobs WHERE project_id = ?",
                            (project["id"],),
                        ).fetchall()
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(rows[0]["status"], "failed")
                    self.assertEqual(rows[0]["provider_name"], "failing-provider")
                    self.assertEqual(rows[0]["error_code"], "IMAGE_PROVIDER_FAILED")
                    self.assertIn("KELE_HTTP_429", rows[0]["error_message"])
        finally:
            phase_one.build_image_generation_provider = original_provider_factory

    def test_unexpected_provider_exception_marks_generation_failed(self):
        class TimeoutProvider:
            name = "timeout-provider"

            def generate_five_images(self, **_kwargs):
                raise TimeoutError("The read operation timed out")

        original_provider_factory = phase_one.build_image_generation_provider
        phase_one.build_image_generation_provider = lambda: TimeoutProvider()
        try:
            with TemporaryDirectory() as data_dir:
                app = create_app(data_dir=data_dir)
                with TestClient(app) as client:
                    token = verified_token(client, "timeout-provider@example.com")
                    headers = {"Authorization": f"Bearer {token}"}
                    product = client.post(
                        "/api/v1/products",
                        headers=headers,
                        json={"name": "Timeout Cup", "brand": "Zhifeng", "model": "T1"},
                    ).json()
                    upload_product_original(client, headers, product["id"])
                    project = client.post(
                        "/api/v1/projects",
                        headers=headers,
                        json={
                            "product_id": product["id"],
                            "name": "Timeout Project",
                            "barcode": {"barcode_type": "EAN_13", "raw_value": "4006381333931", "confirmed": True},
                        },
                    ).json()

                    grant_test_points(app, product["user_id"])
                    response = client.post(f"/api/v1/projects/{project['id']}/generate", headers=headers)
                    failed_job = wait_for_generation_status(client, headers, response.json()["id"], {"failed"})

                    self.assertEqual(response.status_code, 202)
                    self.assertEqual(failed_job["status"], "failed")
                    with app.state.storage.connect() as connection:
                        job = connection.execute(
                            "SELECT status, error_code, error_message FROM generation_jobs WHERE project_id = ?",
                            (project["id"],),
                        ).fetchone()
                        project_row = connection.execute(
                            "SELECT status FROM projects WHERE id = ?",
                            (project["id"],),
                        ).fetchone()
                    self.assertEqual(job["status"], "failed")
                    self.assertEqual(job["error_code"], "IMAGE_PROVIDER_FAILED")
                    self.assertIn("The read operation timed out", job["error_message"])
                    self.assertEqual(project_row["status"], "failed")
        finally:
            phase_one.build_image_generation_provider = original_provider_factory

    def test_failed_generation_records_partial_files_for_preview(self):
        class PartialFileProvider:
            name = "partial-file-provider"

            def generate_five_images(self, **kwargs):
                output_dir = kwargs["output_dir"]
                job_id = kwargs["job_id"]
                job_dir = output_dir / job_id
                job_dir.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (800, 800), "white").save(job_dir / "main.png")
                Image.new("RGB", (800, 800), "white").save(job_dir / "certificate.png")
                Image.new("RGB", (800, 800), "white").save(job_dir / "package.png")
                raise RuntimeError("KELE_HTTP_403: user quota is not enough")

        original_provider_factory = phase_one.build_image_generation_provider
        phase_one.build_image_generation_provider = lambda: PartialFileProvider()
        try:
            with TemporaryDirectory() as data_dir:
                app = create_app(data_dir=data_dir)
                with TestClient(app) as client:
                    token = verified_token(client, "partial-output@example.com")
                    headers = {"Authorization": f"Bearer {token}"}
                    product = client.post(
                        "/api/v1/products",
                        headers=headers,
                        json={"name": "Partial Cup", "brand": "Zhifeng", "model": "P1"},
                    ).json()
                    upload_product_original(client, headers, product["id"])
                    project = client.post(
                        "/api/v1/projects",
                        headers=headers,
                        json={
                            "product_id": product["id"],
                            "name": "Partial Project",
                            "barcode": {"barcode_type": "EAN_13", "raw_value": "4006381333931", "confirmed": True},
                        },
                    ).json()

                    grant_test_points(app, product["user_id"])
                    response = client.post(f"/api/v1/projects/{project['id']}/generate", headers=headers)
                    failed_job = wait_for_generation_status(client, headers, response.json()["id"], {"failed"})
                    outputs = client.get(f"/api/v1/projects/{project['id']}/outputs", headers=headers).json()["items"]

                    self.assertEqual(response.status_code, 202)
                    self.assertEqual(failed_job["status"], "failed")
                    self.assertEqual([output["output_type"] for output in outputs], ["main", "certificate", "package"])
                    self.assertEqual({output["quality_status"] for output in outputs}, {"passed"})
                    self.assertEqual(outputs[0]["width"], 800)
                    self.assertEqual(outputs[0]["height"], 800)
        finally:
            phase_one.build_image_generation_provider = original_provider_factory

    def test_listing_outputs_recovers_orphaned_partial_files(self):
        with TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir)
            with TestClient(app) as client:
                token = verified_token(client, "orphaned-output@example.com")
                headers = {"Authorization": f"Bearer {token}"}
                product = client.post(
                    "/api/v1/products",
                    headers=headers,
                    json={"name": "Orphan Cup", "brand": "Zhifeng", "model": "O1"},
                ).json()
                asset = upload_product_original(client, headers, product["id"])
                project = client.post(
                    "/api/v1/projects",
                    headers=headers,
                    json={
                        "product_id": product["id"],
                        "name": "Orphan Project",
                        "barcode": {"barcode_type": "EAN_13", "raw_value": "4006381333931", "confirmed": True},
                    },
                ).json()

                job_id = "orphaned-job"
                job_dir = app.state.storage.output_dir / job_id
                job_dir.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (800, 800), "white").save(job_dir / "main.png")
                with app.state.storage.connect() as connection:
                    connection.execute(
                        """
                        INSERT INTO generation_jobs
                            (id, user_id, project_id, status, provider_name, source_asset_version_id, error_code, error_message)
                        VALUES (?, ?, ?, 'failed', 'kele-gpt-image-2', ?, 'IMAGE_PROVIDER_FAILED', 'quota')
                        """,
                        (job_id, product["user_id"], project["id"], asset["version_id"]),
                    )

                outputs = client.get(f"/api/v1/projects/{project['id']}/outputs", headers=headers).json()["items"]

                self.assertEqual([output["output_type"] for output in outputs], ["main"])
                self.assertEqual(outputs[0]["width"], 800)
                self.assertEqual(outputs[0]["height"], 800)

    def test_gallery_outputs_are_limited_to_current_user_history(self):
        with TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir)
            with TestClient(app) as client:
                alice_token = verified_token(client, "gallery-alice@example.com")
                bob_token = verified_token(client, "gallery-bob@example.com")
                alice_headers = {"Authorization": f"Bearer {alice_token}"}
                bob_headers = {"Authorization": f"Bearer {bob_token}"}

                alice_generation = generate_mock_project(client, alice_headers, "Alice Gallery Cup")
                bob_generation = generate_mock_project(client, bob_headers, "Bob Gallery Cup")

                alice_gallery = client.get("/api/v1/gallery/outputs", headers=alice_headers)
                bob_gallery = client.get("/api/v1/gallery/outputs", headers=bob_headers)

                self.assertEqual(alice_gallery.status_code, 200)
                self.assertEqual(bob_gallery.status_code, 200)
                alice_output_ids = {output["id"] for output in alice_generation["outputs"]}
                bob_output_ids = {output["id"] for output in bob_generation["outputs"]}
                alice_gallery_ids = {output["id"] for output in alice_gallery.json()["items"]}
                bob_gallery_ids = {output["id"] for output in bob_gallery.json()["items"]}
                self.assertEqual(alice_gallery_ids, alice_output_ids)
                self.assertEqual(bob_gallery_ids, bob_output_ids)
                self.assertTrue(alice_gallery_ids.isdisjoint(bob_output_ids))

    def test_generation_rejects_when_user_active_job_limit_is_reached(self):
        original_env = {
            "APP_ENV": os.environ.get("APP_ENV"),
            "MAX_ACTIVE_JOBS_PER_USER": os.environ.get("MAX_ACTIVE_JOBS_PER_USER"),
            "SMTP_HOST": os.environ.get("SMTP_HOST"),
            "SMTP_USERNAME": os.environ.get("SMTP_USERNAME"),
            "SMTP_PASSWORD": os.environ.get("SMTP_PASSWORD"),
            "SMTP_FROM": os.environ.get("SMTP_FROM"),
        }
        os.environ["APP_ENV"] = "test"
        os.environ["MAX_ACTIVE_JOBS_PER_USER"] = "1"
        for smtp_key in ["SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM"]:
            os.environ[smtp_key] = ""
        try:
            with TemporaryDirectory() as data_dir:
                app = create_app(data_dir=data_dir)
                with TestClient(app) as client:
                    token = verified_token(client, "active-limit@example.com")
                    headers = {"Authorization": f"Bearer {token}"}
                    product = client.post(
                        "/api/v1/products",
                        headers=headers,
                        json={"name": "Active Limit Cup", "brand": "Zhifeng", "model": "AL1"},
                    ).json()
                    asset = upload_product_original(client, headers, product["id"])
                    project = client.post(
                        "/api/v1/projects",
                        headers=headers,
                        json={
                            "product_id": product["id"],
                            "name": "Active Limit Project",
                            "barcode": {"barcode_type": "EAN_13", "raw_value": "4006381333931", "confirmed": True},
                        },
                    ).json()
                    with app.state.storage.connect() as connection:
                        connection.execute(
                            """
                            INSERT INTO generation_jobs
                                (id, user_id, project_id, status, provider_name, source_asset_version_id)
                            VALUES (?, ?, ?, 'running', 'mock-image', ?)
                            """,
                            ("busy-job", product["user_id"], project["id"], asset["version_id"]),
                        )

                    second_project = client.post(
                        "/api/v1/projects",
                        headers=headers,
                        json={
                            "product_id": product["id"],
                            "name": "Active Limit Project 2",
                            "barcode": {"barcode_type": "EAN_13", "raw_value": "4006381333931", "confirmed": True},
                        },
                    ).json()
                    response = client.post(f"/api/v1/projects/{second_project['id']}/generate", headers=headers)

                    self.assertEqual(response.status_code, 429)
                    self.assertEqual(response.json()["detail"]["code"], "ACTIVE_JOB_LIMIT_REACHED")
        finally:
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_generation_rejects_when_provider_slot_is_full(self):
        original_env = {
            "APP_ENV": os.environ.get("APP_ENV"),
            "PROVIDER_MAX_CONCURRENCY": os.environ.get("PROVIDER_MAX_CONCURRENCY"),
            "SMTP_HOST": os.environ.get("SMTP_HOST"),
            "SMTP_USERNAME": os.environ.get("SMTP_USERNAME"),
            "SMTP_PASSWORD": os.environ.get("SMTP_PASSWORD"),
            "SMTP_FROM": os.environ.get("SMTP_FROM"),
        }
        os.environ["APP_ENV"] = "test"
        os.environ["PROVIDER_MAX_CONCURRENCY"] = "1"
        for smtp_key in ["SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM"]:
            os.environ[smtp_key] = ""
        try:
            with TemporaryDirectory() as data_dir:
                app = create_app(data_dir=data_dir)
                with TestClient(app) as client:
                    token = verified_token(client, "provider-slot@example.com")
                    headers = {"Authorization": f"Bearer {token}"}
                    product = client.post(
                        "/api/v1/products",
                        headers=headers,
                        json={"name": "Provider Slot Cup", "brand": "Zhifeng", "model": "PS1"},
                    ).json()
                    upload_product_original(client, headers, product["id"])
                    project = client.post(
                        "/api/v1/projects",
                        headers=headers,
                        json={
                            "product_id": product["id"],
                            "name": "Provider Slot Project",
                            "barcode": {"barcode_type": "EAN_13", "raw_value": "4006381333931", "confirmed": True},
                        },
                    ).json()

                    grant_test_points(app, product["user_id"])
                    with app.state.runtime_services.slot("slot:provider:generation", limit=1, ttl_seconds=600):
                        response = client.post(f"/api/v1/projects/{project['id']}/generate", headers=headers)
                        payload = response.json()
                        self.assertEqual(response.status_code, 202)
                        self.assertIn(payload["status"], {"queued", "running"})

                    completed = wait_for_generation_status(client, headers, payload["id"], {"completed"})
                    self.assertEqual(completed["status"], "completed")
        finally:
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_kele_provider_uses_code28_base_url_and_configured_image_size(self):
        env_keys = ["IMAGE_PROVIDER", "KELE_API_KEY", "KELE_API_BASE_URL", "KELE_IMAGE_SIZE"]
        original_env = {key: os.environ.get(key) for key in env_keys}
        try:
            os.environ["IMAGE_PROVIDER"] = "kele"
            os.environ["KELE_API_KEY"] = "test-key"
            os.environ.pop("KELE_API_BASE_URL", None)
            os.environ["KELE_IMAGE_SIZE"] = "1024x1024"

            provider = phase_one.build_image_generation_provider()

            self.assertEqual(provider.name, "kele-gpt-image-2")
            self.assertEqual(provider.edit_size, "1024x1024")
            self.assertEqual(provider.provider.config.base_url, "https://code28.ccwu.cc/v1")
            self.assertEqual(provider.provider.config.model, "gpt-image-2")
        finally:
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()


def make_png_bytes() -> bytes:
    image = Image.new("RGB", (512, 512), "#f8fafc")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def parse_dt(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def verified_token(client: TestClient, email: str, password: str = "StrongPass123") -> str:
    if email.endswith("@example.com"):
        email = email.replace("@example.com", "@qq.com")
    send_code = client.post("/api/v1/auth/registration-code", json={"email": email})
    assert send_code.status_code == 202, send_code.text
    register = client.post(
        "/api/v1/auth/register",
        json={
            "username": email.split("@", 1)[0],
            "email": email,
            "verification_code": send_code.json()["debug_code"],
            "password": password,
        },
    )
    assert register.status_code == 201, register.text
    login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


def upload_product_original(client: TestClient, headers: dict[str, str], product_id: str) -> dict[str, object]:
    png = make_png_bytes()
    presign = client.post(
        "/api/v1/uploads/presign",
        headers=headers,
        json={
            "asset_type": "product_original",
            "filename": "product.png",
            "content_type": "image/png",
            "size_bytes": len(png),
        },
    )
    assert presign.status_code == 201, presign.text
    payload = presign.json()
    upload = client.put(payload["upload_url"], content=png, headers={"content-type": "image/png"})
    assert upload.status_code == 204, upload.text
    complete = client.post(
        "/api/v1/uploads/complete",
        headers=headers,
        json={"upload_token": payload["upload_token"], "product_id": product_id},
    )
    assert complete.status_code == 201, complete.text
    return complete.json()


def generate_mock_project(client: TestClient, headers: dict[str, str], product_name: str) -> dict[str, object]:
    product = client.post(
        "/api/v1/products",
        headers=headers,
        json={"name": product_name, "brand": "Zhifeng", "model": "G1"},
    ).json()
    upload_product_original(client, headers, product["id"])
    project = client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "product_id": product["id"],
            "name": f"{product_name} Project",
            "barcode": {"barcode_type": "EAN_13", "raw_value": "4006381333931", "confirmed": True},
        },
    ).json()
    grant_test_points_from_client(client, headers)
    response = client.post(f"/api/v1/projects/{project['id']}/generate", headers=headers)
    assert response.status_code == 202, response.text
    return wait_for_generation_status(client, headers, response.json()["id"], {"completed"})


def wait_for_generation_status(
    client: TestClient,
    headers: dict[str, str],
    job_id: str,
    statuses: set[str],
    *,
    timeout_seconds: float = 5,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    last_payload: dict[str, object] | None = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/generation-jobs/{job_id}", headers=headers)
        assert response.status_code == 200, response.text
        last_payload = response.json()
        if last_payload["status"] in statuses:
            return last_payload
        time.sleep(0.05)
    raise AssertionError(f"generation job {job_id} did not reach {statuses}; last payload: {last_payload}")


def grant_test_points(app, user_id: str | None = None, product_id: str | None = None) -> None:
    with app.state.storage.connect() as connection:
        if user_id is None and product_id is not None:
            row = connection.execute("SELECT user_id FROM products WHERE id = ?", (product_id,)).fetchone()
            user_id = row["user_id"]
        user = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        connection.execute(
            """
            INSERT OR IGNORE INTO user_accounts (user_id, username_snapshot, balance_points, reserved_points)
            VALUES (?, ?, 0, 0)
            """,
            (user["id"], user["username"]),
        )
        connection.execute(
            "UPDATE user_accounts SET balance_points = 10000, reserved_points = 0 WHERE user_id = ?",
            (user["id"],),
        )
        connection.execute(
            """
            INSERT INTO account_point_lots (id, user_id, source_type, total_points, remaining_points, expires_at)
            VALUES (?, ?, 'test_recharge', 10000, 10000, '2999-01-01T00:00:00+00:00')
            """,
            (phase_one.new_id(), user["id"]),
        )


def grant_test_points_from_client(client: TestClient, headers: dict[str, str]) -> None:
    user = client.get("/api/v1/users/me", headers=headers).json()
    storage = client.app.state.storage
    with storage.connect() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO user_accounts (user_id, username_snapshot, balance_points, reserved_points)
            VALUES (?, ?, 0, 0)
            """,
            (user["id"], user["username"]),
        )
        connection.execute(
            "UPDATE user_accounts SET balance_points = 10000, reserved_points = 0 WHERE user_id = ?",
            (user["id"],),
        )
        connection.execute(
            """
            INSERT INTO account_point_lots (id, user_id, source_type, total_points, remaining_points, expires_at)
            VALUES (?, ?, 'test_recharge', 10000, 10000, '2999-01-01T00:00:00+00:00')
            """,
            (phase_one.new_id(), user["id"]),
        )
