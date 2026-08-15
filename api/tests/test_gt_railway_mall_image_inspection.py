from io import BytesIO
import unittest

from PIL import Image, ImageDraw

from app.standards.gt_railway_mall import (
    ImageRole,
    inspect_gt_railway_image_file,
    validate_gt_railway_upload_package,
)


def png_bytes(width: int, height: int, *, background: str = "white", product_box: tuple[int, int, int, int] | None = None) -> bytes:
    image = Image.new("RGB", (width, height), background)
    if product_box:
        ImageDraw.Draw(image).rectangle(product_box, fill="black")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class GtRailwayMallImageInspectionTests(unittest.TestCase):
    def test_inspects_real_main_image_bytes_for_dimensions_white_background_and_fill_ratio(self):
        content = png_bytes(800, 800, product_box=(40, 40, 760, 760))

        candidate = inspect_gt_railway_image_file(
            name="main-front.png",
            role=ImageRole.MAIN,
            content=content,
            view="front",
        )

        self.assertEqual(candidate.width, 800)
        self.assertEqual(candidate.height, 800)
        self.assertEqual(candidate.format, "png")
        self.assertTrue(candidate.signals.is_white_background)
        self.assertGreater(candidate.signals.fill_ratio, 0.8)
        self.assertTrue(validate_gt_railway_upload_package([candidate, candidate, candidate]).issues)

    def test_inspected_bad_image_fails_without_trusting_client_signals(self):
        content = png_bytes(801, 800, background="gray", product_box=(350, 350, 450, 450))

        candidate = inspect_gt_railway_image_file(
            name="main-bad.png",
            role=ImageRole.MAIN,
            content=content,
            view="front",
        )
        result = validate_gt_railway_upload_package([candidate])
        codes = [issue.code for issue in result.issues]

        self.assertIn("GT_MAIN_SIZE_INVALID", codes)
        self.assertIn("GT_FIRST_MAIN_BACKGROUND_NOT_WHITE", codes)
        self.assertIn("GT_IMAGE_FILL_RATIO_LOW", codes)

    def test_inspected_oversized_main_image_fails_file_size_gate(self):
        candidate = inspect_gt_railway_image_file(
            name="main-large.png",
            role=ImageRole.MAIN,
            content=png_bytes(800, 800, product_box=(40, 40, 760, 760)),
            view="front",
            file_size_override=1_048_577,
        )

        result = validate_gt_railway_upload_package([candidate, candidate, candidate])

        self.assertIn("GT_MAIN_FILE_TOO_LARGE", [issue.code for issue in result.issues])


if __name__ == "__main__":
    unittest.main()
