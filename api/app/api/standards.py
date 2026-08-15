from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.standards.gt_railway_mall import (
    GT_RAILWAY_MALL_STANDARD,
    GeneratedImageCandidate,
    ImageRole,
    ImageSignals,
    validate_gt_railway_upload_package,
)


router = APIRouter(prefix="/api/v1/standards", tags=["standards"])


class ImageSignalsPayload(BaseModel):
    is_white_background: bool
    is_clear: bool
    is_centered: bool
    fill_ratio: float = Field(ge=0, le=1)
    has_watermark: bool
    has_promo_text: bool
    has_date_or_url: bool
    has_other_brand_logo: bool
    has_large_dark_shadow: bool
    has_large_reflection: bool
    is_distorted: bool
    shows_brand_or_manufacturer: bool

    def to_domain(self) -> ImageSignals:
        return ImageSignals(**self.model_dump())


class GeneratedImageCandidatePayload(BaseModel):
    name: str
    role: ImageRole
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    file_size_bytes: int = Field(ge=0)
    format: str
    view: str
    signals: ImageSignalsPayload

    def to_domain(self) -> GeneratedImageCandidate:
        return GeneratedImageCandidate(
            name=self.name,
            role=self.role,
            width=self.width,
            height=self.height,
            file_size_bytes=self.file_size_bytes,
            format=self.format,
            view=self.view,
            signals=self.signals.to_domain(),
        )


class UploadPackagePayload(BaseModel):
    images: list[GeneratedImageCandidatePayload]


@router.get("/gt-railway-mall")
async def get_gt_railway_mall_standard() -> dict:
    standard = GT_RAILWAY_MALL_STANDARD
    return {
        "name": standard.name,
        "source_url": standard.source_url,
        "main_image": {
            "count": {"min": standard.main_image_min_count, "max": standard.main_image_max_count},
            "size": {"width": standard.main_image_width, "height": standard.main_image_height},
            "max_bytes": standard.main_image_max_bytes,
            "min_fill_ratio": standard.min_main_fill_ratio,
            "first_image_white_background": True,
        },
        "detail_image": {
            "width": standard.detail_image_width,
            "height": "unlimited",
            "max_bytes": standard.detail_image_max_bytes,
        },
        "allowed_formats": list(standard.allowed_formats),
        "forbidden": [
            "watermark",
            "promo_text",
            "date_or_url",
            "other_brand_logo",
            "large_dark_shadow",
            "large_reflection",
            "distortion",
        ],
    }


@router.post("/gt-railway-mall/validate")
async def validate_gt_railway_mall_package(payload: UploadPackagePayload) -> dict:
    result = validate_gt_railway_upload_package([image.to_domain() for image in payload.images])
    return {
        "passed": result.passed,
        "standard": {
            "name": result.standard.name,
            "source_url": result.standard.source_url,
        },
        "issues": [
            {
                "code": issue.code,
                "image_name": issue.image_name,
                "message": issue.message,
            }
            for issue in result.issues
        ],
    }



