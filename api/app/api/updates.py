from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse

from app.storage import AppStorage, json_loads, row_to_dict


router = APIRouter(prefix="/api/v1/updates", tags=["updates"])
VERSION_PATTERN = re.compile(r"^\d+(?:\.\d+){0,3}$")
SUPPORTED_PLATFORMS = {"windows"}
SUPPORTED_ARCHES = {"x64", "arm64"}
SUPPORTED_CHANNELS = {"stable", "beta"}


def get_storage(request: Request) -> AppStorage:
    return request.app.state.storage


@router.get("")
@router.get("/check")
async def check_update(
    current_version: str = Query(min_length=1, max_length=32),
    platform: str = Query(min_length=2, max_length=32),
    arch: str = Query(default="x64", min_length=2, max_length=16),
    channel: str = Query(default="stable", min_length=2, max_length=24),
    storage: AppStorage = Depends(get_storage),
) -> dict[str, Any]:
    normalized_current = normalize_version(current_version)
    normalized_platform = normalize_enum(platform)
    normalized_arch = normalize_enum(arch)
    normalized_channel = normalize_enum(channel)
    if normalized_current is None:
        raise_error(status.HTTP_400_BAD_REQUEST, "INVALID_VERSION", "当前版本号格式无效。")
    if normalized_platform not in SUPPORTED_PLATFORMS:
        raise_error(status.HTTP_400_BAD_REQUEST, "UNSUPPORTED_PLATFORM", "暂不支持该平台的更新检测。")
    if normalized_arch not in SUPPORTED_ARCHES:
        raise_error(status.HTTP_400_BAD_REQUEST, "UNSUPPORTED_ARCH", "暂不支持该架构的更新检测。")
    if normalized_channel not in SUPPORTED_CHANNELS:
        raise_error(status.HTTP_400_BAD_REQUEST, "UNSUPPORTED_CHANNEL", "暂不支持该发布通道。")

    release = find_latest_available_release(
        storage,
        platform=normalized_platform,
        arch=normalized_arch,
        channel=normalized_channel,
    )
    if release is None:
        raise_error(status.HTTP_404_NOT_FOUND, "NO_RELEASE_AVAILABLE", "暂无可用更新版本。")

    latest_version = normalize_version(release["version"])
    has_update = compare_versions(latest_version, normalized_current) > 0
    min_supported = normalize_version(release.get("min_supported_version") or "0")
    force_update = bool(release["force_update"]) or compare_versions(normalized_current, min_supported) < 0
    installer_path = resolve_release_path(storage, release["object_key"])

    return {
        "has_update": has_update,
        "current_version": normalized_current,
        "latest_version": latest_version,
        "channel": release["channel"],
        "platform": release["platform"],
        "arch": release["arch"],
        "force_update": force_update,
        "release_notes": json_loads(release["release_notes_json"]),
        "download_url": f"/api/v1/updates/releases/{release['id']}/download",
        "sha256": release["sha256"],
        "file_size_bytes": int(release.get("file_size_bytes") or installer_path.stat().st_size),
        "published_at": release["published_at"],
    }


@router.get("/releases/{release_id}/download")
async def download_release(release_id: str, storage: AppStorage = Depends(get_storage)) -> FileResponse:
    with storage.connect() as connection:
        release = row_to_dict(
            connection.execute(
                "SELECT * FROM app_releases WHERE id = ? AND status = 'published'",
                (release_id,),
            ).fetchone()
        )
    if release is None:
        raise_error(status.HTTP_404_NOT_FOUND, "RELEASE_NOT_FOUND", "版本不存在或尚未发布。")
    installer_path = resolve_release_path(storage, release["object_key"])
    if not installer_path.exists() or not installer_path.is_file():
        raise_error(status.HTTP_404_NOT_FOUND, "RELEASE_INSTALLER_NOT_FOUND", "安装包文件不存在。")
    return FileResponse(
        installer_path,
        media_type="application/vnd.microsoft.portable-executable",
        filename=installer_path.name,
    )


def find_latest_available_release(storage: AppStorage, *, platform: str, arch: str, channel: str) -> dict[str, Any] | None:
    with storage.connect() as connection:
        rows = connection.execute(
            """
            SELECT * FROM app_releases
            WHERE platform = ?
              AND arch = ?
              AND channel = ?
              AND status = 'published'
              AND published_at IS NOT NULL
            """,
            (platform, arch, channel),
        ).fetchall()
    candidates: list[dict[str, Any]] = []
    for row in rows:
        release = dict(row)
        version = normalize_version(release["version"])
        if version is None:
            continue
        installer_path = resolve_release_path(storage, release["object_key"])
        if installer_path.exists() and installer_path.is_file():
            release["version"] = version
            candidates.append(release)
    if not candidates:
        return None
    return max(candidates, key=lambda release: version_tuple(release["version"]))


def resolve_release_path(storage: AppStorage, object_key: str) -> Path:
    relative_path = Path(object_key.replace("\\", "/"))
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise_error(status.HTTP_400_BAD_REQUEST, "INVALID_RELEASE_OBJECT_KEY", "安装包路径无效。")
    return storage.release_dir / relative_path


def normalize_version(version: str) -> str | None:
    normalized = version.strip()
    if not VERSION_PATTERN.match(normalized):
        return None
    return ".".join(str(int(part)) for part in normalized.split("."))


def compare_versions(left: str, right: str) -> int:
    left_tuple = version_tuple(left)
    right_tuple = version_tuple(right)
    if left_tuple > right_tuple:
        return 1
    if left_tuple < right_tuple:
        return -1
    return 0


def version_tuple(version: str) -> tuple[int, int, int, int]:
    parts = [int(part) for part in version.split(".")]
    return tuple((parts + [0, 0, 0, 0])[:4])


def normalize_enum(value: str) -> str:
    return value.strip().lower()


def raise_error(status_code: int, code: str, message: str) -> None:
    raise HTTPException(status_code=status_code, detail={"code": code, "message": message})
