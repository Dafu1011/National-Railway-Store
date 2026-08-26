import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageChops, ImageDraw, ImageFont

from app.providers import real_image
from app.providers.real_image import (
    KeleFiveImagePipeline,
    _build_detail_page,
    _certificate_rows,
    _compose_certificate,
    _compose_package_label,
    _detail_module_prompts,
    _flatten_certificate_for_tabletop,
    _normalize_certificate_tabletop_background,
    _paste_tabletop_paper,
    _prompt_for,
    _suppress_white_background_shadows,
    _tint_barcode_for_box,
)


class RealImagePipelinePromptTests(unittest.TestCase):

    def test_package_prompt_renders_brand_value_as_large_standalone_text_without_brand_label(self):
        product = {
            "name": "????",
            "brand": "??",
            "model": "ZF-CPU",
            "material": "???",
        }
        project = {"barcode_type": "EAN_13", "barcode_value": "6903244675147"}

        prompt = _prompt_for("package", product, project)

        self.assertIn("brand value only", prompt)
        self.assertIn("large standalone brand wordmark", prompt)
        self.assertIn("large standard printed Chinese brand text", prompt)
        self.assertIn("character correctness and complete stroke structure are more important than sharpness", prompt)
        self.assertIn("slight softness or mild ink blur is acceptable", prompt)
        self.assertIn("not artistic typography", prompt)
        self.assertIn("not calligraphy", prompt)
        self.assertNotIn("?????", prompt)

    def test_detail_module_prompts_put_large_brand_wordmark_only_in_first_section(self):
        prompts = _detail_module_prompts(
            {
                "name": "????",
                "brand": "??",
                "model": "ZF-CPU",
                "material": "???",
            }
        )

        self.assertIn("large standard printed Chinese brand text", prompts[0])
        self.assertIn("character correctness and complete stroke structure are more important than sharpness", prompts[0])
        self.assertIn("slight softness or mild ink blur is acceptable", prompts[0])
        self.assertIn("not artistic typography", prompts[0])
        self.assertIn("not calligraphy", prompts[0])
        self.assertNotIn("large artistic brand wordmark", prompts[0])
        self.assertIn("brand: ??", prompts[0])
        for prompt in prompts[1:]:
            with self.subTest(prompt=prompt):
                self.assertNotIn("brand: ??", prompt)
                self.assertIn("Do not repeat the brand name", prompt)
    def test_non_detail_outputs_request_real_photography_not_rendered_art(self):
        product = {
            "name": "impact wrench",
            "brand": "TORQEX",
            "model": "TX-IW988",
            "category": "electric power tool",
        }

        for output_type in ("main", "certificate", "package", "scene"):
            with self.subTest(output_type=output_type):
                prompt = _prompt_for(output_type, product)
                self.assertIn("real camera photograph", prompt)
                self.assertIn("not CGI", prompt)
                self.assertIn("not a 3D render", prompt)
                self.assertIn("preserve existing physical markings", prompt)

    def test_package_and_certificate_prompts_match_reference_layouts(self):
        product = {
            "name": "impact wrench",
            "brand": "TORQEX",
            "model": "TX-IW988",
            "category": "electric power tool",
        }

        certificate_prompt = _prompt_for("certificate", product)
        project = {
            "barcode_type": "EAN_13",
            "barcode_value": "6903244675147",
            "package_config": {
                "manufacturer_name": "智枫科技",
                "manufacturer_address": "浙江省杭州市西湖区智枫路88号",
            },
        }
        package_prompt = _prompt_for("package", product, project)
        scene_prompt = _prompt_for("scene", product)

        self.assertIn("800x800, 1:1 square", certificate_prompt)
        self.assertIn("pure seamless #ffffff white background", certificate_prompt)
        self.assertIn("pure white matte support surface", certificate_prompt)
        self.assertIn("large pure white negative space across the lower half", certificate_prompt)
        self.assertIn("50 to 55 degrees", certificate_prompt)
        self.assertIn("28 to 35 mm phone wide-angle", certificate_prompt)
        self.assertIn("horizontal tabletop plane", certificate_prompt)
        self.assertIn("visual center around 68% to 72% of image width and 32% to 38% of image height", certificate_prompt)
        self.assertIn("reference-like lower-left placement", certificate_prompt)
        self.assertIn("not a perfectly front-facing rectangle", certificate_prompt)
        self.assertIn("directly generate both the product and the certificate in one natural photo", certificate_prompt)
        self.assertIn("no props, no desk accessories, no plants", certificate_prompt)
        self.assertIn("only the referenced product", certificate_prompt)
        self.assertNotIn("blank paper certificate card", certificate_prompt)
        self.assertNotIn("backend composited flat card", certificate_prompt)
        self.assertIn("a very light natural contact shadow is allowed", certificate_prompt)
        self.assertIn("product shape fidelity is more important than shadow removal", certificate_prompt)
        self.assertNotIn("subtle contact shadows", certificate_prompt)
        self.assertNotIn("straight-on", certificate_prompt)
        self.assertIn("Do not default to a tall narrow bottle package", package_prompt)
        self.assertIn("side information zone reasonably visible to the camera", package_prompt)
        self.assertIn("right-side tabletop when physically possible", package_prompt)
        self.assertIn("pure white background", package_prompt)
        self.assertIn("designed retail packaging, not an oversized shipping package", package_prompt)
        self.assertIn("no unnecessary artificial printed border", package_prompt)
        self.assertIn("unless that border style comes from the package reference", package_prompt)
        self.assertIn("side face should stay visually simple", package_prompt)
        self.assertIn("no random unrelated side icons", package_prompt)
        self.assertIn("avoid unrelated warning symbols", package_prompt)
        self.assertIn("directly print the package text and barcode on the package surface", package_prompt)
        self.assertIn("barcode digits: 6903244675147", package_prompt)
        self.assertIn("manufacturer: 智枫科技", package_prompt)
        self.assertIn("address: 浙江省杭州市西湖区智枫路88号", package_prompt)
        self.assertIn("barcode", package_prompt.lower())
        self.assertIn("slight photographic imperfections", package_prompt)
        self.assertIn("real worksite", scene_prompt)
        self.assertIn("no hands", scene_prompt)
        self.assertNotIn("hand may", scene_prompt)

    def test_main_prompt_requests_minimal_bottom_shadow(self):
        prompt = _prompt_for(
            "main",
            {
                "name": "智枫保温杯",
                "brand": "智枫",
                "model": "ZF-CUP-800",
                "category": "日用品",
            },
        )

        self.assertIn("minimal or no visible floor shadow", prompt)

    def test_certificate_prompt_requests_physical_white_tabletop_scene(self):
        prompt = _prompt_for(
            "certificate",
            {
                "name": "智枫保温杯",
                "brand": "智枫",
                "model": "ZF-CUP-800",
                "category": "日用品",
            },
        )

        self.assertIn("pure seamless #ffffff white background", prompt)
        self.assertIn("pure white matte support surface", prompt)
        self.assertIn("a very light natural contact shadow is allowed", prompt)
        self.assertIn("product shape fidelity is more important than shadow removal", prompt)
        self.assertIn("clean natural product edges are more important than aggressively removing all shadows", prompt)
        self.assertIn("keep a pure-white background while allowing one realistic soft contact shadow", prompt)
        self.assertNotIn("prefer a pure-white no-shadow result", prompt)
        self.assertIn("no horizon line", prompt)
        self.assertIn("50 to 55 degrees", prompt)
        self.assertIn("directly generate both the product and the certificate in one natural photo", prompt)
        self.assertIn("The certificate must be generated by the image model as part of the same camera shot", prompt)
        self.assertIn("no props, no desk accessories, no plants", prompt)
        self.assertIn("only the referenced product", prompt)

    def test_certificate_prompt_matches_reference_phone_snapshot_composition(self):
        prompt = _prompt_for(
            "certificate",
            {
                "name": "Zhifeng thermos cup",
                "brand": "Zhifeng",
                "model": "ZF-CUP-800",
                "category": "drinkware",
            },
        )

        self.assertIn("phone-style angled top-down snapshot", prompt)
        self.assertIn("camera above and slightly in front-left", prompt)
        self.assertIn("Place the uploaded product in the upper-right area", prompt)
        self.assertIn("visual center around 68% to 72% of image width and 32% to 38% of image height", prompt)
        self.assertIn("no product deformation, no warping, no squeezing, no stretching", prompt)
        self.assertIn("cylindrical products must keep straight parallel sides", prompt)
        self.assertIn("do not turn a tall cylinder into a tapered or swollen shape", prompt)
        self.assertIn("preserve the exact original product silhouette", prompt)
        self.assertIn("no jagged stair-step edges, no pixelated cutout edge, no serrated contour", prompt)
        self.assertIn("do not smooth, redraw, stylize, or reinterpret the product body", prompt)
        self.assertIn("use the uploaded image geometry as a locked reference", prompt)
        self.assertIn("no product edge, corner, rim, lip, seam, or silhouette detail may be covered", prompt)
        self.assertIn("the complete outer boundary must remain visible", prompt)
        self.assertIn("The certificate is a single small horizontal rectangular white hard card", prompt)
        self.assertIn("visual center should be around 31% to 35% of image width and 62% to 66% of image height", prompt)
        self.assertIn("should sit reasonably close to the product base without touching it", prompt)
        self.assertIn("must leave a clear white gap from the product and never slide underneath or cover the product", prompt)
        self.assertIn("lower-left to upper-right diagonal relationship", prompt)
        self.assertIn("do not overlap", prompt)
        self.assertNotIn("product stands upright", prompt)

    def test_certificate_prompt_requires_adaptive_physical_product_orientation(self):
        prompt = _prompt_for(
            "certificate",
            {
                "name": "long drill bit set",
                "brand": "TORQEX",
                "model": "TX-DRILL-20",
                "category": "hardware tool",
            },
        )

        self.assertIn("Choose the product's orientation from its real structure, center of gravity, and normal display logic", prompt)
        self.assertIn("do not mechanically force every product to stand upright", prompt)
        self.assertIn("Drill bits, knife rods, screwdrivers, pen-shaped tools, long accessories, pipes", prompt)
        self.assertIn("must lie flat or slightly diagonal rather than stand vertically against gravity", prompt)
        self.assertIn("no floating, no tipping, no impossible balance, no intersection", prompt)

    def test_certificate_prompt_is_detailed_enough_to_force_casual_phone_co_photo(self):
        prompt = _prompt_for(
            "certificate",
            {
                "name": "Zhifeng thermos cup",
                "brand": "Zhifeng",
                "model": "ZF-CUP-800",
                "category": "drinkware",
            },
        )

        self.assertIn("only product reference", prompt)
        self.assertIn("真实自然的手机随手拍", prompt)
        self.assertIn("no wall, no window curtain, no visible table edge, no floor", prompt)
        self.assertIn("white area should occupy most of the frame", prompt)
        self.assertIn("lower half must keep a large clean pure-white negative-space area", prompt)
        self.assertIn("do not add parts, accessories, packaging, labels, or quantities that are not visible in the uploaded image", prompt)
        self.assertIn("single small horizontal rectangular white hard card", prompt)
        self.assertIn("not tissue, not folded, not stacked, not diamond-patterned", prompt)
        self.assertIn("clean sharply cut edges and corners", prompt)
        self.assertIn("may show only very slight natural paper waviness or tiny surface wrinkles", prompt)
        self.assertIn("no frayed, furry, torn, ragged, or fuzzy edges", prompt)
        self.assertIn("long edge nearly horizontal with only a slight 3 to 5 degree rotation", prompt)
        self.assertIn("not a vertical standing card, not a portrait paper sheet, not a floating overlay", prompt)
        self.assertIn("not a full top-down flat-lay and not a straight front view", prompt)
        self.assertIn("ordinary indoor natural-light phone snapshot", prompt)
        self.assertIn("The certificate face must be clear and readable", prompt)
        self.assertIn("one small barcode using the entered barcode digits", prompt)
        self.assertIn("barcode numerals must exactly match the entered barcode digits", prompt)
        self.assertIn("first digit printed outside the barcode bars on the left", prompt)
        self.assertIn("start guard, center guard before the eighth digit, and end guard bars must be the longest", prompt)
        self.assertIn("thin and thick vertical bars with varied bar heights", prompt)
        self.assertIn("no malformed barcode numerals, no random barcode digits", prompt)
        self.assertIn("no garbled characters, no pseudo text", prompt)

    def test_certificate_prompt_leaves_inspector_area_for_backend_only(self):
        prompt = _prompt_for(
            "certificate",
            {
                "name": "厚抹生乳茶",
                "brand": "别样泡泡",
                "model": "500ml",
                "category": "food",
            },
            {
                "barcode_type": "EAN_13",
                "barcode_value": "6924613866618",
                "certificate_config": {"production_date": "2026-08-19", "inspector": "QC-01"},
            },
        )

        self.assertNotIn("inspector: QC-01;", prompt)
        self.assertIn("Do not print the inspector parameter value as ordinary black text", prompt)
        self.assertIn("do not show a normal 检验员：QC-01 row", prompt)
        self.assertIn("The only allowed reserved area is the normal inspector-value area on the certificate", prompt)
        self.assertIn("The backend will render the inspector value after image generation", prompt)
        self.assertIn("keep the inspector-value area clean and blank", prompt)
        self.assertIn("The inspector value area must stay safely above the barcode and must never touch the barcode", prompt)
        for forbidden in ("QC stamp", "quality inspection stamp", "red stamp", "stamp mark", "质检章"):
            self.assertNotIn(forbidden.lower(), prompt.lower())

    def test_certificate_prompt_isolates_backend_inspector_mark_from_product_without_banning_real_red_product_parts(self):
        prompt = _prompt_for(
            "certificate",
            {
                "name": "空气开关",
                "brand": "德力西电气",
                "model": "10个",
                "category": "hardware",
            },
            {
                "barcode_type": "EAN_13",
                "barcode_value": "6903244675147",
                "certificate_config": {"production_date": "2026-08-26", "inspector": "QC-01"},
            },
        )

        self.assertIn("Product red elements are allowed only when they already exist in the uploaded product reference", prompt)
        self.assertIn("do not transfer certificate inspector-area semantics onto the product", prompt)
        self.assertIn("certificate-only inspector area must not appear on product switches", prompt)
        self.assertIn("Do not run any global red-color removal", prompt)
        self.assertNotIn("No red circular mark, red oval mark, red ring, red seal", prompt)

    def test_certificate_qc_stamp_renderer_uses_inspection_label_and_inspector_digits(self):
        card = Image.new("RGBA", (120, 90), (255, 255, 255, 255))
        captured_text: list[str] = []
        original_text = ImageDraw.ImageDraw.text

        def capture_text(self, xy, text, *args, **kwargs):
            captured_text.append(str(text))
            return original_text(self, xy, text, *args, **kwargs)

        ImageDraw.ImageDraw.text = capture_text
        try:
            real_image._draw_qc_stamp(
                card,
                (20, 20),
                "QC-01",
                ImageFont.load_default(),
                ImageFont.load_default(),
            )
        finally:
            ImageDraw.ImageDraw.text = original_text

        self.assertEqual(captured_text, ["检验", "01"])

    def test_certificate_backend_qc_stamp_avoids_detected_barcode(self):
        image = Image.new("RGB", (800, 800), "white")
        draw = ImageDraw.Draw(image)
        for x in range(260, 420, 6):
            draw.rectangle((x, 650, x + 2, 735), fill=(0, 0, 0))
        project = {"certificate_config": {"inspector": "QC-01"}}

        result = real_image._overlay_certificate_qc_stamp(image, project, "C:/Windows/Fonts/msyh.ttc").convert("RGB")

        red_in_barcode = 0
        red_above_barcode = 0
        for y in range(0, result.height):
            for x in range(0, result.width):
                r, g, b = result.getpixel((x, y))
                if r > 140 and g < 110 and b < 110 and r - max(g, b) > 45:
                    if 260 <= x <= 420 and 650 <= y <= 735:
                        red_in_barcode += 1
                    if 560 <= y < 650:
                        red_above_barcode += 1

        self.assertEqual(red_in_barcode, 0)
        self.assertGreater(red_above_barcode, 20)

    def test_certificate_backend_places_qc_stamp_near_inspector_value_area(self):
        image = Image.new("RGB", (800, 800), "white")
        draw = ImageDraw.Draw(image)
        for x in range(260, 420, 6):
            draw.rectangle((x, 650, x + 2, 735), fill=(0, 0, 0))

        x, y = real_image._certificate_qc_stamp_position(image, (70, 52))

        self.assertLess(x, 260)
        self.assertGreaterEqual(y, 560)
        self.assertLessEqual(y + 52, 646)

    def test_certificate_barcode_detection_ignores_upper_table_columns(self):
        image = Image.new("RGB", (800, 800), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((75, 410, 435, 705), outline=(37, 99, 172), width=3)
        for x in range(235, 345, 22):
            draw.line((x, 470, x, 610), fill=(35, 35, 35), width=2)
        for x in range(180, 360, 6):
            draw.rectangle((x, 625, x + 2, 690), fill=(0, 0, 0))

        barcode_bbox = real_image._detect_certificate_barcode_bbox(image)

        self.assertIsNotNone(barcode_bbox)
        assert barcode_bbox is not None
        self.assertGreaterEqual(barcode_bbox[1], 620)

    def test_certificate_barcode_detection_covers_middle_lower_card_area(self):
        image = Image.new("RGB", (800, 800), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((110, 430, 410, 735), outline=(37, 99, 172), width=3)
        for x in range(230, 360, 6):
            draw.rectangle((x, 575, x + 2, 635), fill=(0, 0, 0))

        barcode_bbox = real_image._detect_certificate_barcode_bbox(image)

        self.assertIsNotNone(barcode_bbox)
        assert barcode_bbox is not None
        self.assertLessEqual(barcode_bbox[1], 580)

    def test_certificate_backend_qc_stamp_avoids_middle_lower_barcode(self):
        image = Image.new("RGB", (800, 800), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((110, 430, 410, 735), outline=(37, 99, 172), width=3)
        for x in range(230, 360, 6):
            draw.rectangle((x, 575, x + 2, 635), fill=(0, 0, 0))
        project = {"certificate_config": {"inspector": "QC-01"}}

        result = real_image._overlay_certificate_qc_stamp(image, project, "C:/Windows/Fonts/msyh.ttc").convert("RGB")

        red_in_barcode = 0
        red_on_card = 0
        for y in range(result.height):
            for x in range(result.width):
                r, g, b = result.getpixel((x, y))
                if r > 140 and g < 120 and b < 120 and r - max(g, b) > 35:
                    if 224 <= x <= 366 and 569 <= y <= 641:
                        red_in_barcode += 1
                    if 110 <= x <= 410 and 430 <= y <= 735:
                        red_on_card += 1

        self.assertEqual(red_in_barcode, 0)
        self.assertGreater(red_on_card, 20)

    def test_certificate_card_detection_ignores_unrelated_upper_blue_product_pixels(self):
        image = Image.new("RGB", (800, 800), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((300, 260, 360, 315), fill=(50, 90, 180))
        draw.rectangle((110, 430, 410, 735), outline=(37, 99, 172), width=3)
        draw.text((155, 475), "产品合格证", fill=(30, 30, 30))

        card_bbox = real_image._detect_certificate_card_bbox(image)

        self.assertIsNotNone(card_bbox)
        assert card_bbox is not None
        self.assertGreaterEqual(card_bbox[1], 410)

    def test_certificate_card_detection_aggregates_fragmented_blue_border(self):
        image = Image.new("RGB", (800, 800), "white")
        draw = ImageDraw.Draw(image)
        blue = (37, 99, 172)
        for box in (
            (110, 430, 190, 433),
            (250, 430, 410, 433),
            (110, 732, 230, 735),
            (290, 732, 410, 735),
            (110, 430, 113, 520),
            (110, 610, 113, 735),
            (407, 430, 410, 540),
            (407, 620, 410, 735),
        ):
            draw.rectangle(box, fill=blue)
        draw.text((165, 475), "产品合格证", fill=(30, 30, 30))

        card_bbox = real_image._detect_certificate_card_bbox(image)

        self.assertIsNotNone(card_bbox)
        assert card_bbox is not None
        self.assertLessEqual(card_bbox[0], 100)
        self.assertLessEqual(card_bbox[1], 420)
        self.assertGreaterEqual(card_bbox[2], 420)
        self.assertGreaterEqual(card_bbox[3], 745)

    def test_certificate_qc_stamp_defaults_near_inspector_area_above_barcode(self):
        image = Image.new("RGB", (800, 800), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((110, 430, 410, 735), outline=(37, 99, 172), width=3)
        draw.text((135, 610), "检验员:", fill=(30, 30, 30))
        for x in range(190, 360, 6):
            draw.rectangle((x, 660, x + 2, 725), fill=(0, 0, 0))

        x, y = real_image._certificate_qc_stamp_position(image, (62, 48))
        barcode_bbox = real_image._detect_certificate_barcode_bbox(image)

        self.assertIsNotNone(barcode_bbox)
        assert barcode_bbox is not None
        self.assertGreaterEqual(x, 255)
        self.assertLessEqual(x, 330)
        self.assertLessEqual(y + 48, barcode_bbox[1] - 10)
        self.assertGreaterEqual(y, 570)

    def test_certificate_backend_removes_upper_model_stamp_before_safe_backend_stamp(self):
        image = Image.new("RGB", (800, 800), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((110, 430, 410, 735), outline=(37, 99, 172), width=3)
        draw.text((155, 475), "产品合格证", fill=(30, 30, 30))
        draw.ellipse((250, 385, 312, 425), outline=(198, 45, 45), width=2)
        for x in range(210, 350, 6):
            draw.rectangle((x, 655, x + 2, 720), fill=(0, 0, 0))
        project = {"certificate_config": {"inspector": "QC-01"}}

        result = real_image._overlay_certificate_qc_stamp(image, project, "C:/Windows/Fonts/msyh.ttc").convert("RGB")

        leaked_red = 0
        safe_red = 0
        for y in range(result.height):
            for x in range(result.width):
                r, g, b = result.getpixel((x, y))
                if r > 140 and g < 120 and b < 120 and r - max(g, b) > 35:
                    if 245 <= x <= 317 and 380 <= y <= 430:
                        leaked_red += 1
                    if 245 <= x <= 330 and 560 <= y <= 650:
                        safe_red += 1

        self.assertLess(leaked_red, 5)
        self.assertGreater(safe_red, 20)

    def test_certificate_backend_uses_certificate_card_area_when_barcode_is_missing(self):
        image = Image.new("RGB", (800, 800), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((110, 460, 410, 735), outline=(37, 99, 172), width=3)
        draw.text((155, 505), "产品合格证", fill=(30, 30, 30))
        draw.text((140, 655), "检验员:", fill=(30, 30, 30))

        x, y = real_image._certificate_qc_stamp_position(image, (70, 52))
        card_bbox = real_image._detect_certificate_card_bbox(image)
        assert card_bbox is not None
        guard_bbox = real_image._certificate_barcode_guard_bbox(None, card_bbox, image.width, image.height)

        self.assertGreaterEqual(x, 230)
        self.assertLessEqual(x, 330)
        self.assertGreaterEqual(y, 540)
        self.assertLessEqual(y + 52, guard_bbox[1])

    def test_certificate_backend_keeps_stamp_out_of_fallback_barcode_zone(self):
        image = Image.new("RGB", (800, 800), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((110, 460, 410, 735), outline=(37, 99, 172), width=3)
        draw.text((155, 505), "产品合格证", fill=(30, 30, 30))
        draw.text((140, 655), "检验员:", fill=(30, 30, 30))

        _x, y = real_image._certificate_qc_stamp_position(image, (70, 52))
        card_bbox = real_image._detect_certificate_card_bbox(image)
        assert card_bbox is not None
        guard_bbox = real_image._certificate_barcode_guard_bbox(None, card_bbox, image.width, image.height)

        self.assertLessEqual(y + 52, guard_bbox[1])

    def test_certificate_stamp_position_requires_card_bounds_and_barcode_clearance(self):
        card_bbox = (100, 400, 320, 620)
        barcode_guard = (100, 535, 320, 620)

        self.assertFalse(
            real_image._certificate_stamp_position_is_valid((170, 510), (60, 44), card_bbox, barcode_guard)
        )
        self.assertFalse(
            real_image._certificate_stamp_position_is_valid((70, 470), (60, 44), card_bbox, barcode_guard)
        )
        self.assertTrue(
            real_image._certificate_stamp_position_is_valid((170, 475), (60, 44), card_bbox, barcode_guard)
        )

    def test_certificate_backend_removes_model_generated_red_residue_before_qc_stamp(self):
        image = Image.new("RGB", (800, 800), "white")
        draw = ImageDraw.Draw(image)
        draw.ellipse((140, 620, 215, 650), outline=(198, 45, 45), width=2)
        for x in range(300, 430, 6):
            draw.rectangle((x, 700, x + 2, 765), fill=(0, 0, 0))
        project = {"certificate_config": {"inspector": "QC-01"}}

        result = real_image._overlay_certificate_qc_stamp(image, project, "C:/Windows/Fonts/msyh.ttc").convert("RGB")

        residue_red = 0
        final_red = 0
        for y in range(result.height):
            for x in range(result.width):
                r, g, b = result.getpixel((x, y))
                if r > 140 and g < 120 and b < 120 and r - max(g, b) > 35:
                    if 135 <= x <= 220 and 615 <= y <= 655:
                        residue_red += 1
                    if 280 <= x <= 430 and 620 <= y <= 700:
                        final_red += 1

        self.assertLess(residue_red, 5)
        self.assertGreater(final_red, 20)

    def test_certificate_prompt_lists_required_certificate_fields_and_smaller_qc_stamp(self):
        prompt = _prompt_for(
            "certificate",
            {"name": "厚抹生乳茶", "brand": "别样泡泡", "model": "500ml"},
            {
                "barcode_type": "EAN_13",
                "barcode_value": "6924613866618",
                "certificate_config": {
                    "production_date": "2026-08-19",
                    "inspector": "QC-01",
                    "manufacturer_name": "智枫生产厂家",
                    "manufacturer_address": "吉林省长春市南关区幸福街888号",
                },
            },
        )

        self.assertIn("Required certificate rows: 品牌, 名称, 规格型号, 生产日期, 生产厂家, 厂址, 检验员 value area left blank for backend inspector rendering", prompt)
        self.assertIn("barcode centered horizontally", prompt)
        self.assertIn("backend-applied inspector mark remains half the previous visual size", prompt)
        self.assertIn("manufacturer: 智枫生产厂家", prompt)
        self.assertIn("factory address: 吉林省长春市南关区幸福街888号", prompt)

    def test_prompts_describe_optional_reference_image_style_rules(self):
        certificate_prompt = _prompt_for(
            "certificate",
            {"name": "厚抹生乳茶", "brand": "别样泡泡", "model": "500ml"},
            {"has_certificate_reference": True},
        )
        package_prompt = _prompt_for(
            "package",
            {"name": "蓝牙鼠标", "brand": "蝰蛇", "model": "ZF-CPU"},
            {"has_package_reference": True},
        )

        self.assertIn("A certificate reference image is provided as an additional reference image", certificate_prompt)
        self.assertIn("Use the certificate reference only for certificate card style", certificate_prompt)
        self.assertIn("A package reference image is provided as an additional reference image", package_prompt)
        self.assertIn("Use the package reference only for packaging style", package_prompt)
        self.assertIn("Package size must be chosen from the real product volume and the user-entered 规格型号/model value", package_prompt)
        self.assertIn("the visible package must be taller than the nearby individual product's highest point", package_prompt)
        self.assertIn("overall outer volume must be clearly larger than the product", package_prompt)
        self.assertIn("make the package length and width about 1.3x larger than that current minimum-fit package size", package_prompt)
        self.assertIn("do not stretch, squeeze, warp, or distort package text, logos, barcode, illustrations, or surface graphics", package_prompt)

    def test_package_reference_prompt_does_not_force_kraft_or_plain_carton_style(self):
        prompt = _prompt_for(
            "package",
            {"name": "厚抹生乳茶", "brand": "别样泡泡", "model": "500ml×6瓶"},
            {
                "has_package_reference": True,
                "barcode_type": "EAN_13",
                "barcode_value": "6903244675147",
            },
        )

        self.assertIn("The scene must keep a clean seamless pure #ffffff white background", prompt)
        self.assertIn("package reference image is the highest-priority packaging-style reference", prompt)
        self.assertIn("box type, form factor, handle or carry strap", prompt)
        self.assertNotIn("kraft", prompt.lower())
        self.assertNotIn("plain unmarked side face", prompt)
        self.assertNotIn("front face nearly parallel to the camera", prompt)
        self.assertNotIn("no decorative side graphics", prompt)
        self.assertNotIn("Use a normal retail carton style: a simple store-ready upright", prompt)

    def test_certificate_prompt_forbids_curved_or_gray_support_plane(self):
        prompt = _prompt_for(
            "certificate",
            {
                "name": "Zhifeng thermos cup",
                "brand": "Zhifeng",
                "model": "ZF-CUP-800",
                "category": "drinkware",
            },
        )

        self.assertIn("single flat, level, uncurved horizontal plane", prompt)
        self.assertIn("no curved sweep backdrop", prompt)
        self.assertIn("no concave or convex support surface", prompt)
        self.assertIn("no gray gradient, no off-white texture, no speckled background noise", prompt)
        self.assertIn("no gray or beige shadow patch", prompt)

    def test_shadow_suppression_removes_light_neutral_floor_shadows_without_erasing_product_highlights(self):
        image = Image.new("RGB", (800, 800), "white")
        draw = ImageDraw.Draw(image)
        draw.ellipse((420, 665, 650, 725), fill=(222, 222, 220))
        draw.rectangle((470, 260, 610, 680), fill=(12, 12, 12))
        draw.rectangle((520, 300, 560, 360), fill=(170, 170, 168))

        result = _suppress_white_background_shadows(image)

        self.assertEqual(result.getpixel((520, 705)), (255, 255, 255))
        self.assertEqual(result.getpixel((520, 500)), (12, 12, 12))
        self.assertEqual(result.getpixel((540, 330)), (170, 170, 168))

    def test_certificate_tabletop_background_becomes_pure_white_without_erasing_contact_shadow(self):
        image = Image.new("RGB", (800, 800), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 400, 400), fill=(238, 239, 237))
        draw.rectangle((0, 400, 400, 800), fill=(242, 242, 240))
        draw.point((120, 120), fill=(232, 233, 232))
        draw.ellipse((510, 650, 700, 710), fill=(222, 222, 220))
        draw.ellipse((430, 620, 760, 735), fill=(216, 214, 206))
        draw.rectangle((560, 260, 665, 675), fill=(18, 18, 18))

        result = _normalize_certificate_tabletop_background(image)

        self.assertEqual(result.getpixel((80, 80)), (255, 255, 255))
        self.assertEqual(result.getpixel((80, 500)), (255, 255, 255))
        self.assertEqual(result.getpixel((120, 120)), (255, 255, 255))
        self.assertEqual(result.getpixel((600, 690)), (255, 255, 255))
        self.assertEqual(result.getpixel((700, 700)), (255, 255, 255))
        self.assertEqual(result.getpixel((600, 400)), (18, 18, 18))

    def test_certificate_background_preserves_realistic_contact_shadow_without_erasing_product_edges(self):
        image = Image.new("RGB", (800, 800), "white")
        draw = ImageDraw.Draw(image)
        draw.ellipse((585, 455, 760, 545), fill=(206, 199, 194))
        draw.ellipse((545, 470, 690, 555), fill=(191, 184, 176))
        draw.ellipse((575, 465, 640, 505), fill=(132, 128, 119))
        draw.rectangle((460, 210, 610, 530), fill=(20, 20, 20))
        draw.rectangle((452, 230, 459, 500), fill=(168, 168, 164))

        result = _normalize_certificate_tabletop_background(image)

        self.assertEqual(result.getpixel((650, 470)), (206, 199, 194))
        self.assertEqual(result.getpixel((635, 495)), (132, 128, 119))
        self.assertEqual(result.getpixel((520, 350)), (20, 20, 20))
        self.assertEqual(result.getpixel((455, 320)), (168, 168, 164))

    def test_certificate_background_cleanup_preserves_light_product_edges(self):
        image = Image.new("RGB", (800, 800), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 360, 800), fill=(245, 245, 243))
        draw.rectangle((430, 210, 610, 560), fill=(18, 18, 18))
        draw.rectangle((418, 230, 429, 540), fill=(168, 168, 164))
        draw.rectangle((611, 230, 622, 540), fill=(176, 176, 172))

        result = _normalize_certificate_tabletop_background(image)

        self.assertEqual(result.getpixel((80, 80)), (255, 255, 255))
        self.assertEqual(result.getpixel((423, 320)), (168, 168, 164))
        self.assertEqual(result.getpixel((616, 320)), (176, 176, 172))

    def test_certificate_output_keeps_direct_model_photo_without_backend_card_composition(self):
        class FakeProvider:
            def edit_image(self, *, prompt, size, image_paths):
                image = Image.new("RGB", (1024, 1024), "white")
                draw = ImageDraw.Draw(image)
                draw.ellipse((620, 850, 850, 925), fill=(222, 222, 220))
                draw.rectangle((680, 320, 805, 875), fill=(20, 20, 20))
                draw.rectangle((180, 650, 450, 760), fill=(248, 248, 246), outline=(0, 87, 165), width=3)
                buffer = BytesIO()
                image.save(buffer, format="PNG")
                return buffer.getvalue()

        compose_calls = []
        provider = FakeProvider()
        pipeline = KeleFiveImagePipeline(provider, font_path="C:/Windows/Fonts/msyh.ttc", edit_size="1024x1024")
        product = {"name": "Zhifeng thermos cup", "brand": "Zhifeng", "model": "ZF-CUP-800", "category": "drinkware"}
        project = {"barcode_type": "EAN_13", "barcode_value": "4006381333931"}

        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.png"
            Image.new("RGB", (800, 800), "white").save(source)
            original_compose = real_image._compose_certificate
            real_image._compose_certificate = lambda *_args, **_kwargs: compose_calls.append(True)
            try:
                outputs = pipeline.generate_five_images(
                    output_dir=Path(tmp),
                    job_id="job",
                    product=product,
                    project=project,
                    source_image_path=source,
                )
            finally:
                real_image._compose_certificate = original_compose
            certificate = next(output for output in outputs if output.output_type == "certificate")
            with Image.open(certificate.path) as generated:
                generated_rgb = generated.convert("RGB")
                shadow_pixel = generated_rgb.getpixel((575, 705))
                data = generated_rgb.tobytes()
                red_pixels = sum(
                    1
                    for index in range(0, len(data), 3)
                    if (
                        (r := data[index]) > 150
                        and (g := data[index + 1]) < 100
                        and (b := data[index + 2]) < 100
                        and r - max(g, b) > 60
                    )
                )

        self.assertEqual(compose_calls, [])
        self.assertEqual(shadow_pixel, (222, 222, 220))
        self.assertGreater(red_pixels, 40)

    def test_detail_output_is_allowed_to_be_ecommerce_design(self):
        prompt = _prompt_for(
            "detail",
            {
                "name": "impact wrench",
                "brand": "TORQEX",
                "model": "TX-IW988",
                "category": "electric power tool",
            },
        )

        self.assertIn("ecommerce detail page", prompt)
        self.assertIn("only stitch four finished generated sections", prompt)
        self.assertNotIn("real camera photograph", prompt)

    def test_reference_base_requires_exact_visible_logo_and_registered_mark(self):
        prompt = _prompt_for(
            "main",
            {
                "name": "Jeep thermos cup",
                "brand": "Jeep",
                "model": "ZF-CUP-800",
                "category": "drinkware",
            },
        )

        self.assertIn("exact visible logo", prompt)
        self.assertIn("tiny registered trademark symbol", prompt)
        self.assertIn("must appear in every generated product view", prompt)

    def test_all_image_prompts_keep_same_product_style_identity(self):
        product = {
            "name": "厚抹生乳茶",
            "brand": "别样泡泡",
            "model": "500ml×6瓶",
            "category": "食品饮料",
        }

        for output_type in ["main", "certificate", "package", "detail", "scene"]:
            with self.subTest(output_type=output_type):
                prompt = _prompt_for(output_type, product, {"barcode_type": "EAN_13", "barcode_value": "6903244675147"})
                self.assertIn("All five generated image types must depict the same single uploaded product", prompt)
                self.assertIn("same product style identity", prompt)
                self.assertIn("Do not switch to a different SKU, package variant, colorway, flavor, label design, logo layout, cap shape, bottle shape, accessory set, or material finish", prompt)

    def test_package_reference_style_must_be_adapted_to_current_product(self):
        prompt = _prompt_for(
            "package",
            {"name": "厚抹生乳茶", "brand": "别样泡泡", "model": "500ml×6瓶", "category": "食品饮料"},
            {"has_package_reference": True, "barcode_type": "EAN_13", "barcode_value": "6903244675147"},
        )

        self.assertIn("The current uploaded product and user-entered specification are higher priority than copying the reference package literally", prompt)
        self.assertIn("Adapt the referenced package style to the current product category, product volume, product count, storage needs, and realistic retail packaging logic", prompt)
        self.assertIn("If the reference package belongs to a different product category", prompt)
        self.assertIn("do not copy a packaging proportion, carry structure, visual motif, or premium/cartoon/fresh-food style that would make the final package look mismatched to the current product", prompt)

    def test_package_size_must_fit_product_quantity_from_specification_model(self):
        prompt = _prompt_for(
            "package",
            {"name": "厚抹生乳茶", "brand": "别样泡泡", "model": "500ml×6瓶", "category": "食品饮料"},
            {"has_package_reference": True, "barcode_type": "EAN_13", "barcode_value": "6903244675147"},
        )

        self.assertIn("The package must be physically large enough to contain the uploaded product and every unit implied by the user-entered specification model", prompt)
        self.assertIn("Treat quantity expressions in the specification model, such as 6 bottles, 6 pcs, x6, ×6, 500ml×6瓶, or one box of multiple units, as hard packing capacity requirements", prompt)
        self.assertIn("Do not generate a package sized for only one unit when the specification model says multiple units", prompt)
        self.assertIn("Package dimensions, internal volume, divider/spacing allowance, and external proportions must obey real packing physics", prompt)
        self.assertIn("Package physical capacity has higher priority than reference package style, composition, beauty, and front display completeness", prompt)
        self.assertIn("The visible package must look larger than the product in every required loading direction", prompt)
        self.assertIn("For bottle, cup, can, jar, and drink products, the package internal height must be greater than the product height when packed upright", prompt)
        self.assertIn("If the product is shown standing beside the package, the package must not appear shorter, thinner, or too narrow to contain that product", prompt)
        self.assertIn("Detected multi-unit bottle specification: 6 bottles", prompt)
        self.assertIn("Use a six-bottle carton packing structure, not a single-bottle gift box", prompt)
        self.assertIn("Arrange the internal capacity as 3 bottles by 2 bottles upright", prompt)

    def test_package_bottle_product_should_stand_upright_by_default(self):
        prompt = _prompt_for(
            "package",
            {"name": "果粒橙", "brand": "美汁源", "model": "500ml×6瓶", "category": "食品饮料"},
            {"has_package_reference": True, "barcode_type": "EAN_13", "barcode_value": "6903244675147"},
        )

        self.assertIn("For bottles, cans, cups, jars, and stable flat-bottom containers, the product should stand upright beside the package by default", prompt)
        self.assertIn("Do not lay a bottle, can, cup, jar, or stable flat-bottom container horizontally", prompt)
        self.assertIn("This upright-container rule has higher priority than the general natural resting pose rule", prompt)

    def test_package_mouse_product_keeps_natural_tabletop_resting_pose(self):
        prompt = _prompt_for(
            "package",
            {"name": "蓝牙鼠标", "brand": "蝰蛇", "model": "ZF-CPU", "category": "电子产品"},
            {"has_package_reference": True, "barcode_type": "EAN_13", "barcode_value": "6903244675147"},
        )

        self.assertIn("For desktop-use products, handheld devices, controllers, remotes, mice, keyboards", prompt)
        self.assertIn("place the product in its real tabletop resting pose", prompt)

    def test_package_information_area_and_barcode_stay_on_side_panel(self):
        prompt_with_reference = _prompt_for(
            "package",
            {"name": "厚抹生乳茶", "brand": "别样泡泡", "model": "500ml×6瓶", "category": "食品饮料"},
            {"has_package_reference": True, "barcode_type": "EAN_13", "barcode_value": "6903244675147"},
        )
        prompt_without_reference = _prompt_for(
            "package",
            {"name": "厚抹生乳茶", "brand": "别样泡泡", "model": "500ml×6瓶", "category": "食品饮料"},
            {"barcode_type": "EAN_13", "barcode_value": "6903244675147"},
        )

        for prompt in [prompt_with_reference, prompt_without_reference]:
            with self.subTest(prompt=prompt):
                self.assertIn("The ordinary package information area must be on the visible package side panel only", prompt)
                self.assertIn("Do not create a front information area", prompt)
                self.assertIn("The barcode must be directly below the side information area", prompt)
                self.assertIn("The barcode and all information rows must remain fully visible, uncropped, unobstructed, and inside the same side panel", prompt)
                self.assertNotIn("If the package reference has a visible barcode placement", prompt)
                self.assertNotIn("lower-left corner of the package front", prompt)

    def test_package_prompt_uses_user_entered_information_as_source_of_truth(self):
        prompt = _prompt_for(
            "package",
            {"name": "厚抹生乳茶", "brand": "别样泡泡", "model": "500ml×6瓶", "category": "食品饮料"},
            {"has_package_reference": True, "barcode_type": "EAN_13", "barcode_value": "6903244675147"},
        )

        self.assertIn("User-entered product information is the source of truth for all readable product facts", prompt)
        self.assertIn("do not preserve or copy conflicting readable product facts from the uploaded product photo or package reference", prompt)
        self.assertIn("If the visual source contains old or conflicting text, keep only the product appearance or package style", prompt)
        self.assertNotIn("If a user-entered value conflicts with the visible product category, structure, or appearance, omit that row", prompt)

    def test_detail_module_prompts_preserve_logo_markings_and_avoid_props(self):
        prompts = _detail_module_prompts(
            {
                "name": "Jeep thermos cup",
                "brand": "Jeep",
                "model": "ZF-CUP-800",
                "category": "drinkware",
            }
        )

        self.assertTrue(prompts)
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertIn("exact same visible product logo", prompt)
                self.assertIn("tiny registered trademark symbol", prompt)
                self.assertIn("plain white or very light neutral background", prompt)
                self.assertIn("no laptop, no books, no pen, no plant", prompt)
                self.assertNotIn("usage scene", prompt)
                self.assertNotIn("daily use", prompt)
                self.assertNotIn("未填写", prompt)

    def test_detail_module_prompts_keep_all_product_parts_from_same_reference(self):
        prompts = _detail_module_prompts(
            {
                "name": "uploaded multi-detail product",
                "brand": "ReferenceBrand",
                "model": "REF-001",
                "category": "generic product",
            }
        )

        self.assertTrue(prompts)
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertIn("same single uploaded product reference", prompt)
                self.assertIn("every close-up, bottom view, top view, side view, macro crop, inset, and full-product view", prompt)
                self.assertIn("must share the same structure, geometry, proportions, material, texture, color, seams, edges, bevels, labels, logo position, and visible markings", prompt)
                self.assertIn("Do not invent a different bottom, underside, lid, cap, base, anti-slip pad, connector, label, badge, logo placement, surface pattern, display stand, support pole, base, hanger, rack, mannequin, or non-product support hardware", prompt)
                self.assertIn("If a part of the product is not visible in the uploaded reference, infer only a physically plausible continuation without adding readable logos, brand marks, labels, icons, decorative rings, or new surface features", prompt)

    def test_certificate_template_is_smaller_and_contains_required_fields(self):
        product = {
            "name": "智枫保温杯",
            "brand": "智枫",
            "model": "ZF-CUP-800",
            "specs": [{"key": "容量", "value": "800", "unit": "ml"}],
        }
        project = {
            "barcode_type": "EAN_13",
            "barcode_value": "4006381333931",
            "certificate_config": {
                "production_date": "2026-07-27",
                "inspector": "QC-01",
                "company_name": "智枫科技",
            },
        }

        rows = _certificate_rows(product, project)
        self.assertEqual([label for label, _value in rows], ["品牌", "名称", "规格型号", "生产日期", "生产厂家", "厂址"])

        image = Image.new("RGB", (800, 800), "white")
        _compose_certificate(image, product, project, "C:/Windows/Fonts/msyh.ttc")
        diff = ImageChops.difference(image, Image.new("RGB", image.size, "white"))
        bbox = diff.getbbox()
        self.assertIsNotNone(bbox)
        assert bbox is not None
        self.assertGreaterEqual(bbox[2] - bbox[0], 300)
        self.assertGreaterEqual(bbox[3] - bbox[1], 170)
        self.assertLessEqual(bbox[2] - bbox[0], 335)
        self.assertLessEqual(bbox[3] - bbox[1], 265)

    def test_certificate_composition_avoids_shadow_and_barcode_label(self):
        product = {
            "name": "智枫保温杯",
            "brand": "智枫",
            "model": "ZF-CUP-800",
            "specs": [{"key": "容量", "value": "800", "unit": "ml"}],
        }
        project = {
            "barcode_type": "EAN_13",
            "barcode_value": "4006381333931",
            "certificate_config": {
                "production_date": "2026-07-27",
                "inspector": "QC-01",
                "company_name": "智枫科技",
            },
        }
        captured_text: list[str] = []
        original_text = ImageDraw.ImageDraw.text
        original_shadow = real_image._paste_rgba_with_shadow

        def capture_text(self, xy, text, *args, **kwargs):
            captured_text.append(str(text))
            return original_text(self, xy, text, *args, **kwargs)

        ImageDraw.ImageDraw.text = capture_text
        real_image._paste_rgba_with_shadow = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("certificate must not use synthetic shadow"))
        try:
            _compose_certificate(Image.new("RGB", (800, 800), "white"), product, project, "C:/Windows/Fonts/msyh.ttc")
        finally:
            ImageDraw.ImageDraw.text = original_text
            real_image._paste_rgba_with_shadow = original_shadow

        self.assertNotIn("条形码:", captured_text)

    def test_certificate_template_has_small_red_qc_stamp(self):
        product = {
            "name": "Zhifeng thermos cup",
            "brand": "Zhifeng",
            "model": "ZF-CUP-800",
            "specs": [{"key": "capacity", "value": "800", "unit": "ml"}],
        }
        project = {
            "barcode_type": "EAN_13",
            "barcode_value": "4006381333931",
            "certificate_config": {"production_date": "2026-08-05", "inspector": "QC-01"},
        }
        image = Image.new("RGB", (800, 800), "white")

        _compose_certificate(image, product, project, "C:/Windows/Fonts/msyh.ttc")

        red_pixels = 0
        data = image.tobytes()
        for index in range(0, len(data), 3):
            r, g, b = data[index], data[index + 1], data[index + 2]
            if r > 140 and g < 105 and b < 105 and r - max(g, b) > 55:
                red_pixels += 1

        self.assertGreater(red_pixels, 80)
        self.assertLess(red_pixels, 500)

    def test_certificate_is_laid_flat_on_the_lower_tabletop_area(self):
        product = {
            "name": "智枫保温杯",
            "brand": "智枫",
            "model": "ZF-CUP-800",
            "specs": [{"key": "容量", "value": "800", "unit": "ml"}],
        }
        project = {
            "barcode_type": "EAN_13",
            "barcode_value": "4006381333931",
            "certificate_config": {"production_date": "2026-07-27", "inspector": "QC-01"},
        }
        paste_calls: list[tuple[tuple[int, int], tuple[int, int]]] = []
        original_paste = real_image._paste_rgba_plain

        def capture_paste(base, overlay, xy):
            paste_calls.append((xy, overlay.size))
            return original_paste(base, overlay, xy)

        real_image._paste_rgba_plain = capture_paste
        try:
            _compose_certificate(Image.new("RGB", (800, 800), "white"), product, project, "C:/Windows/Fonts/msyh.ttc")
        finally:
            real_image._paste_rgba_plain = original_paste

        self.assertTrue(paste_calls)
        (x, y), (width, height) = paste_calls[-1]
        self.assertGreaterEqual(x, 95)
        self.assertLessEqual(x, 105)
        self.assertGreaterEqual(y, 405)
        self.assertLessEqual(y, 420)
        self.assertLessEqual(x + width, 440)
        self.assertLessEqual(height, width * 1.05)

    def test_certificate_overlay_uses_tabletop_perspective_not_front_facing_card(self):
        product = {
            "name": "Zhifeng thermos cup",
            "brand": "Zhifeng",
            "model": "ZF-CUP-800",
            "specs": [{"key": "capacity", "value": "800", "unit": "ml"}],
        }
        project = {
            "barcode_type": "EAN_13",
            "barcode_value": "4006381333931",
            "certificate_config": {"production_date": "2026-08-05", "inspector": "QC-01"},
        }
        paste_calls: list[tuple[tuple[int, int], tuple[int, int]]] = []
        original_paste = real_image._paste_rgba_plain

        def capture_paste(base, overlay, xy):
            paste_calls.append((xy, overlay.size))
            return original_paste(base, overlay, xy)

        real_image._paste_rgba_plain = capture_paste
        try:
            _compose_certificate(Image.new("RGB", (800, 800), "white"), product, project, "C:/Windows/Fonts/msyh.ttc")
        finally:
            real_image._paste_rgba_plain = original_paste

        self.assertTrue(paste_calls)
        (x, y), (width, height) = paste_calls[-1]
        self.assertGreaterEqual(x, 95)
        self.assertLessEqual(x, 105)
        self.assertGreaterEqual(y, 405)
        self.assertLessEqual(y, 420)
        self.assertGreaterEqual(width, 260)
        self.assertLessEqual(width, 340)
        self.assertLessEqual(x + width, 440)
        self.assertLessEqual(height, width * 1.05)
        self.assertGreaterEqual(y + height, 605)
        self.assertLessEqual(y + height, 645)

    def test_certificate_overlay_is_horizontal_not_portrait(self):
        card = Image.new("RGBA", (360, 190), (250, 249, 244, 255))
        overlay = _flatten_certificate_for_tabletop(card)
        alpha = overlay.getchannel("A")
        xs: list[int] = []
        ys: list[int] = []
        for y in range(alpha.height):
            for x in range(alpha.width):
                if alpha.getpixel((x, y)) > 10:
                    xs.append(x)
                    ys.append(y)

        self.assertTrue(xs)
        width = max(xs) - min(xs) + 1
        height = max(ys) - min(ys) + 1

        self.assertGreaterEqual(width, height * 1.45)
        self.assertLessEqual(height, 210)

    def test_flattened_certificate_has_no_low_alpha_fuzzy_edge(self):
        card = Image.new("RGBA", (360, 190), (250, 249, 244, 255))
        overlay = _flatten_certificate_for_tabletop(card)
        alpha = overlay.getchannel("A")

        fuzzy_pixels = 0
        for value in alpha.tobytes():
            if 0 < value < 96:
                fuzzy_pixels += 1

        self.assertEqual(fuzzy_pixels, 0)

    def test_flattened_certificate_matches_reference_tabletop_perspective(self):
        card = Image.new("RGBA", (235, 315), (250, 249, 244, 255))
        overlay = _flatten_certificate_for_tabletop(card)
        alpha = overlay.getchannel("A")

        def widest_span(y_start: int, y_end: int) -> int:
            widest = 0
            for row in range(y_start, y_end):
                xs = [x for x in range(alpha.width) if alpha.getpixel((x, row)) > 10]
                if xs:
                    widest = max(widest, max(xs) - min(xs) + 1)
            return widest

        far_edge_width = widest_span(0, overlay.height // 3)
        near_edge_width = widest_span((overlay.height * 2) // 3, overlay.height)

        self.assertGreaterEqual(near_edge_width - far_edge_width, 32)
        self.assertLessEqual(near_edge_width - far_edge_width, 60)

    def test_certificate_has_no_backend_shadow_on_the_tabletop_plane(self):
        product = {
            "name": "Zhifeng thermos cup",
            "brand": "Zhifeng",
            "model": "ZF-CUP-800",
            "specs": [{"key": "capacity", "value": "800", "unit": "ml"}],
        }
        project = {
            "barcode_type": "EAN_13",
            "barcode_value": "4006381333931",
            "certificate_config": {"production_date": "2026-08-05", "inspector": "QC-01"},
        }
        image = Image.new("RGB", (800, 800), "white")

        _compose_certificate(image, product, project, "C:/Windows/Fonts/msyh.ttc")

        for point in ((80, 600), (430, 600), (425, 525), (250, 635)):
            self.assertEqual(image.getpixel(point), (255, 255, 255), point)

    def test_tabletop_paper_paste_does_not_add_shadow(self):
        image = Image.new("RGB", (220, 180), "white")
        overlay = Image.new("RGBA", (100, 50), (250, 249, 244, 255))

        _paste_tabletop_paper(image, overlay, (50, 50))

        self.assertEqual(image.getpixel((150, 100)), (255, 255, 255))
        self.assertEqual(image.getpixel((154, 104)), (255, 255, 255))

    def test_certificate_shadow_does_not_create_dirty_fuzzy_card_edges(self):
        product = {
            "name": "Zhifeng thermos cup",
            "brand": "Zhifeng",
            "model": "ZF-CUP-800",
            "specs": [{"key": "capacity", "value": "800", "unit": "ml"}],
        }
        project = {
            "barcode_type": "EAN_13",
            "barcode_value": "4006381333931",
            "certificate_config": {"production_date": "2026-08-05", "inspector": "QC-01"},
        }
        image = Image.new("RGB", (800, 800), "white")

        _compose_certificate(image, product, project, "C:/Windows/Fonts/msyh.ttc")

        for point in ((130, 735), (410, 748), (430, 735)):
            pixel = image.getpixel(point)
            self.assertTrue(all(channel >= 247 for channel in pixel), (point, pixel))

    def test_certificate_overlay_stays_on_the_tabletop_plane(self):
        product = {
            "name": "智枫保温杯",
            "brand": "智枫",
            "model": "ZF-CUP-800",
            "specs": [{"key": "容量", "value": "800", "unit": "ml"}],
        }
        project = {
            "barcode_type": "EAN_13",
            "barcode_value": "4006381333931",
            "certificate_config": {"production_date": "2026-07-27", "inspector": "QC-01"},
        }
        paste_calls: list[tuple[tuple[int, int], tuple[int, int]]] = []
        original_paste = real_image._paste_rgba_plain

        def capture_paste(base, overlay, xy):
            paste_calls.append((xy, overlay.size))
            return original_paste(base, overlay, xy)

        real_image._paste_rgba_plain = capture_paste
        try:
            _compose_certificate(Image.new("RGB", (800, 800), "white"), product, project, "C:/Windows/Fonts/msyh.ttc")
        finally:
            real_image._paste_rgba_plain = original_paste

        self.assertTrue(paste_calls)
        (x, y), (width, height) = paste_calls[-1]
        self.assertGreaterEqual(y + height, 605)
        self.assertLessEqual(y + height, 645)
        self.assertLessEqual(x + width, 440)

    def test_detail_page_does_not_render_barcode(self):
        product = {
            "name": "智枫保温杯",
            "brand": "智枫",
            "model": "ZF-CUP-800",
            "material": "不锈钢",
            "color": "银色",
            "description": "双层不锈钢保温杯，适合日常通勤、门店陈列和电商详情页展示。",
            "specs": [{"key": "容量", "value": "800", "unit": "ml"}],
        }
        project = {
            "barcode_type": "EAN_13",
            "barcode_value": "4006381333931",
            "detail_config": {"selling_points": ["保温", "易清洁", "耐用"]},
        }
        sources = [Image.new("RGB", (800, 800), color) for color in ("white", "#eef2f7", "#e2e8f0", "#f8fafc")]

        original = real_image.render_barcode_image
        real_image.render_barcode_image = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("detail page must not render barcode"))
        try:
            image = _build_detail_page(sources, product, project, "C:/Windows/Fonts/msyh.ttc")
        finally:
            real_image.render_barcode_image = original

        self.assertEqual(image.size, (800, 3200))

    def test_detail_page_does_not_add_backend_text(self):
        product = {"name": "智枫保温杯", "brand": "智枫", "model": "ZF-CUP-800"}
        project = {"detail_config": {"selling_points": ["保温", "易清洁", "耐用"]}}
        sources = [Image.new("RGB", (800, 800), color) for color in ("#111111", "#222222", "#333333", "#444444")]
        original_text = ImageDraw.ImageDraw.text

        def forbid_text(*_args, **_kwargs):
            raise AssertionError("detail page must only stitch generated images")

        ImageDraw.ImageDraw.text = forbid_text
        try:
            image = _build_detail_page(sources, product, project, "C:/Windows/Fonts/msyh.ttc")
        finally:
            ImageDraw.ImageDraw.text = original_text

        self.assertEqual(image.size, (800, 3200))

    def test_package_prompt_forbids_front_frame_and_side_markings(self):
        product = {
            "name": "智枫保温杯",
            "brand": "智枫",
            "model": "ZF-CUP-800",
            "material": "不锈钢",
            "specs": [{"key": "容量", "value": "800", "unit": "ml"}],
        }
        project = {"barcode_type": "EAN_13", "barcode_value": "6903244675147"}

        prompt = _prompt_for("package", product, project)

        self.assertIn("designed retail packaging, not an oversized shipping package", prompt)
        self.assertIn("no unnecessary artificial printed border", prompt)
        self.assertIn("unless that border style comes from the package reference", prompt)
        self.assertIn("side face should stay visually simple", prompt)
        self.assertIn("no random unrelated side icons", prompt)
        self.assertIn("normal product-appropriate retail package style", prompt)
        self.assertIn("directly print the package text and barcode on the package surface", prompt)
        self.assertIn("no unrelated product facts", prompt)
        self.assertIn("no invented labels", prompt)
        self.assertNotIn("向上", prompt)
        self.assertNotIn("防潮", prompt)
        self.assertIn("avoid unrelated warning symbols", prompt)

    def test_package_prompt_sends_formal_package_information_to_model(self):
        product = {
            "name": "智枫保温杯",
            "brand": "智枫",
            "model": "ZF-CUP-800",
            "material": "不锈钢",
            "specs": [{"key": "容量", "value": "800", "unit": "ml"}],
        }
        project = {
            "barcode_type": "EAN_13",
            "barcode_value": "4006381333931",
            "package_config": {
                "manufacturer_name": "智枫科技",
                "manufacturer_address": "浙江省杭州市西湖区智枫路88号",
            },
        }

        prompt = _prompt_for("package", product, project)

        self.assertIn("directly print the package text and barcode on the package surface", prompt)
        self.assertIn("Standalone package brand wordmark text: 智枫", prompt)
        self.assertIn("brand value only", prompt)
        self.assertIn("large standalone brand wordmark", prompt)
        self.assertNotIn("brand: 智枫", prompt)
        self.assertIn("product name: 智枫保温杯", prompt)
        self.assertIn("specification model: ZF-CUP-800", prompt)
        self.assertIn("manufacturer: 智枫科技", prompt)
        self.assertIn("address: 浙江省杭州市西湖区智枫路88号", prompt)
        self.assertIn("barcode type: EAN_13", prompt)
        self.assertIn("barcode digits: 4006381333931", prompt)
        self.assertNotIn("品牌：智枫", prompt)
        self.assertIn("品名：智枫保温杯", prompt)
        self.assertIn("规格型号：ZF-CUP-800", prompt)
        self.assertNotIn("材质：不锈钢", prompt)
        self.assertIn("生产厂家：智枫科技", prompt)
        self.assertIn("地址：浙江省杭州市西湖区智枫路88号", prompt)
        self.assertNotIn("specification:", prompt)
        self.assertNotIn("规格：", prompt)
        self.assertIn("no garbled characters, no pseudo text, no random English replacement words", prompt)
        self.assertIn("barcode digits must be clear, regular weight, and not bold", prompt)
        self.assertIn("barcode digits must not be missing, truncated, omitted, substituted, reordered, or incomplete", prompt)
        self.assertIn("not bold, not blurry, not thickened, not smeared", prompt)
        self.assertIn("no malformed barcode shape, no broken barcode structure, no decorative fake barcode shape", prompt)
        self.assertIn("first digit outside the barcode bars on the left", prompt)
        self.assertIn("start guard two bars, center guard two bars before the eighth digit, and end guard two bars are the longest", prompt)
        self.assertIn("bars must vary naturally in width and height like a real EAN retail barcode", prompt)
        self.assertIn("side information zone reasonably visible to the camera", prompt)
        self.assertIn("stable enough for readable package printing", prompt)
        self.assertIn("no excessive convergence, twisted panels, or unreadable perspective", prompt)
        self.assertIn("avoid unrelated warning symbols", prompt)

    def test_package_and_detail_prompts_omit_missing_fields_and_placeholders(self):
        product = {
            "name": "蓝牙鼠标",
            "brand": "智枫",
            "model": "ZF-CPU",
            "category": "电脑外设",
            "material": "",
            "color": "",
            "specs": [],
        }
        project = {
            "barcode_type": "EAN_13",
            "barcode_value": "6903244675147",
            "package_config": {
                "manufacturer_name": "智枫科技",
                "manufacturer_address": "吉林省长春市南关区幸福街888号",
            },
        }

        package_prompt = _prompt_for("package", product, project)
        detail_prompts = _detail_module_prompts(product)

        self.assertNotIn("未填写", package_prompt)
        self.assertNotIn("规格：", package_prompt)
        self.assertNotIn("材质：", package_prompt)
        self.assertNotIn("color:", package_prompt)
        self.assertIn("Standalone package brand wordmark text: 智枫", package_prompt)
        self.assertNotIn("品牌：智枫", package_prompt)
        self.assertIn("品名：蓝牙鼠标", package_prompt)
        self.assertIn("型号：ZF-CPU", package_prompt)

        for prompt in detail_prompts:
            with self.subTest(prompt=prompt):
                self.assertNotIn("未填写", prompt)
                self.assertNotIn("specs", prompt)
                self.assertIn("Do not render rows, table entries, labels, or placeholder text for absent fields", prompt)
                self.assertIn("must not present inferred values as structured specifications", prompt)

    def test_package_prompt_uses_real_resting_pose_not_generic_upright_logic(self):
        prompt = _prompt_for(
            "package",
            {
                "name": "蓝牙鼠标",
                "brand": "智枫",
                "model": "ZF-CPU",
                "category": "电脑外设",
            },
            {"barcode_type": "EAN_13", "barcode_value": "6903244675147"},
        )

        self.assertIn("real-world normal use orientation", prompt)
        self.assertIn("normal resting orientation", prompt)
        self.assertIn("designed functional contact surface", prompt)
        self.assertIn("Physical realism has absolute priority", prompt)
        self.assertIn("This package orientation rule applies only to the package", prompt)
        self.assertIn("not by rotating the product upright toward the camera", prompt)
        self.assertIn("A broad surface alone is not permission to stand the product upright", prompt)
        self.assertIn("Do not rotate, stand, lean, prop up, or balance the product just to show more of the product", prompt)
        self.assertIn("normally flat tabletop product", prompt)
        self.assertIn("The product may occupy more horizontal tabletop area", prompt)
        self.assertIn("less visually prominent", prompt)
        self.assertIn("Do not preserve the uploaded source image's exact 2D silhouette", prompt)
        self.assertIn("Re-project the product into its physically natural tabletop pose", prompt)
        self.assertNotIn("Preserve the exact product silhouette", prompt)
        self.assertNotIn("uploaded product geometry is a locked structural reference", prompt)
        self.assertNotIn("complete outer silhouettes", prompt)
        self.assertNotIn("complete feature visibility", prompt)
        self.assertNotIn("normal top/use side must face naturally upward or toward the camera", prompt)

    def test_package_backend_printing_stays_inside_carton_front_face(self):
        product = {
            "name": "智枫保温杯",
            "brand": "智枫",
            "model": "ZF-CUP-800",
            "material": "不锈钢",
            "specs": [{"key": "容量", "value": "800", "unit": "ml"}],
        }
        project = {"barcode_type": "EAN_13", "barcode_value": "6903244675147"}
        paste_calls: list[tuple[tuple[int, int], tuple[int, int]]] = []
        original = real_image._paste_printed_label

        def capture_paste(image, label, xy):
            paste_calls.append((xy, label.size))
            return original(image, label, xy)

        real_image._paste_printed_label = capture_paste
        try:
            _compose_package_label(Image.new("RGB", (800, 800), "white"), product, project, "C:/Windows/Fonts/msyh.ttc")
        finally:
            real_image._paste_printed_label = original

        self.assertTrue(paste_calls)
        (x, _y), (width, _height) = paste_calls[-1]
        self.assertGreaterEqual(x, 190)
        self.assertLessEqual(x + width, 430)

    def test_package_backend_barcode_is_realistic_size_with_lighter_digits(self):
        product = {
            "name": "智枫保温杯",
            "brand": "智枫",
            "model": "ZF-CUP-800",
            "material": "不锈钢",
            "specs": [{"key": "容量", "value": "800", "unit": "ml"}],
        }
        project = {"barcode_type": "EAN_13", "barcode_value": "6903244675147"}
        calls: list[dict[str, object]] = []
        original = real_image.render_barcode_image

        def capture_barcode(*args, **kwargs):
            calls.append(kwargs)
            return original(*args, **kwargs)

        real_image.render_barcode_image = capture_barcode
        try:
            _compose_package_label(Image.new("RGB", (800, 800), "white"), product, project, "C:/Windows/Fonts/msyh.ttc")
        finally:
            real_image.render_barcode_image = original

        self.assertTrue(calls)
        self.assertGreaterEqual(calls[-1]["width"], 232)
        self.assertLessEqual(calls[-1]["width"], 238)
        self.assertGreaterEqual(calls[-1]["height"], 102)
        self.assertLessEqual(calls[-1]["height"], 108)

    def test_package_printed_label_canvas_contains_full_retail_code(self):
        product = {
            "name": "Thermos cup",
            "brand": "Zhifeng",
            "model": "ZF-CUP-800",
            "material": "stainless steel",
            "specs": [{"key": "capacity", "value": "800", "unit": "ml"}],
        }
        project = {"barcode_type": "EAN_13", "barcode_value": "6903244675147"}
        barcode_calls: list[dict[str, object]] = []
        paste_calls: list[tuple[tuple[int, int], tuple[int, int]]] = []
        original_barcode = real_image.render_barcode_image
        original_paste = real_image._paste_printed_label

        def capture_barcode(*args, **kwargs):
            barcode_calls.append(kwargs)
            return original_barcode(*args, **kwargs)

        def capture_paste(image, label, xy):
            paste_calls.append((xy, label.size))
            return original_paste(image, label, xy)

        real_image.render_barcode_image = capture_barcode
        real_image._paste_printed_label = capture_paste
        try:
            _compose_package_label(Image.new("RGB", (800, 800), "white"), product, project, "C:/Windows/Fonts/msyh.ttc")
        finally:
            real_image.render_barcode_image = original_barcode
            real_image._paste_printed_label = original_paste

        self.assertTrue(barcode_calls)
        self.assertTrue(paste_calls)
        (_x, _y), (label_width, _label_height) = paste_calls[-1]
        self.assertGreaterEqual(label_width, barcode_calls[-1]["width"])

    def test_package_barcode_tint_keeps_digits_lightweight_not_bold(self):
        barcode = Image.new("RGBA", (8, 8), (255, 255, 255, 0))
        draw = ImageDraw.Draw(barcode)
        draw.rectangle((1, 1, 6, 6), fill=(0, 0, 0, 255))

        _tint_barcode_for_box(barcode)

        self.assertLessEqual(barcode.getpixel((2, 2))[3], 220)
        self.assertGreaterEqual(barcode.getpixel((2, 2))[3], 205)

    def test_package_printed_label_blends_as_carton_ink_not_hard_overlay(self):
        base = Image.new("RGB", (40, 40), (192, 151, 101))
        label = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
        ImageDraw.Draw(label).rectangle((5, 5, 14, 14), fill=(28, 32, 30, 255))

        real_image._paste_printed_label(base, label, (10, 10))

        r, g, b = base.getpixel((18, 18))
        self.assertGreaterEqual(r, 45)
        self.assertGreaterEqual(g, 40)
        self.assertGreaterEqual(b, 35)

    def test_package_printed_label_ink_follows_underlying_carton_tone(self):
        base = Image.new("RGB", (40, 20), (210, 170, 110))
        draw = ImageDraw.Draw(base)
        draw.rectangle((20, 0, 39, 19), fill=(160, 120, 80))
        label = Image.new("RGBA", (30, 12), (0, 0, 0, 0))
        ImageDraw.Draw(label).rectangle((0, 0, 29, 11), fill=(28, 32, 30, 255))

        real_image._paste_printed_label(base, label, (5, 4))

        light_side = base.getpixel((10, 8))[0]
        dark_side = base.getpixel((25, 8))[0]
        self.assertGreater(light_side, dark_side)
        self.assertGreaterEqual(light_side - dark_side, 14)

    def test_detail_page_stitches_four_generated_images(self):
        product = {
            "name": "智枫保温杯",
            "brand": "智枫",
            "model": "ZF-CUP-800",
            "material": "不锈钢",
            "color": "银色",
            "description": "双层不锈钢保温杯，适合日常通勤、门店陈列和电商详情页展示。",
            "specs": [{"key": "容量", "value": "800", "unit": "ml"}],
        }
        project = {"detail_config": {"selling_points": ["保温", "易清洁", "耐用"]}}
        sources = [
            Image.new("RGB", (800, 500), "#ffffff"),
            Image.new("RGB", (800, 700), "#ff0000"),
            Image.new("RGB", (800, 900), "#00ff00"),
            Image.new("RGB", (800, 600), "#0000ff"),
        ]

        image = _build_detail_page(sources, product, project, "C:/Windows/Fonts/msyh.ttc")

        self.assertEqual(image.size, (800, 2700))
        self.assertEqual(image.getpixel((400, 250)), (255, 255, 255))
        self.assertEqual(image.getpixel((400, 850)), (255, 0, 0))
        self.assertEqual(image.getpixel((400, 1650)), (0, 255, 0))
        self.assertEqual(image.getpixel((400, 2400)), (0, 0, 255))

    def test_detail_page_uses_the_fourth_generated_image_at_the_bottom(self):
        product = {
            "name": "智枫保温杯",
            "brand": "智枫",
            "model": "ZF-CUP-800",
            "material": "不锈钢",
            "color": "银色",
            "description": "这段文字不应出现在详情图底部。",
            "specs": [{"key": "容量", "value": "800", "unit": "ml"}],
        }
        project = {"detail_config": {"selling_points": ["保温", "易清洁", "耐用"]}}
        sources = [Image.new("RGB", (800, 800), "#ffffff") for _ in range(4)]

        image = _build_detail_page(sources, product, project, "C:/Windows/Fonts/msyh.ttc")

        self.assertEqual(image.size, (800, 3200))
        self.assertEqual(image.getpixel((52, 2870)), (255, 255, 255))
        self.assertEqual(image.getpixel((72, 2870)), (255, 255, 255))

    def test_package_generation_does_not_add_backend_printed_label_after_model_image(self):
        class FakeProvider:
            def edit_image(self, *, prompt, size, image_paths):
                image = Image.new("RGB", (1024, 1024), "#ffffff")
                buffer = BytesIO()
                image.save(buffer, format="PNG")
                return buffer.getvalue()

        provider = FakeProvider()
        pipeline = KeleFiveImagePipeline(provider, font_path="C:/Windows/Fonts/msyh.ttc")
        product = {
            "name": "智枫保温杯",
            "brand": "智枫",
            "model": "ZF-CUP-800",
            "category": "日用品",
            "specs": [{"key": "容量", "value": "800", "unit": "ml"}],
        }
        project = {"barcode_type": "EAN_13", "barcode_value": "6903244675147"}
        original_compose = real_image._compose_package_label
        calls: list[str] = []

        def capture_compose(*_args, **_kwargs):
            calls.append("composed")

        real_image._compose_package_label = capture_compose
        try:
            with TemporaryDirectory() as tmp:
                source = Path(tmp) / "source.png"
                Image.new("RGB", (800, 800), "white").save(source)
                pipeline.generate_five_images(
                    output_dir=Path(tmp),
                    job_id="job",
                    product=product,
                    project=project,
                    source_image_path=source,
                )
        finally:
            real_image._compose_package_label = original_compose

        self.assertEqual(calls, [])

    def test_detail_output_requests_separate_visual_modules_before_stitching(self):
        class FakeProvider:
            def __init__(self):
                self.prompts: list[str] = []

            def edit_image(self, *, prompt, size, image_paths):
                self.prompts.append(prompt)
                image = Image.new("RGB", (800, 800), (240 - len(self.prompts) * 10, 245, 250))
                buffer = BytesIO()
                image.save(buffer, format="PNG")
                return buffer.getvalue()

        provider = FakeProvider()
        pipeline = KeleFiveImagePipeline(provider, font_path="C:/Windows/Fonts/msyh.ttc")
        product = {
            "name": "智枫保温杯",
            "brand": "智枫",
            "model": "ZF-CUP-800",
            "category": "日用品",
            "specs": [{"key": "容量", "value": "800", "unit": "ml"}],
        }
        project = {
            "barcode_type": "EAN_13",
            "barcode_value": "4006381333931",
            "detail_config": {"selling_points": ["保温", "便携", "耐用"]},
        }

        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.png"
            Image.new("RGB", (800, 800), "white").save(source)
            outputs = pipeline.generate_five_images(
                output_dir=Path(tmp),
                job_id="job",
                product=product,
                project=project,
                source_image_path=source,
            )

        self.assertEqual(len(outputs), 5)
        detail_prompts = [prompt for prompt in provider.prompts if "detail module" in prompt]
        self.assertEqual(len(detail_prompts), len(_detail_module_prompts(product)))
        self.assertEqual(len(detail_prompts), 4)
        self.assertTrue(any("product hero" in prompt for prompt in detail_prompts))
        self.assertTrue(any("product-only feature section" in prompt for prompt in detail_prompts))
        self.assertFalse(any("usage scene" in prompt for prompt in detail_prompts))
        self.assertFalse(any("daily use" in prompt for prompt in detail_prompts))
        self.assertTrue(any("close-up detail" in prompt for prompt in detail_prompts))
        self.assertFalse(any("close-up detail 2" in prompt for prompt in detail_prompts))
        self.assertTrue(any("structure and scale visual reference" in prompt for prompt in detail_prompts))
        self.assertTrue(all("finished ecommerce detail section" in prompt for prompt in detail_prompts))

    def test_provider_edit_size_can_differ_from_final_output_size(self):
        class FakeProvider:
            def __init__(self):
                self.sizes: list[str] = []

            def edit_image(self, *, prompt, size, image_paths):
                self.sizes.append(size)
                image = Image.new("RGB", (1024, 1024), "#f8fafc")
                buffer = BytesIO()
                image.save(buffer, format="PNG")
                return buffer.getvalue()

        provider = FakeProvider()
        pipeline = KeleFiveImagePipeline(provider, font_path="C:/Windows/Fonts/msyh.ttc", edit_size="1024x1024")
        product = {
            "name": "智枫保温杯",
            "brand": "智枫",
            "model": "ZF-CUP-800",
            "category": "日用品",
            "specs": [{"key": "容量", "value": "800", "unit": "ml"}],
        }
        project = {
            "barcode_type": "EAN_13",
            "barcode_value": "4006381333931",
            "certificate_config": {"production_date": "2026-07-27", "inspector": "QC-01"},
            "detail_config": {"selling_points": ["保温", "易清洁", "耐用"]},
        }

        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.png"
            Image.new("RGB", (800, 800), "white").save(source)
            outputs = pipeline.generate_five_images(
                output_dir=Path(tmp),
                job_id="job",
                product=product,
                project=project,
                source_image_path=source,
            )

            file_sizes = {}
            for output in outputs:
                with Image.open(output.path) as generated:
                    file_sizes[output.output_type] = generated.size

        self.assertEqual(set(provider.sizes), {"1024x1024"})
        self.assertEqual(file_sizes["main"], (800, 800))
        self.assertEqual(file_sizes["certificate"], (800, 800))
        self.assertEqual(file_sizes["package"], (800, 800))
        self.assertEqual(file_sizes["scene"], (800, 800))
        self.assertEqual(file_sizes["detail"], (800, 3200))

    def test_main_and_package_do_not_whiten_light_gray_product_surfaces(self):
        class FakeProvider:
            def edit_image(self, *, prompt, size, image_paths):
                image = Image.new("RGB", (800, 800), "white")
                draw = ImageDraw.Draw(image)
                draw.rectangle((260, 260, 540, 540), fill=(218, 218, 216))
                draw.rectangle((330, 330, 470, 470), fill=(185, 185, 183))
                buffer = BytesIO()
                image.save(buffer, format="PNG")
                return buffer.getvalue()

        provider = FakeProvider()
        pipeline = KeleFiveImagePipeline(provider, font_path="C:/Windows/Fonts/msyh.ttc", edit_size="1024x1024")
        product = {
            "name": "智枫蓝牙耳机",
            "brand": "智枫",
            "model": "ZF-CUP-800",
            "category": "蓝牙耳机",
        }
        project = {
            "barcode_type": "EAN_13",
            "barcode_value": "4006381333931",
            "detail_config": {"selling_points": ["降噪", "舒适", "长续航"]},
        }

        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.png"
            Image.new("RGB", (800, 800), "white").save(source)
            outputs = pipeline.generate_five_images(
                output_dir=Path(tmp),
                job_id="job",
                product=product,
                project=project,
                source_image_path=source,
            )

            output_paths = {output.output_type: output.path for output in outputs}
            for output_type in ("main", "package"):
                with self.subTest(output_type=output_type):
                    with Image.open(output_paths[output_type]) as generated:
                        image = generated.convert("RGB")
                        self.assertEqual(image.getpixel((300, 300)), (218, 218, 216))
                        self.assertEqual(image.getpixel((400, 400)), (185, 185, 183))


if __name__ == "__main__":
    unittest.main()
