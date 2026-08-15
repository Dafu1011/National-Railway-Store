from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps


OUTPUT_SPECS: tuple[tuple[str, int, int], ...] = (
    ("main", 800, 800),
    ("certificate", 800, 800),
    ("package", 800, 800),
    ("detail", 800, 2400),
    ("scene", 800, 800),
)


@dataclass(frozen=True)
class GeneratedMockImage:
    output_type: str
    width: int
    height: int
    path: Path


class MockImageProvider:
    name = "mock"
    model = "mock-gpt-image-2-compatible"

    def generate_five_images(
        self,
        *,
        output_dir: Path,
        job_id: str,
        product: dict[str, Any],
        project: dict[str, Any],
        source_image_path: Path | None = None,
    ) -> list[GeneratedMockImage]:
        job_dir = output_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        generated: list[GeneratedMockImage] = []

        for output_type, width, height in OUTPUT_SPECS:
            image = self._render_image(output_type, width, height, product, project, source_image_path)
            path = job_dir / f"{output_type}.png"
            image.save(path, format="PNG")
            generated.append(GeneratedMockImage(output_type=output_type, width=width, height=height, path=path))

        return generated

    def _render_image(
        self,
        output_type: str,
        width: int,
        height: int,
        product: dict[str, Any],
        project: dict[str, Any],
        source_image_path: Path | None,
    ) -> Image.Image:
        background = "white" if output_type in {"main", "certificate", "package"} else (245, 247, 250)
        image = Image.new("RGB", (width, height), background)
        draw = ImageDraw.Draw(image)
        font_title = _font(34)
        font_body = _font(22)
        font_small = _font(16)

        source = _load_source_image(source_image_path)

        if output_type == "main":
            if source is not None:
                _paste_source_image(image, source, (150, 130, 650, 670))
            else:
                _draw_product(draw, width, height, product, with_text=False)
        elif output_type == "certificate":
            if source is not None:
                _paste_source_image(image, source, (55, 160, 385, 620))
            else:
                _draw_product(draw, width, height, product, offset_x=-150, with_text=False)
            _draw_certificate(draw, width, height, product, project, font_title, font_body, font_small)
        elif output_type == "package":
            if source is not None:
                _paste_source_image(image, source, (48, 260, 330, 655))
            else:
                _draw_product(draw, width, height, product, offset_x=-170, offset_y=70, scale=0.78, with_text=False)
            _draw_package(draw, width, height, product, project, font_title, font_body, font_small)
        elif output_type == "detail":
            _draw_detail_page(draw, width, height, product, project, font_title, font_body, font_small)
            if source is not None:
                _paste_source_image(image, source, (470, 102, 720, 350))
        else:
            _draw_scene(draw, width, height, product, font_title, font_body)
            if source is not None:
                _paste_source_image(image, source, (245, 205, 555, 635))

        return image


def _font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _load_source_image(source_image_path: Path | None) -> Image.Image | None:
    if source_image_path is None or not source_image_path.exists():
        return None
    with Image.open(source_image_path) as source:
        return ImageOps.exif_transpose(source).convert("RGB")


def _paste_source_image(canvas: Image.Image, source: Image.Image, box: tuple[int, int, int, int]) -> None:
    max_width = box[2] - box[0]
    max_height = box[3] - box[1]
    contained = ImageOps.contain(source, (max_width, max_height))
    x = box[0] + (max_width - contained.width) // 2
    y = box[1] + (max_height - contained.height) // 2
    canvas.paste(contained, (x, y))


