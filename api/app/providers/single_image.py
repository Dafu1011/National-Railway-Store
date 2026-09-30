from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from app.providers.kele import KeleGptImage2Provider


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
        Image.new("RGB", (1024, 1024), "white").save(path)
        return SingleGeneratedImage(output_type="single", width=1024, height=1024, path=path)


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
        path.write_bytes(image_bytes)
        with Image.open(path) as image:
            normalized = image.convert("RGB")
            width, height = normalized.size
            normalized.save(path, format="PNG", optimize=True)
        return SingleGeneratedImage(output_type="single", width=width, height=height, path=path)
