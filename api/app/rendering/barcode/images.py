from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

from app.rendering.barcode.validators import BarcodeType


def render_barcode_image(
    barcode_type: BarcodeType | str,
    value: str,
    *,
    width: int = 260,
    height: int = 92,
    draw_border: bool = True,
    transparent: bool = False,
) -> Image.Image:
    background = (255, 255, 255, 0) if transparent else "white"
    image = Image.new("RGBA" if transparent else "RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    ink = (15, 23, 42, 255) if transparent else (15, 23, 42)
    if draw_border:
        draw.rectangle((0, 0, width - 1, height - 1), outline=ink, width=1)
    if _is_ean13(str(barcode_type), value):
        _draw_ean13(draw, value, width, height, ink)
        return image

    bits = _bits_for(str(barcode_type), value)
    left = 14
    top = 9
    bar_height = max(44, height - 34)
    module = max(1, (width - left * 2) // len(bits))
    cursor = left
    for bit in bits:
        if bit == "1":
            draw.rectangle((cursor, top, cursor + module - 1, top + bar_height), fill=ink)
        cursor += module
    draw.text((max(8, (width - len(value) * 7) // 2), height - 20), value, fill=ink, font=_font(13))
    return image


def _is_ean13(barcode_type: str, value: str) -> bool:
    return barcode_type.endswith("EAN_13") and len(value) == 13 and value.isdigit()


def _draw_ean13(draw: ImageDraw.ImageDraw, value: str, width: int, height: int, ink) -> None:
    bits = _ean13_bits(value)
    module = max(1, (width - 42) // 95)
    total_width = module * 95
    bar_left = max(26, (width - total_width) // 2)
    top = 8
    normal_bottom = height - 27
    guard_bottom = height - 16
    guard_indices = set(range(0, 3)) | set(range(45, 50)) | set(range(92, 95))

    cursor = bar_left
    for index, bit in enumerate(bits):
        if bit == "1":
            bottom = guard_bottom if index in guard_indices else normal_bottom
            draw.rectangle((cursor, top, cursor + module - 1, bottom), fill=ink)
        cursor += module

    font = _font(max(9, min(17, module * 7)))
    digit_top = normal_bottom + 1
    _draw_centered_text(draw, value[0], bar_left - 15, digit_top, 16, font, ink)
    for index, digit in enumerate(value[1:7]):
        x = bar_left + (3 + index * 7) * module
        _draw_centered_text(draw, digit, x, digit_top, 7 * module, font, ink)
    right_start = 50
    for index, digit in enumerate(value[7:]):
        x = bar_left + (right_start + index * 7) * module
        _draw_centered_text(draw, digit, x, digit_top, 7 * module, font, ink)


def _draw_centered_text(draw: ImageDraw.ImageDraw, text: str, x: int, y: int, width: int, font: ImageFont.ImageFont, ink) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    draw.text((x + (width - text_width) // 2, y), text, fill=ink, font=font)


def _bits_for(barcode_type: str, value: str) -> str:
    if _is_ean13(barcode_type, value):
        return _ean13_bits(value)
    if barcode_type.endswith("UPC_A") and len(value) == 12 and value.isdigit():
        return _ean13_bits(f"0{value}")[:95]
    return _fallback_barcode_bits(value)


def _font(size: int) -> ImageFont.ImageFont:
    for candidate in ("C:/Windows/Fonts/consola.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _ean13_bits(value: str) -> str:
    left_odd = {
        "0": "0001101",
        "1": "0011001",
        "2": "0010011",
        "3": "0111101",
        "4": "0100011",
        "5": "0110001",
        "6": "0101111",
        "7": "0111011",
        "8": "0110111",
        "9": "0001011",
    }
    left_even = {
        "0": "0100111",
        "1": "0110011",
        "2": "0011011",
        "3": "0100001",
        "4": "0011101",
        "5": "0111001",
        "6": "0000101",
        "7": "0010001",
        "8": "0001001",
        "9": "0010111",
    }
    right = {
        "0": "1110010",
        "1": "1100110",
        "2": "1101100",
        "3": "1000010",
        "4": "1011100",
        "5": "1001110",
        "6": "1010000",
        "7": "1000100",
        "8": "1001000",
        "9": "1110100",
    }
    parity = {
        "0": "OOOOOO",
        "1": "OOEOEE",
        "2": "OOEEOE",
        "3": "OOEEEO",
        "4": "OEOOEE",
        "5": "OEEOOE",
        "6": "OEEEOO",
        "7": "OEOEOE",
        "8": "OEOEEO",
        "9": "OEEOEO",
    }
    left_digits = value[1:7]
    right_digits = value[7:]
    left_bits = "".join(left_odd[digit] if mode == "O" else left_even[digit] for digit, mode in zip(left_digits, parity[value[0]]))
    right_bits = "".join(right[digit] for digit in right_digits)
    return "101" + left_bits + "01010" + right_bits + "101"


def _fallback_barcode_bits(value: str) -> str:
    digits = [int(char) for char in value if char.isdigit()] or [1, 0, 1, 0]
    return "".join("1" if (digits[index % len(digits)] + index) % 2 == 0 else "0" for index in range(95))
