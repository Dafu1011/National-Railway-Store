from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from PIL import Image, ImageChops, UnidentifiedImageError

from app.providers.kele import KeleGptImage2Provider
from app.providers.single_image import KeleSingleImageProvider, MockSingleImageProvider


def png_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class SingleImageProviderTests(unittest.TestCase):
    def test_both_generation_routes_save_800_square_without_changing_model_request(self):
        for references in ([], [Path("first.png"), Path("second.png")]):
            with self.subTest(references=references), TemporaryDirectory() as tmp:
                provider = Mock(spec=KeleGptImage2Provider)
                raw = png_bytes(Image.new("RGB", (1024, 1024), "navy"))
                provider.generate_image.return_value = raw
                provider.edit_image.return_value = raw
                result = KeleSingleImageProvider(provider).generate_single_image(
                    output_dir=Path(tmp), job_id="job", prompt="用户原始诉求",
                    reference_image_paths=references,
                )

                with Image.open(result.path) as output:
                    self.assertEqual(output.size, (800, 800))
                    self.assertEqual(output.format, "PNG")
                    self.assertEqual(output.mode, "RGB")
                    self.assertEqual(output.getpixel((0, 0)), (0, 0, 128))
                self.assertEqual((result.width, result.height), (800, 800))
                self.assertEqual(result.output_type, "single")
                if references:
                    provider.edit_image.assert_called_once_with(
                        prompt="用户原始诉求", size="1024x1024", image_paths=references,
                    )
                    provider.generate_image.assert_not_called()
                else:
                    provider.generate_image.assert_called_once_with(prompt="用户原始诉求", size="1024x1024")
                    provider.edit_image.assert_not_called()

    def test_non_square_and_small_images_are_contained_and_centered_without_cropping(self):
        cases = (
            ((1600, 800), (0, 200, 800, 600)),
            ((800, 1600), (200, 0, 600, 800)),
            ((320, 160), (0, 200, 800, 600)),
            ((160, 320), (200, 0, 600, 800)),
            ((128, 128), (0, 0, 800, 800)),
            ((1200, 801), (0, 133, 800, 667)),
        )
        for size, content_box in cases:
            with self.subTest(size=size), TemporaryDirectory() as tmp:
                source = Image.new("RGB", size, "navy")
                source.paste("red", (0, 0, size[0] // 4, size[1] // 4))
                source.paste("green", (size[0] * 3 // 4, size[1] * 3 // 4, size[0], size[1]))
                provider = Mock(spec=KeleGptImage2Provider)
                provider.generate_image.return_value = png_bytes(source)
                result = KeleSingleImageProvider(provider, image_size="1536x1024").generate_single_image(
                    output_dir=Path(tmp), job_id="job", prompt="完整保留画面", reference_image_paths=[],
                )

                with Image.open(result.path) as output:
                    self.assertEqual(output.size, (800, 800))
                    self.assertEqual(
                        ImageChops.difference(output, Image.new("RGB", (800, 800), "white")).getbbox(),
                        content_box,
                    )
                    left, top, right, bottom = content_box
                    self.assertEqual(output.getpixel((left + 10, top + 10)), (255, 0, 0))
                    self.assertEqual(output.getpixel((right - 10, bottom - 10)), (0, 128, 0))
                self.assertEqual((result.width, result.height), (800, 800))
                provider.generate_image.assert_called_once_with(prompt="完整保留画面", size="1536x1024")

    def test_existing_800_square_keeps_its_pixels(self):
        source = Image.new("RGB", (800, 800), "navy")
        source.paste("red", (11, 19, 213, 617))
        provider = Mock(spec=KeleGptImage2Provider)
        provider.generate_image.return_value = png_bytes(source)
        with TemporaryDirectory() as tmp:
            result = KeleSingleImageProvider(provider).generate_single_image(
                output_dir=Path(tmp), job_id="job", prompt="保持原图", reference_image_paths=[],
            )
            with Image.open(result.path) as output:
                self.assertEqual(output.size, (800, 800))
                self.assertIsNone(ImageChops.difference(source, output).getbbox())

    def test_jpeg_response_is_saved_as_real_800_png(self):
        raw = BytesIO()
        Image.new("RGB", (1200, 1200), "navy").save(raw, format="JPEG")
        provider = Mock(spec=KeleGptImage2Provider)
        provider.generate_image.return_value = raw.getvalue()
        with TemporaryDirectory() as tmp:
            result = KeleSingleImageProvider(provider).generate_single_image(
                output_dir=Path(tmp), job_id="job", prompt="测试图片格式", reference_image_paths=[],
            )
            with Image.open(result.path) as output:
                self.assertEqual(output.size, (800, 800))
                self.assertEqual(output.format, "PNG")

    def test_unreadable_response_is_rejected_before_final_file_is_written(self):
        provider = Mock(spec=KeleGptImage2Provider)
        provider.generate_image.return_value = b"not-an-image"
        with TemporaryDirectory() as tmp:
            with self.assertRaises(UnidentifiedImageError):
                KeleSingleImageProvider(provider).generate_single_image(
                    output_dir=Path(tmp), job_id="job", prompt="损坏图片", reference_image_paths=[],
                )
            self.assertFalse((Path(tmp) / "single-image" / "job" / "single.png").exists())

    def test_mock_provider_saves_800_square(self):
        with TemporaryDirectory() as tmp:
            result = MockSingleImageProvider().generate_single_image(
                output_dir=Path(tmp), job_id="job", prompt="模拟图片", reference_image_paths=[],
            )
            with Image.open(result.path) as output:
                self.assertEqual(output.size, (800, 800))
                self.assertEqual(output.format, "PNG")
            self.assertEqual((result.width, result.height), (800, 800))


if __name__ == "__main__":
    unittest.main()
