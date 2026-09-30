from __future__ import annotations

import base64
import binascii
import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.billing import (
    InsufficientBalance,
    charge_generation_hold,
    release_generation_hold,
    reserve_generation_charge,
)
from app.providers.kele import KeleGptImage2Provider
from app.providers.single_image import KeleSingleImageProvider, MockSingleImageProvider, SingleGeneratedImage
from app.storage import AppStorage, new_id, row_to_dict


router = APIRouter(prefix="/api/v1", tags=["single-image"])

SINGLE_IMAGE_OUTPUT_TYPE = "single"
MAX_REFERENCE_IMAGES = 6
DEFAULT_SINGLE_IMAGE_POINTS = 2


class SingleImageCreatePayload(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    asset_version_ids: list[str] = Field(default_factory=list)

    @field_validator("prompt")
    @classmethod
    def normalize_prompt(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("prompt is required")
        return normalized

    @field_validator("asset_version_ids")
    @classmethod
    def validate_asset_count(cls, value: list[str]) -> list[str]:
        if len(value) > MAX_REFERENCE_IMAGES:
            raise ValueError(f"at most {MAX_REFERENCE_IMAGES} reference images are allowed")
        return value


def get_storage(request: Request) -> AppStorage:
    return request.app.state.storage


def get_runtime_services(request: Request) -> Any:
    return request.app.state.runtime_services


def current_user(
    authorization: str | None = Header(default=None),
    storage: AppStorage = Depends(get_storage),
) -> dict[str, Any]:
    from app.api.phase_one import current_user as phase_one_current_user

    return phase_one_current_user(authorization=authorization, storage=storage)


@router.post("/single-image-jobs", status_code=status.HTTP_202_ACCEPTED)
async def create_single_image_job(
    payload: SingleImageCreatePayload,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
    storage: AppStorage = Depends(get_storage),
    runtime_services: Any = Depends(get_runtime_services),
) -> dict[str, Any]:
    reference_assets = get_reference_assets(storage, asset_version_ids=payload.asset_version_ids, user_id=user["id"])
    provider = getattr(request.app.state, "single_image_provider_override", None) or build_single_image_provider()
    job_id = new_id()
    try:
        reserve_generation_charge(storage, user=user, job_id=job_id, points=single_image_generation_points())
    except InsufficientBalance as exc:
        raise_error(
            status.HTTP_402_PAYMENT_REQUIRED,
            "INSUFFICIENT_BALANCE",
            f"Insufficient balance: required {exc.required_points}, available {exc.available_points}.",
        )
    with storage.connect() as connection:
        connection.execute(
            """
            INSERT INTO single_image_jobs (id, user_id, prompt, status, provider_name)
            VALUES (?, ?, ?, 'queued', ?)
            """,
            (job_id, user["id"], payload.prompt, provider.name),
        )
        for index, asset in enumerate(reference_assets):
            connection.execute(
                """
                INSERT INTO single_image_job_assets (id, job_id, user_id, asset_version_id, sort_order)
                VALUES (?, ?, ?, ?, ?)
                """,
                (new_id(), job_id, user["id"], asset["version_id"], index),
            )

    if getattr(request.app.state, "single_image_provider_override", None) is not None:
        execute_claimed_single_image_job(
            job_id=job_id,
            storage=storage,
            runtime_services=runtime_services,
            provider_override=provider,
        )
    notify_generation_queue(request)
    return get_single_image_job_payload(storage, job_id, user["id"])


@router.get("/single-image-jobs/{job_id}")
async def get_single_image_job(
    job_id: str,
    user: dict[str, Any] = Depends(current_user),
    storage: AppStorage = Depends(get_storage),
) -> dict[str, Any]:
    return get_single_image_job_payload(storage, job_id, user["id"])


@router.get("/single-image-outputs/{output_id}/download")
async def download_single_image_output(
    output_id: str,
    user: dict[str, Any] = Depends(current_user),
    storage: AppStorage = Depends(get_storage),
) -> FileResponse:
    output = get_single_image_output(storage, output_id=output_id, user_id=user["id"])
    if output["quality_status"] != "passed":
        raise_error(status.HTTP_409_CONFLICT, "QUALITY_REVIEW_REQUIRED", "Output is not ready for download.")
    path = Path(output["file_path"])
    if not path.exists():
        raise_error(status.HTTP_404_NOT_FOUND, "OUTPUT_FILE_NOT_FOUND", "Output file does not exist.")
    return FileResponse(path, media_type="image/png", filename="single.png", headers=single_image_cache_headers(output))


@router.get("/single-image-outputs/{output_id}/thumbnail")
async def thumbnail_single_image_output(
    output_id: str,
    user: dict[str, Any] = Depends(current_user),
    storage: AppStorage = Depends(get_storage),
) -> FileResponse:
    output = get_single_image_output(storage, output_id=output_id, user_id=user["id"])
    if output["quality_status"] != "passed":
        raise_error(status.HTTP_409_CONFLICT, "QUALITY_REVIEW_REQUIRED", "Output is not ready for preview.")
    path = Path(output["file_path"])
    if not path.exists():
        raise_error(status.HTTP_404_NOT_FOUND, "OUTPUT_FILE_NOT_FOUND", "Output file does not exist.")
    thumbnail_path = ensure_single_image_thumbnail(path)
    return FileResponse(
        thumbnail_path,
        media_type="image/png",
        filename="single-thumb.png",
        headers=single_image_cache_headers(output),
    )


@router.delete("/single-image-outputs/{output_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_single_image_output(
    output_id: str,
    user: dict[str, Any] = Depends(current_user),
    storage: AppStorage = Depends(get_storage),
) -> Response:
    with storage.connect() as connection:
        updated = connection.execute(
            """
            UPDATE single_image_outputs
            SET deleted_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ? AND deleted_at IS NULL
            """,
            (output_id, user["id"]),
        )
        if updated.rowcount != 1:
            raise_access_denied()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def process_next_queued_single_image_job(storage: AppStorage, runtime_services: Any) -> bool:
    job_id = claim_next_queued_single_image_job(storage)
    if job_id is None:
        return False
    return execute_claimed_single_image_job(job_id=job_id, storage=storage, runtime_services=runtime_services)


def claim_next_queued_single_image_job(storage: AppStorage) -> str | None:
    with storage.connect() as connection:
        row = connection.execute(
            """
            SELECT id
            FROM single_image_jobs
            WHERE status = 'queued'
            ORDER BY created_at ASC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        updated = connection.execute(
            """
            UPDATE single_image_jobs
            SET status = 'running', error_code = NULL, error_message = NULL
            WHERE id = ? AND status = 'queued'
            """,
            (row["id"],),
        )
        if updated.rowcount != 1:
            return None
        return row["id"]


def execute_claimed_single_image_job(
    *,
    job_id: str,
    storage: AppStorage,
    runtime_services: Any,
    provider_override: Any | None = None,
) -> bool:
    context = single_image_job_context(storage, job_id=job_id)
    if context is None:
        return True
    job = context["job"]
    provider = provider_override or build_single_image_provider()
    try:
        with runtime_services.slot(
            "slot:provider:generation",
            limit=configured_positive_int("PROVIDER_MAX_CONCURRENCY", 2),
            ttl_seconds=configured_positive_int("GENERATION_SLOT_TTL_SECONDS", 900),
        ):
            generated = provider.generate_single_image(
                output_dir=storage.output_dir,
                job_id=job_id,
                prompt=job["prompt"],
                reference_image_paths=[Path(asset["file_path"]) for asset in context["assets"]],
            )
    except Exception as exc:
        if str(exc).startswith("SLOT_BUSY"):
            requeue_single_image_job(storage, job_id=job_id, user_id=job["user_id"])
            return False
        with storage.connect() as connection:
            connection.execute(
                """
                UPDATE single_image_jobs
                SET status = 'failed',
                    completed_at = CURRENT_TIMESTAMP,
                    error_code = ?,
                    error_message = ?
                WHERE id = ? AND user_id = ?
                """,
                ("IMAGE_PROVIDER_FAILED", clip_error_message(str(exc)), job_id, job["user_id"]),
            )
        release_generation_hold(storage, user_id=job["user_id"], job_id=job_id, remark="Single image generation failed; hold released.")
        return True

    with storage.connect() as connection:
        insert_single_image_output(connection, user_id=job["user_id"], job_id=job_id, image=generated)
    charge_generation_hold(storage, user_id=job["user_id"], job_id=job_id, remark="单图生成扣费")
    with storage.connect() as connection:
        connection.execute(
            """
            UPDATE single_image_jobs
            SET status = 'completed',
                completed_at = CURRENT_TIMESTAMP,
                error_code = NULL,
                error_message = NULL
            WHERE id = ? AND user_id = ?
            """,
            (job_id, job["user_id"]),
        )
    runtime_services.delete_cache(gallery_cache_key(job["user_id"]))
    return True


def single_image_job_context(storage: AppStorage, *, job_id: str) -> dict[str, Any] | None:
    with storage.connect() as connection:
        job = row_to_dict(connection.execute("SELECT * FROM single_image_jobs WHERE id = ?", (job_id,)).fetchone())
        if job is None:
            return None
        rows = connection.execute(
            """
            SELECT
                asset_versions.id AS version_id,
                asset_versions.file_path,
                asset_versions.width,
                asset_versions.height,
                assets.asset_type
            FROM single_image_job_assets
            JOIN asset_versions ON asset_versions.id = single_image_job_assets.asset_version_id
            JOIN assets ON assets.id = asset_versions.asset_id
            WHERE single_image_job_assets.job_id = ?
              AND single_image_job_assets.user_id = ?
            ORDER BY single_image_job_assets.sort_order ASC
            """,
            (job_id, job["user_id"]),
        ).fetchall()
    return {"job": job, "assets": [dict(row) for row in rows]}


def get_reference_assets(storage: AppStorage, *, asset_version_ids: list[str], user_id: str) -> list[dict[str, Any]]:
    if not asset_version_ids:
        return []
    placeholders = ",".join("?" for _ in asset_version_ids)
    with storage.connect() as connection:
        rows = connection.execute(
            f"""
            SELECT
                assets.id AS asset_id,
                assets.asset_type,
                asset_versions.id AS version_id,
                asset_versions.file_path,
                asset_versions.width,
                asset_versions.height
            FROM asset_versions
            JOIN assets ON assets.id = asset_versions.asset_id
            WHERE asset_versions.user_id = ?
              AND asset_versions.id IN ({placeholders})
              AND assets.asset_type = 'single_image_reference'
              AND assets.deleted_at IS NULL
              AND assets.status = 'active'
            """,
            [user_id, *asset_version_ids],
        ).fetchall()
    by_id = {row["version_id"]: dict(row) for row in rows}
    if len(by_id) != len(set(asset_version_ids)):
        raise_access_denied()
    return [by_id[version_id] for version_id in asset_version_ids]


def get_single_image_job_payload(storage: AppStorage, job_id: str, user_id: str) -> dict[str, Any]:
    with storage.connect() as connection:
        job = row_to_dict(
            connection.execute(
                "SELECT * FROM single_image_jobs WHERE id = ? AND user_id = ?",
                (job_id, user_id),
            ).fetchone()
        )
        if job is None:
            raise_access_denied()
        reference_count = int(
            connection.execute(
                "SELECT COUNT(*) AS count FROM single_image_job_assets WHERE job_id = ? AND user_id = ?",
                (job_id, user_id),
            ).fetchone()["count"]
        )
    job["reference_asset_count"] = reference_count
    job["outputs"] = list_single_image_outputs(storage, job_id=job_id, user_id=user_id)
    return job


def list_single_image_outputs(storage: AppStorage, *, job_id: str, user_id: str) -> list[dict[str, Any]]:
    with storage.connect() as connection:
        rows = connection.execute(
            """
            SELECT * FROM single_image_outputs
            WHERE job_id = ? AND user_id = ? AND deleted_at IS NULL
            ORDER BY created_at ASC
            """,
            (job_id, user_id),
        ).fetchall()
    return [single_image_output_payload(dict(row)) for row in rows]


def list_gallery_single_image_output_summaries(
    storage: AppStorage,
    *,
    user_id: str,
    limit: int,
    cursor: str | None = None,
) -> list[dict[str, Any]]:
    cursor_values = decode_gallery_cursor(cursor)
    clauses = ["user_id = ?", "quality_status = 'passed'", "deleted_at IS NULL"]
    params: list[Any] = [user_id]
    if cursor_values is not None:
        clauses.append("(created_at < ? OR (created_at = ? AND id < ?))")
        params.extend([cursor_values["created_at"], cursor_values["created_at"], cursor_values["id"]])
    params.append(max(limit * 4, 20))
    with storage.connect() as connection:
        rows = connection.execute(
            f"""
            SELECT id, output_type, width, height, quality_status, created_at, file_path
            FROM single_image_outputs
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        payload = dict(row)
        if not Path(payload["file_path"]).exists():
            continue
        payload.pop("file_path", None)
        items.append(single_image_output_payload(payload))
        if len(items) >= limit:
            break
    return items


def single_image_output_payload(row: dict[str, Any]) -> dict[str, Any]:
    output_id = row["id"]
    row["source"] = "single_image"
    row["download_url"] = f"/api/v1/single-image-outputs/{output_id}/download"
    row["thumbnail_url"] = f"/api/v1/single-image-outputs/{output_id}/thumbnail"
    return row


def insert_single_image_output(connection: Any, *, user_id: str, job_id: str, image: SingleGeneratedImage) -> None:
    existing = connection.execute(
        "SELECT id FROM single_image_outputs WHERE job_id = ? AND user_id = ? AND output_type = ?",
        (job_id, user_id, image.output_type),
    ).fetchone()
    if existing is not None:
        ensure_single_image_thumbnail(image.path)
        return
    connection.execute(
        """
        INSERT INTO single_image_outputs
            (id, user_id, job_id, output_type, width, height, format, file_path, quality_status)
        VALUES (?, ?, ?, ?, ?, ?, 'png', ?, 'passed')
        """,
        (new_id(), user_id, job_id, image.output_type, image.width, image.height, str(image.path)),
    )
    ensure_single_image_thumbnail(image.path)


def get_single_image_output(storage: AppStorage, *, output_id: str, user_id: str) -> dict[str, Any]:
    with storage.connect() as connection:
        output = row_to_dict(
            connection.execute(
                "SELECT * FROM single_image_outputs WHERE id = ? AND user_id = ? AND deleted_at IS NULL",
                (output_id, user_id),
            ).fetchone()
        )
    if output is None:
        raise_access_denied()
    return output


def ensure_single_image_thumbnail(path: Path) -> Path:
    thumbnail_path = path.with_name(f"{path.stem}.thumb.png")
    if thumbnail_path.exists() and thumbnail_path.stat().st_mtime >= path.stat().st_mtime:
        return thumbnail_path
    with Image.open(path) as image:
        thumbnail = ImageOps.contain(image.convert("RGB"), (320, 320), method=Image.Resampling.LANCZOS)
        thumbnail.save(thumbnail_path, format="PNG", optimize=True)
    return thumbnail_path


def build_single_image_provider() -> Any:
    provider_name = os.getenv("IMAGE_PROVIDER", "mock").strip().lower()
    if provider_name in {"mock", "local"}:
        return MockSingleImageProvider()
    if provider_name in {"kele", "code28", "kele-gpt-image-2", "gpt-image-2"}:
        from app.api.phase_one import load_kele_config

        return KeleSingleImageProvider(
            KeleGptImage2Provider(load_kele_config()),
            image_size=os.getenv("KELE_IMAGE_SIZE", "1024x1024"),
        )
    raise_error(status.HTTP_503_SERVICE_UNAVAILABLE, "IMAGE_PROVIDER_UNSUPPORTED", f"Unsupported IMAGE_PROVIDER: {provider_name}")


def requeue_single_image_job(storage: AppStorage, *, job_id: str, user_id: str) -> None:
    with storage.connect() as connection:
        connection.execute(
            "UPDATE single_image_jobs SET status = 'queued' WHERE id = ? AND user_id = ? AND status = 'running'",
            (job_id, user_id),
        )


def notify_generation_queue(request: Request) -> None:
    queue = getattr(request.app.state, "generation_queue", None)
    if queue is not None:
        queue.notify()


def single_image_generation_points() -> int:
    return configured_positive_int("SINGLE_IMAGE_GENERATION_POINTS", DEFAULT_SINGLE_IMAGE_POINTS)


def configured_positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def gallery_cache_key(user_id: str) -> str:
    return f"cache:gallery:outputs:{user_id}"


def encode_gallery_cursor(row: dict[str, Any]) -> str:
    payload = json.dumps({"created_at": row["created_at"], "id": row["id"]}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_gallery_cursor(cursor: str | None) -> dict[str, str] | None:
    if cursor is None or cursor == "":
        return None
    try:
        padded_cursor = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded_cursor.encode("ascii")).decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        raise_error(status.HTTP_400_BAD_REQUEST, "INVALID_GALLERY_CURSOR", "Invalid gallery cursor.")
    if not isinstance(payload, dict) or not isinstance(payload.get("created_at"), str) or not isinstance(payload.get("id"), str):
        raise_error(status.HTTP_400_BAD_REQUEST, "INVALID_GALLERY_CURSOR", "Invalid gallery cursor.")
    return {"created_at": payload["created_at"], "id": payload["id"]}


def single_image_cache_headers(output: dict[str, Any]) -> dict[str, str]:
    return {
        "Cache-Control": "private, max-age=86400",
        "ETag": f"\"{output['id']}-1\"",
    }


def raise_access_denied() -> None:
    raise_error(status.HTTP_404_NOT_FOUND, "RESOURCE_ACCESS_DENIED", "Resource does not exist or access is denied.")


def raise_error(status_code: int, code: str, message: str) -> None:
    raise HTTPException(status_code=status_code, detail={"code": code, "message": message})


def clip_error_message(message: str, limit: int = 2000) -> str:
    return message[:limit]
