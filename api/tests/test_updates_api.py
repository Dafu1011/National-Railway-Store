import hashlib
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient

from app.main import create_app


class UpdatesApiTests(unittest.TestCase):
    def test_check_update_returns_latest_matching_published_release_with_existing_installer(self):
        with TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir)
            installer_bytes = b"fake exe 2.0.10"
            object_key = "windows/x64/stable/2.0.10/zhifeng-image-2.0.10-x64.exe"
            installer_path = app.state.storage.release_dir / object_key
            installer_path.parent.mkdir(parents=True, exist_ok=True)
            installer_path.write_bytes(installer_bytes)
            sha256 = hashlib.sha256(installer_bytes).hexdigest()
            insert_release(
                app,
                release_id="release-2-0-9",
                version="2.0.9",
                object_key="windows/x64/stable/2.0.9/zhifeng-image-2.0.9-x64.exe",
                sha256="old-sha",
            )
            insert_release(
                app,
                release_id="release-2-0-10",
                version="2.0.10",
                object_key=object_key,
                sha256=sha256,
                release_notes=["修复更新检测", "优化安装包下载"],
            )
            insert_release(
                app,
                release_id="release-beta",
                version="2.1.0",
                channel="beta",
                object_key="windows/x64/beta/2.1.0/zhifeng-image-2.1.0-x64.exe",
                sha256="beta-sha",
            )

            with TestClient(app) as client:
                response = client.get(
                    "/api/v1/updates/check",
                    params={
                        "current_version": "2.0.0",
                        "platform": "windows",
                        "arch": "x64",
                        "channel": "stable",
                    },
                )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["has_update"])
            self.assertEqual(payload["current_version"], "2.0.0")
            self.assertEqual(payload["latest_version"], "2.0.10")
            self.assertEqual(payload["channel"], "stable")
            self.assertEqual(payload["platform"], "windows")
            self.assertEqual(payload["arch"], "x64")
            self.assertFalse(payload["force_update"])
            self.assertEqual(payload["release_notes"], ["修复更新检测", "优化安装包下载"])
            self.assertEqual(payload["sha256"], sha256)
            self.assertEqual(payload["file_size_bytes"], len(installer_bytes))
            self.assertEqual(payload["download_url"], "/api/v1/updates/releases/release-2-0-10/download")

    def test_check_update_returns_no_update_when_current_version_is_latest(self):
        with TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir)
            object_key = "windows/x64/stable/2.0.3/zhifeng-image-2.0.3-x64.exe"
            installer_path = app.state.storage.release_dir / object_key
            installer_path.parent.mkdir(parents=True, exist_ok=True)
            installer_path.write_bytes(b"fake exe 2.0.3")
            insert_release(app, release_id="release-2-0-3", version="2.0.3", object_key=object_key)

            with TestClient(app) as client:
                response = client.get(
                    "/api/v1/updates",
                    params={
                        "current_version": "2.0.3",
                        "platform": "windows",
                        "arch": "x64",
                        "channel": "stable",
                    },
                )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertFalse(payload["has_update"])
            self.assertEqual(payload["latest_version"], "2.0.3")
            self.assertEqual(payload["download_url"], "/api/v1/updates/releases/release-2-0-3/download")

    def test_check_update_ignores_published_release_when_installer_file_is_missing(self):
        with TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir)
            insert_release(
                app,
                release_id="release-missing-file",
                version="2.0.3",
                object_key="windows/x64/stable/2.0.3/zhifeng-image-2.0.3-x64.exe",
            )

            with TestClient(app) as client:
                response = client.get(
                    "/api/v1/updates/check",
                    params={
                        "current_version": "2.0.0",
                        "platform": "windows",
                        "arch": "x64",
                        "channel": "stable",
                    },
                )

            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["detail"]["code"], "NO_RELEASE_AVAILABLE")

    def test_release_download_serves_installer_from_release_folder(self):
        with TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir)
            installer_bytes = b"fake windows installer"
            object_key = "windows/x64/stable/2.0.3/zhifeng-image-2.0.3-x64.exe"
            installer_path = app.state.storage.release_dir / object_key
            installer_path.parent.mkdir(parents=True, exist_ok=True)
            installer_path.write_bytes(installer_bytes)
            insert_release(app, release_id="release-download", version="2.0.3", object_key=object_key)

            with TestClient(app) as client:
                response = client.get("/api/v1/updates/releases/release-download/download")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, installer_bytes)
            self.assertIn("zhifeng-image-2.0.3-x64.exe", response.headers["content-disposition"])


def insert_release(
    app,
    *,
    release_id: str,
    version: str,
    object_key: str,
    sha256: str = "sha",
    channel: str = "stable",
    platform: str = "windows",
    arch: str = "x64",
    release_notes: list[str] | None = None,
) -> None:
    with app.state.storage.connect() as connection:
        connection.execute(
            """
            INSERT INTO app_releases
                (id, version, channel, platform, arch, object_key, sha256, file_size_bytes,
                 release_notes_json, force_update, min_supported_version, status, published_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, 0, '2.0.0', 'published', CURRENT_TIMESTAMP)
            """,
            (
                release_id,
                version,
                channel,
                platform,
                arch,
                object_key,
                sha256,
                json_dumps(release_notes or []),
            ),
        )


def json_dumps(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
