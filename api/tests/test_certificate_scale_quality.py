import unittest

from PIL import Image, ImageDraw

from app.quality.certificate_scale import inspect_certificate_scale, is_large_or_bulky_product


def certificate_scene(card_box: tuple[int, int, int, int]) -> Image.Image:
    image = Image.new("RGB", (800, 800), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 120, 760, 620), fill=(30, 30, 30))
    draw.rectangle(card_box, fill=(248, 248, 246), outline=(0, 87, 165), width=3)
    return image


class CertificateScaleQualityTests(unittest.TestCase):
    def test_large_equipment_allows_readable_certificate_wider_than_old_small_card_limit(self):
        result = inspect_certificate_scale(
            certificate_scene((300, 620, 560, 775)),
            {"name": "手推式扫雪机", "category": "大型清洁机械", "model": "6.5马力"},
        )

        self.assertTrue(result.passed)
        self.assertIsNone(result.code)
        self.assertGreater(result.card_width_ratio, 0.28)

    def test_large_equipment_accepts_readable_certificate_with_flexible_position(self):
        result = inspect_certificate_scale(
            certificate_scene((230, 600, 610, 775)),
            {"name": "手推式扫雪机", "category": "大型清洁机械", "model": "6.5马力"},
        )

        self.assertTrue(result.passed)
        self.assertIsNone(result.code)
        self.assertGreater(result.card_width_ratio, 0.36)

    def test_medium_product_allows_larger_certificate_than_bulky_equipment(self):
        result = inspect_certificate_scale(
            certificate_scene((300, 620, 560, 775)),
            {"name": "保温杯", "category": "日用品", "model": "800ml"},
        )

        self.assertTrue(result.passed)
        self.assertTrue(result.card_width_ratio <= 0.36)

    def test_bulky_classifier_covers_machinery_and_large_cleaning_products(self):
        self.assertTrue(is_large_or_bulky_product({"name": "手推式扫雪机", "category": "清洁设备"}))
        self.assertTrue(is_large_or_bulky_product({"name": "割草机", "category": "园林机械"}))
        self.assertFalse(is_large_or_bulky_product({"name": "保温杯", "category": "日用品"}))


if __name__ == "__main__":
    unittest.main()
