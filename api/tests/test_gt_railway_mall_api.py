import unittest

from fastapi.testclient import TestClient

from app.main import create_app


class GtRailwayMallApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app())

    def test_get_gt_railway_standard_returns_upload_limits(self):
        response = self.client.get("/api/v1/standards/gt-railway-mall")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["main_image"]["count"], {"min": 3, "max": 5})
        self.assertEqual(data["main_image"]["size"], {"width": 800, "height": 800})
        self.assertEqual(data["main_image"]["max_bytes"], 1_048_576)
        self.assertEqual(data["detail_image"]["width"], 800)
        self.assertEqual(data["detail_image"]["max_bytes"], 5_242_880)

    def test_validate_gt_railway_package_returns_issue_codes(self):
        response = self.client.post(
            "/api/v1/standards/gt-railway-mall/validate",
            json={
                "images": [
                    {
                        "name": "main.png",
                        "role": "main",
                        "width": 800,
                        "height": 800,
                        "file_size_bytes": 1_100_000,
                        "format": "png",
                        "view": "front",
                        "signals": {
                            "is_white_background": False,
                            "is_clear": True,
                            "is_centered": True,
                            "fill_ratio": 0.84,
                            "has_watermark": False,
                            "has_promo_text": False,
                            "has_date_or_url": False,
                            "has_other_brand_logo": False,
                            "has_large_dark_shadow": False,
                            "has_large_reflection": False,
                            "is_distorted": False,
                            "shows_brand_or_manufacturer": True,
                        },
                    }
                ]
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["passed"])
        self.assertIn("GT_MAIN_COUNT_INVALID", [issue["code"] for issue in data["issues"]])
        self.assertIn("GT_FIRST_MAIN_BACKGROUND_NOT_WHITE", [issue["code"] for issue in data["issues"]])
        self.assertIn("GT_MAIN_FILE_TOO_LARGE", [issue["code"] for issue in data["issues"]])


if __name__ == "__main__":
    unittest.main()
