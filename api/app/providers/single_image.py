from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from app.providers.kele import KeleGptImage2Provider


SINGLE_IMAGE_OUTPUT_SIZE = (800, 800)


@dataclass(frozen=True)
class SingleGeneratedImage:
    output_type: str
    width: int
    height: int
    path: Path


class MockSingleImageProvider:
    name = "mock-single-image"

    def generate_single_image(
        self,
        *,
        output_dir: Path,
        job_id: str,
        prompt: str,
        reference_image_paths: list[Path],
    ) -> SingleGeneratedImage:
        job_dir = output_dir / "single-image" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        path = job_dir / "single.png"
        Image.new("RGB", SINGLE_IMAGE_OUTPUT_SIZE, "white").save(path, format="PNG")
        return SingleGeneratedImage(
            output_type="single", width=SINGLE_IMAGE_OUTPUT_SIZE[0], height=SINGLE_IMAGE_OUTPUT_SIZE[1], path=path,
        )


class KeleSingleImageProvider:
    name = "kele-gpt-image-2-single"

    def __init__(self, provider: KeleGptImage2Provider, *, image_size: str = "1024x1024"):
        self.provider = provider
        self.image_size = image_size

    def generate_single_image(
        self,
        *,
        output_dir: Path,
        job_id: str,
        prompt: str,
        reference_image_paths: list[Path],
    ) -> SingleGeneratedImage:
        if reference_image_paths:
            image_bytes = self.provider.edit_image(prompt=prompt, size=self.image_size, image_paths=reference_image_paths)
        else:
            image_bytes = self.provider.generate_image(prompt=prompt, size=self.image_size)
        job_dir = output_dir / "single-image" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        path = job_dir / "single.png"
        with Image.open(BytesIO(image_bytes)) as image:
            contained = ImageOps.contain(
                image.convert("RGB"), SINGLE_IMAGE_OUTPUT_SIZE, method=Image.Resampling.LANCZOS,
            )
        normalized = Image.new("RGB", SINGLE_IMAGE_OUTPUT_SIZE, "white")
        normalized.paste(
            contained, ((normalized.width - contained.width) // 2, (normalized.height - contained.height) // 2),
        )
        normalized.save(path, format="PNG", optimize=True)
        width, height = normalized.size
        return SingleGeneratedImage(output_type="single", width=width, height=height, path=path)
