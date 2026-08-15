from dataclasses import dataclass
from enum import StrEnum
from io import BytesIO

from PIL import Image


class ImageRole(StrEnum):
    MAIN = "main"
    DETAIL = "detail"


@dataclass
class GtRailwayMallStandard:
    name: str
    source_url: str
    main_image_min_count: int
    main_image_max_count: int
    main_image_width: int
    main_image_height: int
    main_image_max_bytes: int
    detail_image_width: int
    detail_image_max_bytes: int
    min_main_fill_ratio: float
    allowed_formats: tuple[str, ...]


GT_RAILWAY_MALL_STANDARD = GtRailwayMallStandard(
    name="国铁商城商品发布规则",
    source_url="https://mall.95306.cn/mall-view/noticeRe?id=15",
    main_image_min_count=3,
    main_image_max_count=5,
    main_image_width=800,
    main_image_height=800,
    main_image_max_bytes=1_048_576,
    detail_image_width=800,
    detail_image_max_bytes=5_242_880,
    min_main_fill_ratio=0.8,
    allowed_formats=("png", "jpg", "jpeg", "webp"),
)


@dataclass
class ImageSignals:
    is_white_background: bool
    is_clear: bool
    is_centered: bool
    fill_ratio: float
    has_watermark: bool
    has_promo_text: bool
    has_date_or_url: bool
    has_other_brand_logo: bool
    has_large_dark_shadow: bool
    has_large_reflection: bool
    is_distorted: bool
    shows_brand_or_manufacturer: bool


@dataclass
class GeneratedImageCandidate:
    name: str
    role: ImageRole
    width: int
    height: int
    file_size_bytes: int
    format: str
    view: str
    signals: ImageSignals


@dataclass(frozen=True)
class UploadStandardIssue:
    code: str
    image_name: str | None
    message: str


@dataclass(frozen=True)
class UploadStandardValidationResult:
    standard: GtRailwayMallStandard
    passed: bool
    issues: list[UploadStandardIssue]


def validate_gt_railway_upload_package(
    images: list[GeneratedImageCandidate],
    *,
    standard: GtRailwayMallStandard = GT_RAILWAY_MALL_STANDARD,
) -> UploadStandardValidationResult:
    issues: list[UploadStandardIssue] = []
    main_images = [image for image in images if image.role == ImageRole.MAIN]
    detail_images = [image for image in images if image.role == ImageRole.DETAIL]

    if not standard.main_image_min_count <= len(main_images) <= standard.main_image_max_count:
        issues.append(
            UploadStandardIssue(
                code="GT_MAIN_COUNT_INVALID",
                image_name=None,
                message=f"商品主图需 {standard.main_image_min_count}-{standard.main_image_max_count} 张。",
            )
        )

    if main_images and not main_images[0].signals.is_white_background:
        issues.append(
            UploadStandardIssue(
                code="GT_FIRST_MAIN_BACKGROUND_NOT_WHITE",
                image_name=main_images[0].name,
                message="首张商品主图必须为白底。",
            )
        )

    seen_views: set[str] = set()
    for image in main_images:
        if image.width != standard.main_image_width or image.height != standard.main_image_height:
            issues.append(
                UploadStandardIssue(
                    code="GT_MAIN_SIZE_INVALID",
                    image_name=image.name,
                    message="商品主图尺寸必须为 800px x 800px。",
                )
            )
        if image.file_size_bytes > standard.main_image_max_bytes:
            issues.append(
                UploadStandardIssue(
                    code="GT_MAIN_FILE_TOO_LARGE",
                    image_name=image.name,
                    message="商品主图单张照片不得超过 1M。",
                )
            )
        if image.view in seen_views:
            issues.append(
                UploadStandardIssue(
                    code="GT_MAIN_VIEW_DUPLICATED",
                    image_name=image.name,
                    message="商品主图应展示不同视角，不得重复。",
                )
            )
        seen_views.add(image.view)
        _append_common_visual_issues(image, issues, require_fill_ratio=True, standard=standard)

    if main_images and not any(image.signals.shows_brand_or_manufacturer for image in main_images):
        issues.append(
            UploadStandardIssue(
                code="GT_BRAND_OR_MANUFACTURER_NOT_SHOWN",
                image_name=None,
                message="商品主图至少 1 张需完整清晰展示品牌标识或生产厂家信息。",
            )
        )

    for image in detail_images:
        if image.width != standard.detail_image_width:
            issues.append(
                UploadStandardIssue(
                    code="GT_DETAIL_WIDTH_INVALID",
                    image_name=image.name,
                    message="商品详情图宽度必须为 800px。",
                )
            )
        if image.file_size_bytes > standard.detail_image_max_bytes:
            issues.append(
                UploadStandardIssue(
                    code="GT_DETAIL_FILE_TOO_LARGE",
                    image_name=image.name,
                    message="商品详情图单张不得超过 5M。",
                )
            )
        _append_common_visual_issues(image, issues, require_fill_ratio=False, standard=standard)

    return UploadStandardValidationResult(standard=standard, passed=len(issues) == 0, issues=issues)


