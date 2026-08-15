import unittest

from app.standards.gt_railway_mall import (
    GT_RAILWAY_MALL_STANDARD,
    GeneratedImageCandidate,
    ImageRole,
    ImageSignals,
    validate_gt_railway_upload_package,
)


def main_image(name: str, *, first: bool = False, view: str = "front") -> GeneratedImageCandidate:
    return GeneratedImageCandidate(
        name=name,
        role=ImageRole.MAIN,
        width=800,
        height=800,
        file_size_bytes=800_000,
        format="png",
        view=view,
        signals=ImageSignals(
            is_white_background=first,
            is_clear=True,
            is_centered=True,
            fill_ratio=0.84,
            has_watermark=False,
            has_promo_text=False,
            has_date_or_url=False,
            has_other_brand_logo=False,
            has_large_dark_shadow=False,
            has_large_reflection=False,
            is_distorted=False,
            shows_brand_or_manufacturer=True,
        ),
    )


class GtRailwayMallStandardTests(unittest.TestCase):
    def test_accepts_compliant_main_images_and_detail_image(self):
        package = [
            main_image("main-front.png", first=True, view="front"),
            main_image("main-side.png", view="side"),
            main_image("main-back.png", view="back"),
            GeneratedImageCandidate(
                name="detail.png",
                role=ImageRole.DETAIL,
                width=800,
                height=2400,
                file_size_bytes=4_500_000,
                format="png",
                view="detail",
                signals=ImageSignals(
                    is_white_background=False,
                    is_clear=True,
                    is_centered=True,
                    fill_ratio=0.7,
                    has_watermark=False,
                    has_promo_text=False,
                    has_date_or_url=False,
                    has_other_brand_logo=False,
                    has_large_dark_shadow=False,
                    has_large_reflection=False,
                    is_distorted=False,
                    shows_brand_or_manufacturer=True,
                ),
            ),
        ]

        result = validate_gt_railway_upload_package(package)

        self.assertTrue(result.passed)
        self.assertEqual(result.standard.source_url, GT_RAILWAY_MALL_STANDARD.source_url)

    def test_rejects_main_package_with_too_few_main_images(self):
        result = validate_gt_railway_upload_package([main_image("only-one.png", first=True)])

        self.assertFalse(result.passed)
        self.assertIn("GT_MAIN_COUNT_INVALID", [issue.code for issue in result.issues])

    def test_rejects_first_main_image_without_white_background(self):
        package = [
            main_image("main-front.png", first=False, view="front"),
            main_image("main-side.png", view="side"),
            main_image("main-back.png", view="back"),
        ]

        result = validate_gt_railway_upload_package(package)

        self.assertFalse(result.passed)
        self.assertIn("GT_FIRST_MAIN_BACKGROUND_NOT_WHITE", [issue.code for issue in result.issues])

    def test_rejects_main_image_over_one_megabyte_or_wrong_size(self):
        oversized = main_image("main-front.png", first=True)
        oversized.file_size_bytes = GT_RAILWAY_MALL_STANDARD.main_image_max_bytes + 1
        wrong_size = main_image("main-side.png", view="side")
        wrong_size.width = 801
        package = [oversized, wrong_size, main_image("main-back.png", view="back")]

        result = validate_gt_railway_upload_package(package)

        self.assertIn("GT_MAIN_FILE_TOO_LARGE", [issue.code for issue in result.issues])
        self.assertIn("GT_MAIN_SIZE_INVALID", [issue.code for issue in result.issues])

    def test_rejects_duplicate_views_low_fill_ratio_and_forbidden_visual_content(self):
        first = main_image("main-front.png", first=True, view="front")
        duplicate = main_image("main-front-2.png", view="front")
        duplicate.signals.fill_ratio = 0.72
        duplicate.signals.has_watermark = True
        package = [first, duplicate, main_image("main-back.png", view="back")]

        result = validate_gt_railway_upload_package(package)

        codes = [issue.code for issue in result.issues]
        self.assertIn("GT_MAIN_VIEW_DUPLICATED", codes)
        self.assertIn("GT_IMAGE_FILL_RATIO_LOW", codes)
        self.assertIn("GT_IMAGE_HAS_WATERMARK", codes)

    def test_rejects_detail_image_when_width_or_file_size_is_invalid(self):
        result = validate_gt_railway_upload_package(
            [
                main_image("main-front.png", first=True, view="front"),
                main_image("main-side.png", view="side"),
                main_image("main-back.png", view="back"),
                GeneratedImageCandidate(
                    name="detail.png",
                    role=ImageRole.DETAIL,
                    width=799,
                    height=2400,
                    file_size_bytes=GT_RAILWAY_MALL_STANDARD.detail_image_max_bytes + 1,
                    format="png",
                    view="detail",
                    signals=ImageSignals(
                        is_white_background=False,
                        is_clear=True,
                        is_centered=True,
                        fill_ratio=0.7,
                        has_watermark=False,
                        has_promo_text=False,
                        has_date_or_url=False,
                        has_other_brand_logo=False,
                        has_large_dark_shadow=False,
                        has_large_reflection=False,
                        is_distorted=False,
                        shows_brand_or_manufacturer=True,
                    ),
                ),
            ]
        )

        codes = [issue.code for issue in result.issues]
        self.assertIn("GT_DETAIL_WIDTH_INVALID", codes)
        self.assertIn("GT_DETAIL_FILE_TOO_LARGE", codes)

    def test_rejects_unsupported_image_format(self):
        unsupported = main_image("main-front.gif", first=True, view="front")
        unsupported.format = "gif"
        package = [
            unsupported,
            main_image("main-side.png", view="side"),
            main_image("main-back.png", view="back"),
        ]

        result = validate_gt_railway_upload_package(package)

        self.assertFalse(result.passed)
        self.assertIn("GT_IMAGE_FORMAT_UNSUPPORTED", [issue.code for issue in result.issues])


if __name__ == "__main__":
    unittest.main()