def _draw_product(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    product: dict[str, Any],
    *,
    offset_x: int = 0,
    offset_y: int = 0,
    scale: float = 1.0,
    with_text: bool = True,
) -> None:
    box_w = int(330 * scale)
    box_h = int(460 * scale)
    x0 = width // 2 - box_w // 2 + offset_x
    y0 = min(height - box_h - 70, max(110, height // 2 - box_h // 2 + offset_y))
    x1 = x0 + box_w
    y1 = y0 + box_h
    draw.rounded_rectangle((x0, y0, x1, y1), radius=42, fill=(225, 231, 235), outline=(31, 41, 55), width=4)
    draw.rounded_rectangle((x0 + 70, y0 - 45, x1 - 70, y0 + 55), radius=32, fill=(203, 213, 225), outline=(31, 41, 55), width=3)
    draw.ellipse((x0 + 60, y0 + 95, x1 - 60, y0 + 285), fill=(248, 250, 252), outline=(100, 116, 139), width=3)
    if with_text:
        draw.text((x0, y1 + 20), product.get("name", "商品"), fill=(15, 23, 42), font=_font(24))


def _draw_certificate(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    product: dict[str, Any],
    project: dict[str, Any],
    font_title: ImageFont.ImageFont,
    font_body: ImageFont.ImageFont,
    font_small: ImageFont.ImageFont,
) -> None:
    x0, y0, x1, y1 = 430, 145, 745, 610
    draw.rectangle((x0, y0, x1, y1), fill=(255, 255, 255), outline=(15, 23, 42), width=3)
    draw.text((x0 + 34, y0 + 28), "产品合格证", fill=(15, 23, 42), font=font_title)
    lines = [
        f"品名: {product.get('name', '')}",
        f"品牌: {product.get('brand', '')}",
        f"型号: {product.get('model', '')}",
        "检验: 合格",
    ]
    for index, line in enumerate(lines):
        draw.text((x0 + 24, y0 + 100 + index * 42), line[:18], fill=(15, 23, 42), font=font_body)
    _draw_barcode(draw, x0 + 38, y1 - 128, project["barcode_value"], font_small)


def _draw_package(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    product: dict[str, Any],
    project: dict[str, Any],
    font_title: ImageFont.ImageFont,
    font_body: ImageFont.ImageFont,
    font_small: ImageFont.ImageFont,
) -> None:
    x0, y0, x1, y1 = 365, 185, 745, 590
    draw.polygon([(x0, y0 + 65), (x0 + 70, y0), (x1, y0 + 58), (x1 - 68, y1), (x0, y1 - 42)], fill=(205, 173, 123), outline=(92, 64, 51))
    label = (x0 + 64, y0 + 105, x1 - 45, y0 + 315)
    draw.rectangle(label, fill=(255, 255, 255), outline=(92, 64, 51), width=2)
    draw.text((label[0] + 18, label[1] + 18), product.get("brand", "智枫"), fill=(15, 23, 42), font=font_title)
    draw.text((label[0] + 18, label[1] + 65), product.get("model", ""), fill=(15, 23, 42), font=font_body)
    _draw_barcode(draw, label[0] + 18, label[1] + 112, project["barcode_value"], font_small)


def _draw_detail_page(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    product: dict[str, Any],
    project: dict[str, Any],
    font_title: ImageFont.ImageFont,
    font_body: ImageFont.ImageFont,
    font_small: ImageFont.ImageFont,
) -> None:
    sections = [
        ("商品首屏", product.get("name", "")),
        ("使用场景", "适合日常、仓储、门店陈列和电商详情展示。"),
        ("商品细节", f"材质: {product.get('material', '')}  颜色: {product.get('color', '')}"),
        ("规格尺寸", _spec_text(product)),
        ("条形码信息", f"{project['barcode_type']} / {project['barcode_value']}"),
    ]
    y = 70
    for title, body in sections:
        draw.rounded_rectangle((48, y, width - 48, y + 390), radius=18, fill=(255, 255, 255), outline=(203, 213, 225), width=2)
        draw.text((82, y + 34), title, fill=(15, 23, 42), font=font_title)
        draw.text((82, y + 96), body[:44], fill=(51, 65, 85), font=font_body)
        if title == "商品首屏":
            _draw_product(draw, width, height, product, offset_y=y - 300, scale=0.55, with_text=False)
        if title == "条形码信息":
            _draw_barcode(draw, 82, y + 160, project["barcode_value"], font_small)
        y += 445


def _draw_scene(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    product: dict[str, Any],
    font_title: ImageFont.ImageFont,
    font_body: ImageFont.ImageFont,
) -> None:
    draw.rectangle((0, 540, width, height), fill=(226, 232, 240))
    draw.rectangle((0, 0, width, 540), fill=(232, 244, 238))
    draw.ellipse((-120, 90, 260, 470), fill=(210, 232, 220))
    draw.ellipse((610, 60, 920, 380), fill=(214, 226, 245))
    _draw_product(draw, width, height, product, with_text=False)
    draw.text((52, 50), "细节实拍模拟图", fill=(15, 23, 42), font=font_title)
    draw.text((52, 96), product.get("name", ""), fill=(51, 65, 85), font=font_body)


def _draw_barcode(draw: ImageDraw.ImageDraw, x: int, y: int, value: str, font: ImageFont.ImageFont) -> None:
    draw.rectangle((x, y, x + 230, y + 78), fill=(255, 255, 255), outline=(15, 23, 42), width=1)
    bits = _ean13_bits(value) if len(value) == 13 and value.isdigit() else _fallback_barcode_bits(value)
    module = max(1, min(2, 204 // len(bits)))
    cursor = x + 13
    for bit in bits:
        if bit == "1":
            draw.rectangle((cursor, y + 8, cursor + module - 1, y + 53), fill=(15, 23, 42))
        cursor += module
    draw.text((x + 24, y + 55), value, fill=(15, 23, 42), font=font)


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
    bits = []
    for index in range(95):
        bits.append("1" if (digits[index % len(digits)] + index) % 2 == 0 else "0")
    return "".join(bits)


def _spec_text(product: dict[str, Any]) -> str:
    specs = product.get("specs", [])
    if not specs:
        return "规格信息待补充"
    return " / ".join(f"{item.get('key', '')}: {item.get('value', '')}{item.get('unit', '')}" for item in specs)