def inspect_gt_railway_image_file(
    *,
    name: str,
    role: ImageRole,
    content: bytes,
    view: str,
    file_size_override: int | None = None,
) -> GeneratedImageCandidate:
    with Image.open(BytesIO(content)) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        image_format = (image.format or "").lower()
        is_white_background = _has_white_corners(rgb)
        fill_ratio = _foreground_bounding_box_ratio(rgb)

    return GeneratedImageCandidate(
        name=name,
        role=role,
        width=width,
        height=height,
        file_size_bytes=file_size_override if file_size_override is not None else len(content),
        format=image_format,
        view=view,
        signals=ImageSignals(
            is_white_background=is_white_background,
            is_clear=True,
            is_centered=True,
            fill_ratio=fill_ratio,
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


def _append_common_visual_issues(
    image: GeneratedImageCandidate,
    issues: list[UploadStandardIssue],
    *,
    require_fill_ratio: bool,
    standard: GtRailwayMallStandard,
) -> None:
    if image.format.lower().lstrip(".") not in standard.allowed_formats:
        issues.append(_issue("GT_IMAGE_FORMAT_UNSUPPORTED", image, "商品图片格式应为 PNG、JPG、JPEG 或 WebP。"))
    if not image.signals.is_clear:
        issues.append(_issue("GT_IMAGE_NOT_CLEAR", image, "商品图片必须清晰完整。"))
    if not image.signals.is_centered:
        issues.append(_issue("GT_IMAGE_NOT_CENTERED", image, "商品图片应居中布置。"))
    if require_fill_ratio and image.signals.fill_ratio < standard.min_main_fill_ratio:
        issues.append(_issue("GT_IMAGE_FILL_RATIO_LOW", image, "商品主体填充背景空间不得低于 80%。"))
    if image.signals.has_watermark:
        issues.append(_issue("GT_IMAGE_HAS_WATERMARK", image, "商品图片不得出现水印。"))
    if image.signals.has_promo_text:
        issues.append(_issue("GT_IMAGE_HAS_PROMO_TEXT", image, "商品图片不得包含促销文字。"))
    if image.signals.has_date_or_url:
        issues.append(_issue("GT_IMAGE_HAS_DATE_OR_URL", image, "商品图片不应包含日期、网站名称或链接。"))
    if image.signals.has_other_brand_logo:
        issues.append(_issue("GT_IMAGE_HAS_OTHER_BRAND_LOGO", image, "商品图片不应包含其他品牌 Logo。"))
    if image.signals.has_large_dark_shadow:
        issues.append(_issue("GT_IMAGE_HAS_LARGE_DARK_SHADOW", image, "商品图片不能有大面积黑投影。"))
    if image.signals.has_large_reflection:
        issues.append(_issue("GT_IMAGE_HAS_LARGE_REFLECTION", image, "商品图片不能有大面积反光环境物。"))
    if image.signals.is_distorted:
        issues.append(_issue("GT_IMAGE_DISTORTED", image, "商品图片不得出现拉伸、变形、压缩。"))


def _issue(code: str, image: GeneratedImageCandidate, message: str) -> UploadStandardIssue:
    return UploadStandardIssue(code=code, image_name=image.name, message=message)


def _has_white_corners(image: Image.Image) -> bool:
    width, height = image.size
    sample_points = [(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)]
    return all(_is_near_white(image.getpixel(point)) for point in sample_points)


def _foreground_bounding_box_ratio(image: Image.Image) -> float:
    width, height = image.size
    min_x, min_y = width, height
    max_x, max_y = -1, -1
    background = _average_corner_color(image)

    for y in range(height):
        for x in range(width):
            if _color_distance(image.getpixel((x, y)), background) > 30:
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)

    if max_x < min_x or max_y < min_y:
        return 0.0

    box_width = max_x - min_x + 1
    box_height = max_y - min_y + 1
    return (box_width * box_height) / (width * height)


def _is_near_white(pixel: tuple[int, int, int]) -> bool:
    red, green, blue = pixel
    return red >= 245 and green >= 245 and blue >= 245


def _average_corner_color(image: Image.Image) -> tuple[int, int, int]:
    width, height = image.size
    points = [(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)]
    colors = [image.getpixel(point) for point in points]
    return tuple(sum(color[index] for color in colors) // len(colors) for index in range(3))


def _color_distance(left: tuple[int, int, int], right: tuple[int, int, int]) -> int:
    return sum(abs(left[index] - right[index]) for index in range(3))
