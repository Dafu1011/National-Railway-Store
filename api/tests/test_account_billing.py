from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient
from PIL import Image

from app.api import phase_one
from app.core.billing import InsufficientBalance, reserve_generation_charge
from app.main import create_app
from app.providers.real_image import GeneratedImage
from tests.test_phase_one_flow import upload_product_original, verified_token, wait_for_generation_status


class AccountBillingTests(unittest.TestCase):
    def test_registered_user_starts_with_zero_balance(self):
        with TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir)
            with TestClient(app) as client:
                token = verified_token(client, "zero-balance@qq.com")

                response = client.get("/api/v1/account/me", headers=auth_header(token))

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["balance_points"], 0)
                self.assertEqual(payload["reserved_points"], 0)
                self.assertEqual(payload["available_points"], 0)
                self.assertEqual(payload["user"]["email"], "zero-balance@qq.com")

    def test_admin_recharge_adds_approved_3699_package_points(self):
        with TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir)
            with TestClient(app) as client:
                admin_token = verified_token(client, "admin@qq.com")
                user_token = verified_token(client, "recharge-target@qq.com")
                user = client.get("/api/v1/users/me", headers=auth_header(user_token)).json()
                make_admin(app, "admin@qq.com")

                response = client.post(
                    f"/api/v1/admin/accounts/{user['id']}/recharge",
                    headers=auth_header(admin_token),
                    json={"points": 10000, "remark": "3699元套餐"},
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["balance_points"], 10000)
                account = client.get("/api/v1/account/me", headers=auth_header(user_token)).json()
                self.assertEqual(account["available_points"], 10000)
                self.assertEqual(account["next_expiring_lot"]["remaining_points"], 10000)
                transactions = client.get("/api/v1/account/transactions", headers=auth_header(user_token)).json()["items"]
                self.assertEqual(transactions[0]["type"], "recharge")
                self.assertEqual(transactions[0]["points"], 10000)
                self.assertEqual(transactions[0]["remark"], "3699元套餐")

    def test_generation_requires_balance_before_provider_runs(self):
        with TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir)
            with TestClient(app) as client:
                token = verified_token(client, "needs-balance@qq.com")
                headers = auth_header(token)
                project = create_project_with_upload(client, headers)

                response = client.post(f"/api/v1/projects/{project['id']}/generate", headers=headers)

                self.assertEqual(response.status_code, 402)
                self.assertEqual(response.json()["detail"]["code"], "INSUFFICIENT_BALANCE")
                with app.state.storage.connect() as connection:
                    jobs = connection.execute("SELECT COUNT(*) AS count FROM generation_jobs").fetchone()
                self.assertEqual(jobs["count"], 0)

    def test_reserving_points_is_atomic_for_available_balance(self):
        with TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir)
            with TestClient(app) as client:
                admin_token = verified_token(client, "atomic-admin@qq.com")
                user_token = verified_token(client, "atomic-user@qq.com")
                make_admin(app, "atomic-admin@qq.com")
                user = client.get("/api/v1/users/me", headers=auth_header(user_token)).json()
                response = client.post(
                    f"/api/v1/admin/accounts/{user['id']}/recharge",
                    headers=auth_header(admin_token),
                    json={"points": 10, "remark": "atomic reserve test"},
                )
                self.assertEqual(response.status_code, 200)

                reserve_generation_charge(app.state.storage, user=user, job_id="job-one")

                with self.assertRaises(InsufficientBalance):
                    reserve_generation_charge(app.state.storage, user=user, job_id="job-two")
                account = client.get("/api/v1/account/me", headers=auth_header(user_token)).json()
                self.assertEqual(account["balance_points"], 10)
                self.assertEqual(account["reserved_points"], 10)

    def test_successful_five_image_generation_charges_ten_points(self):
        with TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir)
            with TestClient(app) as client:
                admin_token = verified_token(client, "charge-admin@qq.com")
                user_token = verified_token(client, "charge-user@qq.com")
                make_admin(app, "charge-admin@qq.com")
                user = client.get("/api/v1/users/me", headers=auth_header(user_token)).json()
                recharge(client, admin_token, user["id"])
                project = create_project_with_upload(client, auth_header(user_token))

                response = client.post(f"/api/v1/projects/{project['id']}/generate", headers=auth_header(user_token))
                generation = wait_for_generation_status(client, auth_header(user_token), response.json()["id"], {"completed"})

                self.assertEqual(response.status_code, 202)
                self.assertEqual(len(generation["outputs"]), 5)
                account = client.get("/api/v1/account/me", headers=auth_header(user_token)).json()
                self.assertEqual(account["balance_points"], 9990)
                self.assertEqual(account["reserved_points"], 0)
                transactions = client.get("/api/v1/account/transactions", headers=auth_header(user_token)).json()["items"]
                self.assertEqual(transactions[0]["type"], "generation_charge")
                self.assertEqual(transactions[0]["points"], -10)

    def test_failed_generation_releases_hold_without_charge(self):
        class FailingProvider:
            name = "failing-provider"

            def generate_five_images(self, **_kwargs):
                raise RuntimeError("provider exploded")

        original_provider_factory = phase_one.build_image_generation_provider
        phase_one.build_image_generation_provider = lambda: FailingProvider()
        try:
            with TemporaryDirectory() as data_dir:
                app = create_app(data_dir=data_dir)
                with TestClient(app) as client:
                    admin_token = verified_token(client, "failure-admin@qq.com")
                    user_token = verified_token(client, "failure-user@qq.com")
                    make_admin(app, "failure-admin@qq.com")
                    user = client.get("/api/v1/users/me", headers=auth_header(user_token)).json()
                    recharge(client, admin_token, user["id"])
                    project = create_project_with_upload(client, auth_header(user_token))

                    response = client.post(f"/api/v1/projects/{project['id']}/generate", headers=auth_header(user_token))
                    generation = wait_for_generation_status(client, auth_header(user_token), response.json()["id"], {"failed"})

                    self.assertEqual(response.status_code, 202)
                    self.assertEqual(generation["status"], "failed")
                    account = client.get("/api/v1/account/me", headers=auth_header(user_token)).json()
                    self.assertEqual(account["balance_points"], 10000)
                    self.assertEqual(account["reserved_points"], 0)
                    transactions = client.get("/api/v1/account/transactions", headers=auth_header(user_token)).json()["items"]
                    self.assertNotIn("generation_charge", {item["type"] for item in transactions})
        finally:
            phase_one.build_image_generation_provider = original_provider_factory

    def test_less_than_five_outputs_does_not_charge(self):
        class PartialSuccessProvider:
            name = "partial-success-provider"

            def generate_five_images(self, **kwargs):
                job_dir = Path(kwargs["output_dir"]) / kwargs["job_id"]
                job_dir.mkdir(parents=True, exist_ok=True)
                outputs = []
                for output_type in ["main", "certificate", "package", "scene"]:
                    path = job_dir / f"{output_type}.png"
                    Image.new("RGB", (800, 800), "white").save(path)
                    outputs.append(GeneratedImage(output_type=output_type, width=800, height=800, path=path))
                return outputs

        original_provider_factory = phase_one.build_image_generation_provider
        phase_one.build_image_generation_provider = lambda: PartialSuccessProvider()
        try:
            with TemporaryDirectory() as data_dir:
                app = create_app(data_dir=data_dir)
                with TestClient(app) as client:
                    admin_token = verified_token(client, "partial-admin@qq.com")
                    user_token = verified_token(client, "partial-user@qq.com")
                    make_admin(app, "partial-admin@qq.com")
                    user = client.get("/api/v1/users/me", headers=auth_header(user_token)).json()
                    recharge(client, admin_token, user["id"])
                    project = create_project_with_upload(client, auth_header(user_token))

                    response = client.post(f"/api/v1/projects/{project['id']}/generate", headers=auth_header(user_token))
                    generation = wait_for_generation_status(client, auth_header(user_token), response.json()["id"], {"completed"})

                    self.assertEqual(response.status_code, 202)
                    self.assertEqual(len(generation["outputs"]), 4)
                    account = client.get("/api/v1/account/me", headers=auth_header(user_token)).json()
                    self.assertEqual(account["balance_points"], 10000)
                    self.assertEqual(account["reserved_points"], 0)
        finally:
            phase_one.build_image_generation_provider = original_provider_factory


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def make_admin(app, email: str) -> None:
    with app.state.storage.connect() as connection:
        connection.execute("UPDATE users SET role = 'admin' WHERE email_normalized = ?", (email,))


def recharge(client: TestClient, admin_token: str, user_id: str) -> None:
    response = client.post(
        f"/api/v1/admin/accounts/{user_id}/recharge",
        headers=auth_header(admin_token),
        json={"points": 10000, "remark": "3699元套餐"},
    )
    assert response.status_code == 200, response.text


def create_project_with_upload(client: TestClient, headers: dict[str, str]) -> dict[str, object]:
    product = client.post(
        "/api/v1/products",
        headers=headers,
        json={"name": "Billing Cup", "brand": "Zhifeng", "model": "B1"},
    ).json()
    upload_product_original(client, headers, product["id"])
    return client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "product_id": product["id"],
            "name": "Billing Project",
            "barcode": {"barcode_type": "EAN_13", "raw_value": "4006381333931", "confirmed": True},
        },
    ).json()


if __name__ == "__main__":
    unittest.main()
