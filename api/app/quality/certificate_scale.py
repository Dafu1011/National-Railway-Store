from dataclasses import dataclass
from typing import Any

from PIL import Image

from app.providers.real_image import _detect_certificate_card_bbox


BULKY_PRODUCT_TOKENS = (
    "大型",
    "机械",
    "设备",
    "机器",
    "车辆",
    "车",
    "扫雪机",
    "清扫机",
    "洗地机",
    "割草机",
    "农机",
    "园林",
    "工具车",
    "家电",
    "家具",
    "健身",
    "machinery",
    "machine",
    "equipment",
    "vehicle",
    "snow blower",
    "sweeper",
    "lawn mower",
    "appliance",
    "furniture",
    "fitness",
)


@dataclass(frozen=True)
class CertificateScaleResult:
    passed: bool
    code: str | None
    message: str | None
    card_bbox: tuple[int, int, int, int] | None
    card_width_ratio: float
    card_height_ratio: float
    card_area_ratio: float
    max_width_ratio: float
    max_area_ratio: float
    is_large_product: bool


def is_large_or_bulky_product(product: dict[str, Any]) -> bool:
    text = " ".join(str(product.get(key, "") or "").lower() for key in ("name", "category", "model", "description"))
    return any(token in text for token in BULKY_PRODUCT_TOKENS)


def inspect_certificate_scale(image: Image.Image, product: dict[str, Any]) -> CertificateScaleResult:
    rgb = image.convert("RGB")
    width, height = rgb.size
    card_bbox = _detect_certificate_card_bbox(rgb)
    large_product = is_large_or_bulky_product(product)
    max_width_ratio = 1.0
    max_area_ratio = 1.0

    if card_bbox is None:
        return CertificateScaleResult(
            passed=False,
            code="CERTIFICATE_CARD_NOT_DETECTED",
            message="未检测到合格证卡片边界，不能通过正式下载质量门禁。",
            card_bbox=None,
            card_width_ratio=0.0,
            card_height_ratio=0.0,
            card_area_ratio=0.0,
            max_width_ratio=max_width_ratio,
            max_area_ratio=max_area_ratio,
            is_large_product=large_product,
        )

    left, top, right, bottom = card_bbox
    card_width = right - left + 1
    card_height = bottom - top + 1
    card_width_ratio = card_width / width
    card_height_ratio = card_height / height
    card_area_ratio = (card_width * card_height) / (width * height)

    return CertificateScaleResult(
        passed=True,
        code=None,
        message=None,
        card_bbox=card_bbox,
        card_width_ratio=card_width_ratio,
        card_height_ratio=card_height_ratio,
        card_area_ratio=card_area_ratio,
        max_width_ratio=max_width_ratio,
        max_area_ratio=max_area_ratio,
        is_large_product=large_product,
    )
