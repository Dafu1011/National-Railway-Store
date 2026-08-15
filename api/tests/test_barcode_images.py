import unittest

from app.rendering.barcode.images import render_barcode_image
from app.rendering.barcode.validators import BarcodeType


class BarcodeImageRenderingTests(unittest.TestCase):
    def test_ean13_draws_first_digit_outside_bars_and_long_guard_bars(self):
        image = render_barcode_image(BarcodeType.EAN_13, "6970997560655", width=260, height=92, draw_border=False)

        first_digit_pixels = _dark_pixels_in_region(image, 4, 70, 34, 90)
        self.assertGreater(first_digit_pixels, 8)

        bar_columns = _dark_columns(image, 0, 62)
        self.assertGreaterEqual(len(bar_columns), 40)
        left_guard_x = min(bar_columns)
        right_guard_x = max(bar_columns)
        middle_columns = [x for x in bar_columns if 112 <= x <= 148]
        self.assertTrue(middle_columns)
        middle_guard_x = middle_columns[len(middle_columns) // 2]

        guard_y = 74
        self.assertTrue(_is_dark(image.getpixel((left_guard_x, guard_y))))
        self.assertTrue(_is_dark(image.getpixel((middle_guard_x, guard_y))))
        self.assertTrue(_is_dark(image.getpixel((right_guard_x, guard_y))))

        normal_bar_x = next(x for x in bar_columns if left_guard_x + 20 <= x <= left_guard_x + 70)
        self.assertFalse(_is_dark(image.getpixel((normal_bar_x, guard_y))))

    def test_ean13_first_digit_is_close_to_left_guard_bars(self):
        image = render_barcode_image(BarcodeType.EAN_13, "6970997560655", width=260, height=92, draw_border=False)

        bar_columns = _dark_columns(image, 0, 62)
        left_guard_x = min(bar_columns)
        first_digit_columns = _dark_columns_in_region(image, 0, 68, left_guard_x, 90)

        self.assertTrue(first_digit_columns)
        self.assertLessEqual(left_guard_x - max(first_digit_columns), 5)


def _dark_columns(image, top: int, bottom: int) -> list[int]:
    columns = []
    for x in range(image.width):
        if any(_is_dark(image.getpixel((x, y))) for y in range(top, bottom)):
            columns.append(x)
    return columns


def _dark_pixels_in_region(image, left: int, top: int, right: int, bottom: int) -> int:
    count = 0
    for y in range(top, bottom):
        for x in range(left, right):
            if _is_dark(image.getpixel((x, y))):
                count += 1
    return count


def _dark_columns_in_region(image, left: int, top: int, right: int, bottom: int) -> list[int]:
    columns = []
    for x in range(left, right):
        if any(_is_dark(image.getpixel((x, y))) for y in range(top, bottom)):
            columns.append(x)
    return columns


def _is_dark(pixel) -> bool:
    r, g, b = pixel[:3]
    return r < 80 and g < 80 and b < 80


if __name__ == "__main__":
    unittest.main()
