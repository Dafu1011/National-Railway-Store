import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageChops, ImageDraw

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
        self.assertIn("Do not default to a tall narrow bottle carton", package_prompt)
        self.assertIn("front face nearly parallel to the camera", package_prompt)
        self.assertIn("right-side tabletop when physically possible", package_prompt)
        self.assertIn("pure white background", package_prompt)
        self.assertIn("designed retail packaging, not a plain generic shipping carton", package_prompt)
        self.assertIn("no front rectangular frame", package_prompt)
        self.assertIn("no bordered front panel", package_prompt)
        self.assertIn("plain unmarked side face", package_prompt)
        self.assertIn("no side icons, side logos, side badges, side symbols, or side markings", package_prompt)
        self.assertIn("avoid unrelated warning symbols", package_prompt)
        self.assertIn("model must directly print the package text and barcode on the carton", package_prompt)
        self.assertIn("barcode digits: 6903244675147", package_prompt)
        self.assertIn("manufacturer: 智枫科技", package_prompt)
        self.assertIn("address: 浙江省杭州市西湖区智枫路88号", package_prompt)
        self.assertIn("barcode", package_prompt.lower())
        self.assertIn("subtle real used-photo imperfections", package_prompt)
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
                shadow_pixel = generated.convert("RGB").getpixel((575, 705))

        self.assertEqual(compose_calls, [])
        self.assertEqual(shadow_pixel, (222, 222, 220))

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
        self.assertEqual([label for label, _value in rows], ["品牌", "产品名称", "规格型号", "生产日期", "检验员", "公司名称"])

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

    def test_certificate_template_has_no_red_triangle_stamp(self):
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

        self.assertEqual(red_pixels, 0)

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

        self.assertIn("designed retail packaging, not a plain generic shipping carton", prompt)
        self.assertIn("no front rectangular frame", prompt)
        self.assertIn("no bordered front panel", prompt)
        self.assertIn("plain unmarked side face", prompt)
        self.assertIn("no side icons, side logos, side badges, side symbols, or side markings", prompt)
        self.assertIn("no decorative side graphics", prompt)
        self.assertIn("normal retail carton style", prompt)
        self.assertIn("model must directly print the package text and barcode on the carton", prompt)
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

        self.assertIn("model must directly print the package text and barcode on the carton", prompt)
        self.assertIn("brand: 智枫", prompt)
        self.assertIn("product name: 智枫保温杯", prompt)
        self.assertIn("model: ZF-CUP-800", prompt)
        self.assertIn("manufacturer: 智枫科技", prompt)
        self.assertIn("address: 浙江省杭州市西湖区智枫路88号", prompt)
        self.assertIn("barcode type: EAN_13", prompt)
        self.assertIn("barcode digits: 4006381333931", prompt)
        self.assertIn("品牌：智枫", prompt)
        self.assertIn("品名：智枫保温杯", prompt)
        self.assertIn("型号：ZF-CUP-800", prompt)
        self.assertIn("材质：不锈钢", prompt)
        self.assertIn("厂商：智枫科技", prompt)
        self.assertIn("地址：浙江省杭州市西湖区智枫路88号", prompt)
        self.assertNotIn("specification:", prompt)
        self.assertNotIn("规格：", prompt)
        self.assertIn("no garbled characters, no pseudo text, no random English replacement words", prompt)
        self.assertIn("barcode digits must be clear, regular weight, and not bold", prompt)
        self.assertIn("not bold, not blurry, not thickened, not smeared", prompt)
        self.assertIn("first digit outside the barcode bars on the left", prompt)
        self.assertIn("start guard two bars, center guard two bars before the eighth digit, and end guard two bars are the longest", prompt)
        self.assertIn("bars must vary naturally in width and height like a real EAN retail barcode", prompt)
        self.assertIn("front print zone must be almost square-on to the camera", prompt)
        self.assertIn("carton front must be straight-on enough that model-generated native printing does not look tilted", prompt)
        self.assertIn("avoid perspective that makes upright package text look crooked", prompt)
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
        self.assertIn("品牌：智枫", package_prompt)
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
        self.assertIn("This carton-facing rule applies only to the carton", prompt)
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
