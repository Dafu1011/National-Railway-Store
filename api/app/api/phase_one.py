from __future__ import annotations

from io import BytesIO
from pathlib import Path
import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from PIL import Image, ImageOps, UnidentifiedImageError

from app.providers.mock_image import MockImageProvider
from app.providers.kele import KeleConfig, KeleGptImage2Provider
from app.providers.real_image import OUTPUT_SPECS, KeleFiveImagePipeline
from app.rendering.barcode.validators import BarcodeType, validate_barcode_value
from app.storage import AppStorage, json_dumps, json_loads, new_id, row_to_dict
from app.core.billing import (
    InsufficientBalance,
    charge_generation_hold,
    release_generation_hold,
    reserve_generation_charge,
)
from app.core.email_sender import EmailNotConfigured, send_registration_code_email
from app.core.object_storage import material_object_key


router = APIRouter(prefix="/api/v1", tags=["phase-one"])
logger = logging.getLogger(__name__)

HTTP_422 = 422
REFRESH_COOKIE_NAME = "zhifeng_refresh_token"
ALLOWED_ASSET_TYPES = {
    "product_original",
    "product_detail",
    "product_cutout",
    "logo",
    "certificate_reference",
    "package_reference",
}
ALLOWED_IMAGE_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp"}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_IMAGE_PIXELS = 24_000_000


class RegistrationCodePayload(BaseModel):
    email: str = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("email format is invalid")
        return normalized


class RegisterPayload(RegistrationCodePayload):
    username: str = Field(min_length=1, max_length=60)
    verification_code: str = Field(min_length=4, max_length=8)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("username is required")
        return normalized

    @field_validator("verification_code")
    @classmethod
    def normalize_verification_code(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.isdigit():
            raise ValueError("verification code must be numeric")
        return normalized


class LoginPayload(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return RegisterPayload.validate_email(value)


class PasswordResetCodePayload(RegistrationCodePayload):
    pass


class PasswordResetPayload(RegistrationCodePayload):
    verification_code: str = Field(min_length=4, max_length=8)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("verification_code")
    @classmethod
    def normalize_verification_code(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.isdigit():
            raise ValueError("verification code must be numeric")
        return normalized


class ProductSpecPayload(BaseModel):
    key: str
    value: str
    unit: str = ""


class ProductCreatePayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    brand: str = ""
    model: str = ""
    category: str = ""
    material: str = ""
    color: str = ""
    description: str = ""
    specs: list[ProductSpecPayload] = Field(default_factory=list)


class BarcodePayload(BaseModel):
    barcode_type: BarcodeType
    raw_value: str


class ProjectBarcodePayload(BarcodePayload):
    confirmed: bool


class ProjectCreatePayload(BaseModel):
    product_id: str
    name: str = Field(min_length=1, max_length=120)
    style_config: dict[str, Any] = Field(default_factory=dict)
    certificate_config: dict[str, Any] = Field(default_factory=dict)
    package_config: dict[str, Any] = Field(default_factory=dict)
    detail_config: dict[str, Any] = Field(default_factory=dict)
    barcode: ProjectBarcodePayload


class UploadPresignPayload(BaseModel):
    asset_type: str
    filename: str = Field(min_length=1, max_length=180)
    content_type: str = Field(min_length=3, max_length=80)
    size_bytes: int = Field(gt=0, le=MAX_UPLOAD_BYTES)

    @field_validator("asset_type")
    @classmethod
    def validate_asset_type(cls, value: str) -> str:
        if value not in ALLOWED_ASSET_TYPES:
            raise ValueError("asset_type is not allowed")
        return value

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in ALLOWED_IMAGE_CONTENT_TYPES:
            raise ValueError("image content type is not allowed")
        return normalized


class UploadCompletePayload(BaseModel):
    upload_token: str = Field(min_length=24, max_length=160)
    product_id: str | None = None
    project_id: str | None = None


def get_storage(request: Request) -> AppStorage:
    return request.app.state.storage


def get_runtime_services(request: Request) -> Any:
    return request.app.state.runtime_services


def current_user(
    authorization: str | None = Header(default=None),
    storage: AppStorage = Depends(get_storage),
) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise_error(status.HTTP_401_UNAUTHORIZED, "AUTH_REQUIRED", "闇€瑕佺櫥褰曞悗璁块棶銆?")
    token = authorization.removeprefix("Bearer ").strip()
    with storage.connect() as connection:
        user = connection.execute(
            """
            SELECT users.* FROM users
            JOIN sessions ON sessions.user_id = users.id
            WHERE sessions.token = ? AND sessions.expires_at > ?
            """,
            (token, utc_now()),
        ).fetchone()
        if user is not None:
            connection.execute(
                "UPDATE sessions SET expires_at = ? WHERE token = ?",
                (utc_after(days=refresh_token_expire_days()), token),
            )
    if user is None:
        raise_error(status.HTTP_401_UNAUTHORIZED, "AUTH_REQUIRED", "鐧诲綍鐘舵€佹棤鏁堛€?")
    return dict(user)


@router.post("/auth/registration-code", status_code=status.HTTP_202_ACCEPTED)
async def send_registration_code(
    payload: RegistrationCodePayload,
    storage: AppStorage = Depends(get_storage),
    runtime_services: Any = Depends(get_runtime_services),
) -> dict[str, Any]:
    email_key = hashlib.sha256(payload.email.lower().encode("utf-8")).hexdigest()
    if not is_supported_registration_email(payload.email):
        raise_error(status.HTTP_400_BAD_REQUEST, "EMAIL_DOMAIN_UNSUPPORTED", "娉ㄥ唽閭浠呮敮鎸?QQ 閭鍜岀綉鏄撻偖绠便€?")
    if runtime_services.hit_rate_limit(f"rate:registration-code:{email_key}", limit=5, window_seconds=3600):
        raise_error(status.HTTP_429_TOO_MANY_REQUESTS, "EMAIL_CODE_RATE_LIMITED", "楠岃瘉鐮佽姹傝繃浜庨绻併€?")
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires_minutes = registration_code_expire_minutes()
    try:
        with runtime_services.lock(f"lock:register:{email_key}", ttl_seconds=30):
            with storage.connect() as connection:
                existing_user = connection.execute(
                    "SELECT id FROM users WHERE email_normalized = ? OR email = ?",
                    (payload.email.lower(), payload.email.lower()),
                ).fetchone()
                if existing_user is not None:
                    raise_error(status.HTTP_409_CONFLICT, "EMAIL_ALREADY_REGISTERED", "璇ラ偖绠卞凡缁忔敞鍐屻€?")
                # Keep only the latest unused registration code for one email.
                connection.execute(
                    """
                    UPDATE email_verification_codes
                    SET consumed_at = CURRENT_TIMESTAMP
                    WHERE email = ? AND purpose = 'register' AND consumed_at IS NULL
                    """,
                    (payload.email.lower(),),
                )
                connection.execute(
                    """
                    INSERT INTO email_verification_codes (id, email, code_hash, purpose, expires_at)
                    VALUES (?, ?, ?, 'register', ?)
                    """,
                    (new_id(), payload.email.lower(), hash_registration_code(payload.email, code), utc_after(minutes=expires_minutes)),
                )
        send_registration_code_email(payload.email, code, expires_minutes=expires_minutes)
    except EmailNotConfigured:
        raise_error(status.HTTP_503_SERVICE_UNAVAILABLE, "SMTP_NOT_CONFIGURED", "閭鍙戦€佹湇鍔″皻鏈厤缃€?")
    except Exception as exc:
        if str(exc).startswith("LOCK_BUSY"):
            raise_error(status.HTTP_409_CONFLICT, "REGISTER_IN_PROGRESS", "璇ラ偖绠辨鍦ㄥ鐞嗘敞鍐岃姹傘€?")
        raise
    result = {"email": payload.email.lower(), "expires_in_seconds": expires_minutes * 60}
    if expose_debug_email_code():
        result["debug_code"] = code
    return result


@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterPayload,
    request: Request,
    response: Response,
    storage: AppStorage = Depends(get_storage),
    runtime_services: Any = Depends(get_runtime_services),
) -> dict[str, Any]:
    email_key = hashlib.sha256(payload.email.lower().encode("utf-8")).hexdigest()
    if not is_supported_registration_email(payload.email):
        raise_error(status.HTTP_400_BAD_REQUEST, "EMAIL_DOMAIN_UNSUPPORTED", "娉ㄥ唽閭浠呮敮鎸?QQ 閭鍜岀綉鏄撻偖绠便€?")
    if runtime_services.hit_rate_limit(f"rate:register:{email_key}", limit=5, window_seconds=3600):
        raise_error(status.HTTP_429_TOO_MANY_REQUESTS, "REGISTER_RATE_LIMITED", "娉ㄥ唽璇锋眰杩囦簬棰戠箒銆?")
    user_id = new_id()
    access_token = secrets.token_urlsafe(32)
    try:
        with runtime_services.lock(f"lock:register:{email_key}", ttl_seconds=30):
            with storage.connect() as connection:
                verification = row_to_dict(
                    connection.execute(
                        """
                        SELECT * FROM email_verification_codes
                        WHERE email = ? AND purpose = 'register' AND consumed_at IS NULL AND expires_at > ?
                        ORDER BY created_at DESC
                        LIMIT 1
                        """,
                        (payload.email.lower(), utc_now()),
                    ).fetchone()
                )
                if verification is None:
                    raise_error(status.HTTP_400_BAD_REQUEST, "EMAIL_CODE_INVALID", "楠岃瘉鐮侀敊璇垨宸茶繃鏈熴€?")
                if not hmac.compare_digest(
                    verification["code_hash"], hash_registration_code(payload.email, payload.verification_code)
                ):
                    connection.execute(
                        "UPDATE email_verification_codes SET attempt_count = attempt_count + 1 WHERE id = ?",
                        (verification["id"],),
                    )
                    raise_error(status.HTTP_400_BAD_REQUEST, "EMAIL_CODE_INVALID", "楠岃瘉鐮侀敊璇垨宸茶繃鏈熴€?")
                connection.execute(
                    """
                    INSERT INTO users (id, email, email_normalized, username, password_hash, status, email_verified_at)
                    VALUES (?, ?, ?, ?, ?, 'active', CURRENT_TIMESTAMP)
                    """,
                    (user_id, payload.email.lower(), payload.email.lower(), payload.username, hash_password(payload.password)),
                )
                connection.execute(
                    """
                    INSERT INTO user_accounts (user_id, username_snapshot, balance_points, reserved_points)
                    VALUES (?, ?, 0, 0)
                    """,
                    (user_id, payload.username),
                )
                connection.execute(
                    "UPDATE email_verification_codes SET consumed_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (verification["id"],),
                )
                create_access_session(connection, token=access_token, user_id=user_id)
                refresh_token = create_refresh_session(connection, user_id=user_id, request=request)
    except Exception as exc:
        if str(exc).startswith("LOCK_BUSY"):
            raise_error(status.HTTP_409_CONFLICT, "REGISTER_IN_PROGRESS", "璇ラ偖绠辨鍦ㄥ鐞嗘敞鍐岃姹傘€?")
        if "UNIQUE" in str(exc).upper():
            raise_error(status.HTTP_409_CONFLICT, "EMAIL_ALREADY_REGISTERED", "璇ラ偖绠卞凡缁忔敞鍐屻€?")
        raise
    set_refresh_cookie(response, refresh_token)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": public_user(
            {
                "id": user_id,
                "email": payload.email.lower(),
                "username": payload.username,
                "role": "user",
                "status": "active",
                "email_verified_at": utc_now(),
            }
        ),
    }


@router.post("/auth/login")
async def login(
    payload: LoginPayload,
    request: Request,
    response: Response,
    storage: AppStorage = Depends(get_storage),
    runtime_services: Any = Depends(get_runtime_services),
) -> dict[str, Any]:
    email_key = hashlib.sha256(payload.email.lower().encode("utf-8")).hexdigest()
    client_ip = request.client.host if request.client else "unknown"
    if runtime_services.hit_rate_limit(f"rate:login:email:{email_key}", limit=10, window_seconds=900):
        raise_error(status.HTTP_429_TOO_MANY_REQUESTS, "LOGIN_RATE_LIMITED", "鐧诲綍灏濊瘯杩囦簬棰戠箒銆?")
    if runtime_services.hit_rate_limit(f"rate:login:ip:{client_ip}", limit=50, window_seconds=900):
        raise_error(status.HTTP_429_TOO_MANY_REQUESTS, "LOGIN_RATE_LIMITED", "鐧诲綍灏濊瘯杩囦簬棰戠箒銆?")
    with storage.connect() as connection:
        row = connection.execute(
            "SELECT * FROM users WHERE email_normalized = ? OR email = ?",
            (payload.email.lower(), payload.email.lower()),
        ).fetchone()
        user = row_to_dict(row)
        if user is None or not verify_password(payload.password, user["password_hash"]):
            raise_error(status.HTTP_401_UNAUTHORIZED, "INVALID_CREDENTIALS", "閭鎴栧瘑鐮侀敊璇€?")
        if user.get("status") != "active" or not user.get("email_verified_at"):
            raise_error(status.HTTP_403_FORBIDDEN, "EMAIL_NOT_VERIFIED", "閭楠岃瘉鍚庢墠鑳界櫥褰曘€?")
        token = create_access_session(connection, user_id=user["id"])
        refresh_token = create_refresh_session(connection, user_id=user["id"], request=request)
    set_refresh_cookie(response, refresh_token)
    return {"access_token": token, "token_type": "bearer", "user": public_user(user)}


@router.post("/auth/password-reset-code", status_code=status.HTTP_202_ACCEPTED)
async def send_password_reset_code(
    payload: PasswordResetCodePayload,
    storage: AppStorage = Depends(get_storage),
    runtime_services: Any = Depends(get_runtime_services),
) -> dict[str, Any]:
    email_key = hashlib.sha256(payload.email.lower().encode("utf-8")).hexdigest()
    if not is_supported_registration_email(payload.email):
        raise_error(status.HTTP_400_BAD_REQUEST, "EMAIL_DOMAIN_UNSUPPORTED", "Email domain is not supported.")
    if runtime_services.hit_rate_limit(f"rate:password-reset-code:{email_key}", limit=5, window_seconds=3600):
        raise_error(status.HTTP_429_TOO_MANY_REQUESTS, "EMAIL_CODE_RATE_LIMITED", "Password reset code requested too often.")

    code = f"{secrets.randbelow(1_000_000):06d}"
    expires_minutes = registration_code_expire_minutes()
    result = {"email": payload.email.lower(), "expires_in_seconds": expires_minutes * 60}
    try:
        with runtime_services.lock(f"lock:password-reset:{email_key}", ttl_seconds=30):
            with storage.connect() as connection:
                user = connection.execute(
                    "SELECT id FROM users WHERE email_normalized = ? OR email = ?",
                    (payload.email.lower(), payload.email.lower()),
                ).fetchone()
                if user is None:
                    return result
                connection.execute(
                    """
                    UPDATE email_verification_codes
                    SET consumed_at = CURRENT_TIMESTAMP
                    WHERE email = ? AND purpose = 'password_reset' AND consumed_at IS NULL
                    """,
                    (payload.email.lower(),),
                )
                connection.execute(
                    """
                    INSERT INTO email_verification_codes (id, email, code_hash, purpose, expires_at)
                    VALUES (?, ?, ?, 'password_reset', ?)
                    """,
                    (
                        new_id(),
                        payload.email.lower(),
                        hash_password_reset_code(payload.email, code),
                        utc_after(minutes=expires_minutes),
                    ),
                )
        send_registration_code_email(payload.email, code, expires_minutes=expires_minutes, purpose="password_reset")
    except EmailNotConfigured:
        raise_error(status.HTTP_503_SERVICE_UNAVAILABLE, "SMTP_NOT_CONFIGURED", "Email service is not configured.")
    except Exception as exc:
        if str(exc).startswith("LOCK_BUSY"):
            raise_error(status.HTTP_409_CONFLICT, "PASSWORD_RESET_IN_PROGRESS", "Password reset is already in progress.")
        raise

    if expose_debug_email_code():
        result["debug_code"] = code
    return result


@router.post("/auth/reset-password")
async def reset_password(
    payload: PasswordResetPayload,
    storage: AppStorage = Depends(get_storage),
) -> dict[str, str]:
    if not is_supported_registration_email(payload.email):
        raise_error(status.HTTP_400_BAD_REQUEST, "EMAIL_DOMAIN_UNSUPPORTED", "Email domain is not supported.")
    with storage.connect() as connection:
        user = row_to_dict(
            connection.execute(
                "SELECT * FROM users WHERE email_normalized = ? OR email = ?",
                (payload.email.lower(), payload.email.lower()),
            ).fetchone()
        )
        if user is None:
            raise_error(status.HTTP_400_BAD_REQUEST, "EMAIL_CODE_INVALID", "Password reset code is invalid or expired.")
        verification = row_to_dict(
            connection.execute(
                """
                SELECT * FROM email_verification_codes
                WHERE email = ? AND purpose = 'password_reset' AND consumed_at IS NULL AND expires_at > ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (payload.email.lower(), utc_now()),
            ).fetchone()
        )
        if verification is None:
            raise_error(status.HTTP_400_BAD_REQUEST, "EMAIL_CODE_INVALID", "Password reset code is invalid or expired.")
        if not hmac.compare_digest(
            verification["code_hash"], hash_password_reset_code(payload.email, payload.verification_code)
        ):
            connection.execute(
                "UPDATE email_verification_codes SET attempt_count = attempt_count + 1 WHERE id = ?",
                (verification["id"],),
            )
            raise_error(status.HTTP_400_BAD_REQUEST, "EMAIL_CODE_INVALID", "Password reset code is invalid or expired.")
        connection.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(payload.new_password), user["id"]),
        )
        connection.execute(
            "UPDATE email_verification_codes SET consumed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (verification["id"],),
        )
        connection.execute(
            "UPDATE refresh_sessions SET revoked_at = CURRENT_TIMESTAMP WHERE user_id = ? AND revoked_at IS NULL",
            (user["id"],),
        )
        connection.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
    return {"email": payload.email.lower(), "status": "password_reset"}


@router.post("/auth/refresh")
async def refresh_access_token(
    request: Request,
    response: Response,
    storage: AppStorage = Depends(get_storage),
) -> dict[str, Any]:
    refresh_token = request.cookies.get(refresh_cookie_name())
    if not refresh_token:
        raise_error(status.HTTP_401_UNAUTHORIZED, "REFRESH_REQUIRED", "鐧诲綍宸茶繃鏈燂紝璇烽噸鏂扮櫥褰曘€?")
    with storage.connect() as connection:
        session = row_to_dict(
            connection.execute(
                """
                SELECT refresh_sessions.*, users.email, users.username, users.role, users.status, users.email_verified_at
                FROM refresh_sessions
                JOIN users ON users.id = refresh_sessions.user_id
                WHERE refresh_sessions.refresh_token_hash = ?
                  AND refresh_sessions.revoked_at IS NULL
                  AND refresh_sessions.expires_at > ?
                """,
                (hash_token(refresh_token), utc_now()),
            ).fetchone()
        )
        if session is None or session.get("status") != "active":
            clear_refresh_cookie(response)
            raise_error(status.HTTP_401_UNAUTHORIZED, "REFRESH_INVALID", "鐧诲綍宸茶繃鏈燂紝璇烽噸鏂扮櫥褰曘€?")
        access_token = create_access_session(connection, user_id=session["user_id"])
        connection.execute(
            "UPDATE refresh_sessions SET expires_at = ? WHERE id = ?",
            (utc_after(days=refresh_token_expire_days()), session["id"]),
        )
    set_refresh_cookie(response, refresh_token)
    return {"access_token": access_token, "token_type": "bearer", "user": public_user({"id": session["user_id"], **session})}


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, storage: AppStorage = Depends(get_storage)) -> Response:
    refresh_token = request.cookies.get(refresh_cookie_name())
    if refresh_token:
        with storage.connect() as connection:
            connection.execute(
                "UPDATE refresh_sessions SET revoked_at = CURRENT_TIMESTAMP WHERE refresh_token_hash = ? AND revoked_at IS NULL",
                (hash_token(refresh_token),),
            )
    clear_refresh_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/users/me")
async def me(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return public_user(user)


@router.post("/products", status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreatePayload,
    user: dict[str, Any] = Depends(current_user),
    storage: AppStorage = Depends(get_storage),
    runtime_services: Any = Depends(get_runtime_services),
) -> dict[str, Any]:
    product_id = new_id()
    with storage.connect() as connection:
        connection.execute(
            """
            INSERT INTO products
                (id, user_id, name, brand, model, category, material, color, description, specs_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                product_id,
                user["id"],
                payload.name,
                payload.brand,
                payload.model,
                payload.category,
                payload.material,
                payload.color,
                payload.description,
                json_dumps([spec.model_dump() for spec in payload.specs]),
            ),
        )
    runtime_services.delete_cache(products_cache_key(user["id"]))
    return get_product_payload(storage, product_id, user["id"])


@router.get("/products")
async def list_products(
    user: dict[str, Any] = Depends(current_user),
    storage: AppStorage = Depends(get_storage),
    runtime_services: Any = Depends(get_runtime_services),
) -> dict[str, Any]:
    cache_key = products_cache_key(user["id"])
    cached = runtime_services.get_cache_json(cache_key)
    if cached is not None:
        return cached
    with storage.connect() as connection:
        rows = connection.execute(
            "SELECT * FROM products WHERE user_id = ? AND deleted_at IS NULL ORDER BY created_at DESC",
            (user["id"],),
        ).fetchall()
    payload = {"items": [product_payload(dict(row)) for row in rows]}
    runtime_services.set_cache_json(cache_key, payload, ttl_seconds=60)
    return payload


@router.post("/uploads/presign", status_code=status.HTTP_201_CREATED)
async def presign_upload(
    payload: UploadPresignPayload,
    user: dict[str, Any] = Depends(current_user),
    storage: AppStorage = Depends(get_storage),
) -> dict[str, Any]:
    upload_token = secrets.token_urlsafe(32)
    safe_filename = Path(payload.filename).name
    object_key = material_object_key(user_id=user["id"], upload_token=upload_token, filename=safe_filename)
    with storage.connect() as connection:
        connection.execute(
            """
            INSERT INTO upload_sessions
                (upload_token, user_id, asset_type, filename, requested_content_type,
                 requested_size_bytes, object_key)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                upload_token,
                user["id"],
                payload.asset_type,
                safe_filename,
                payload.content_type,
                payload.size_bytes,
                object_key,
            ),
        )
    return {
        "upload_token": upload_token,
        "upload_url": f"/api/v1/uploads/local/{upload_token}",
        "method": "PUT",
        "headers": {"Content-Type": payload.content_type},
        "object_key": object_key,
        "expires_in_seconds": 900,
    }


@router.put("/uploads/local/{upload_token}", status_code=status.HTTP_204_NO_CONTENT)
async def put_local_upload(
    upload_token: str,
    request: Request,
    storage: AppStorage = Depends(get_storage),
) -> Response:
    with storage.connect() as connection:
        upload = row_to_dict(
            connection.execute("SELECT * FROM upload_sessions WHERE upload_token = ?", (upload_token,)).fetchone()
        )
    if upload is None or upload["status"] not in {"pending", "uploaded"}:
        raise_error(status.HTTP_404_NOT_FOUND, "UPLOAD_SESSION_NOT_FOUND", "涓婁紶浼氳瘽涓嶅瓨鍦ㄦ垨宸插畬鎴愩€?")

    content = await request.body()
    if not content:
        raise_error(HTTP_422, "UPLOAD_FILE_EMPTY", "涓婁紶鏂囦欢涓虹┖銆?")
    if len(content) > MAX_UPLOAD_BYTES or len(content) > int(upload["requested_size_bytes"]):
        raise_error(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "UPLOAD_FILE_TOO_LARGE", "涓婁紶鏂囦欢瓒呰繃闄愬埗銆?")

    target = storage.upload_dir / f"{upload_token}.upload"
    target.write_bytes(content)
    received_content_type = request.headers.get("content-type", upload["requested_content_type"]).split(";")[0].lower()
    with storage.connect() as connection:
        connection.execute(
            """
            UPDATE upload_sessions
            SET file_path = ?, received_content_type = ?, received_size_bytes = ?, status = 'uploaded'
            WHERE upload_token = ?
            """,
            (str(target), received_content_type, len(content), upload_token),
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/uploads/complete", status_code=status.HTTP_201_CREATED)
async def complete_upload(
    payload: UploadCompletePayload,
    user: dict[str, Any] = Depends(current_user),
    storage: AppStorage = Depends(get_storage),
) -> dict[str, Any]:
    with storage.connect() as connection:
        upload = row_to_dict(
            connection.execute(
                "SELECT * FROM upload_sessions WHERE upload_token = ? AND user_id = ?",
                (payload.upload_token, user["id"]),
            ).fetchone()
        )
    if upload is None:
        raise_error(status.HTTP_404_NOT_FOUND, "UPLOAD_SESSION_NOT_FOUND", "涓婁紶浼氳瘽涓嶅瓨鍦ㄦ垨鏃犳潈璁块棶銆?")
    if upload["status"] != "uploaded" or not upload["file_path"]:
        raise_error(status.HTTP_409_CONFLICT, "UPLOAD_NOT_FINISHED", "鏂囦欢灏氭湭涓婁紶瀹屾垚銆?")

    product_id = payload.product_id
    if upload["asset_type"].startswith("product_"):
        if not product_id:
            raise_error(HTTP_422, "PRODUCT_ID_REQUIRED", "鍟嗗搧绱犳潗蹇呴』缁戝畾鍟嗗搧銆?")
        if get_owned_row(storage, "products", product_id, user["id"]) is None:
            raise_access_denied()

    normalized = normalize_uploaded_image(Path(upload["file_path"]), upload["received_content_type"] or upload["requested_content_type"])
    asset_id = new_id()
    version_id = new_id()
    target_dir = storage.asset_dir / user["id"] / asset_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{version_id}.png"
    target_path.write_bytes(normalized["bytes"])

    with storage.connect() as connection:
        connection.execute(
            """
            INSERT INTO assets (id, user_id, product_id, project_id, asset_type)
            VALUES (?, ?, ?, ?, ?)
            """,
            (asset_id, user["id"], product_id, payload.project_id, upload["asset_type"]),
        )
        connection.execute(
            """
            INSERT INTO asset_versions
                (id, asset_id, user_id, version, filename, content_type, file_path,
                 size_bytes, width, height, sha256)
            VALUES (?, ?, ?, 1, ?, 'image/png', ?, ?, ?, ?, ?)
            """,
            (
                version_id,
                asset_id,
                user["id"],
                upload["filename"],
                str(target_path),
                len(normalized["bytes"]),
                normalized["width"],
                normalized["height"],
                normalized["sha256"],
            ),
        )
        connection.execute(
            "UPDATE upload_sessions SET status = 'completed', completed_at = CURRENT_TIMESTAMP WHERE upload_token = ?",
            (payload.upload_token,),
        )
    return get_asset_version_payload(storage, version_id, user["id"])


@router.post("/barcodes/validate")
async def validate_barcode(
    payload: BarcodePayload,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    result = validate_barcode_value(payload.barcode_type, payload.raw_value)
    return result.__dict__


@router.post("/projects", status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreatePayload,
    user: dict[str, Any] = Depends(current_user),
    storage: AppStorage = Depends(get_storage),
) -> dict[str, Any]:
    product = get_owned_row(storage, "products", payload.product_id, user["id"])
    if product is None:
        raise_access_denied()

    barcode = validate_barcode_value(payload.barcode.barcode_type, payload.barcode.raw_value)
    if not payload.barcode.confirmed or not barcode.can_confirm:
        raise_error(HTTP_422, "BARCODE_NOT_CONFIRMED", "鏉″舰鐮佸皻鏈‘璁ゃ€?")

    project_id = new_id()
    with storage.connect() as connection:
        connection.execute(
            """
            INSERT INTO projects
                (id, user_id, product_id, name, style_config_json, certificate_config_json,
                 package_config_json, detail_config_json, barcode_type, barcode_value, barcode_confirmed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                project_id,
                user["id"],
                product["id"],
                payload.name,
                json_dumps(payload.style_config),
                json_dumps(payload.certificate_config),
                json_dumps(payload.package_config),
                json_dumps(payload.detail_config),
                payload.barcode.barcode_type.value,
                barcode.normalized_value,
            ),
        )
    return get_project_payload(storage, project_id, user["id"])


@router.get("/projects")
async def list_projects(
    user: dict[str, Any] = Depends(current_user),
    storage: AppStorage = Depends(get_storage),
) -> dict[str, Any]:
    with storage.connect() as connection:
        rows = connection.execute(
            "SELECT * FROM projects WHERE user_id = ? AND deleted_at IS NULL ORDER BY created_at DESC",
            (user["id"],),
        ).fetchall()
    return {"items": [project_payload(dict(row)) for row in rows]}


@router.post("/projects/{project_id}/generate", status_code=status.HTTP_202_ACCEPTED)
async def generate_project(
    project_id: str,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
    storage: AppStorage = Depends(get_storage),
    runtime_services: Any = Depends(get_runtime_services),
) -> dict[str, Any]:
    project = get_owned_row(storage, "projects", project_id, user["id"])
    if project is None:
        raise_access_denied()
    product = get_owned_row(storage, "products", project["product_id"], user["id"])
    if product is None:
        raise_access_denied()
    if not project["barcode_confirmed"]:
        raise_error(HTTP_422, "BARCODE_NOT_CONFIRMED", "鏉″舰鐮佸皻鏈‘璁ゃ€?")

    source_asset = get_latest_product_original_asset(storage, product["id"], user["id"])
    if source_asset is None:
        raise_error(
            HTTP_422,
            "PRODUCT_ORIGINAL_ASSET_REQUIRED",
            "Product original asset is required before generation.",
        )

    try:
        with runtime_services.lock(f"lock:generation:user:{user['id']}", ttl_seconds=10):
            existing_job = active_project_generation_job(storage, project_id=project_id, user_id=user["id"])
            if existing_job is not None:
                notify_generation_queue(request)
                return existing_job

            max_active_jobs = configured_positive_int("MAX_ACTIVE_JOBS_PER_USER", 3)
            if active_generation_job_count(storage, user["id"]) >= max_active_jobs:
                raise_error(status.HTTP_429_TOO_MANY_REQUESTS, "ACTIVE_JOB_LIMIT_REACHED", "Generation active job limit reached.")

            if queued_generation_job_count(storage) >= configured_positive_int("MAX_QUEUE_DEPTH", 1000):
                raise_error(status.HTTP_429_TOO_MANY_REQUESTS, "GENERATION_QUEUE_FULL", "Generation queue is full.")

            job = create_queued_generation_job(
                project_id=project_id,
                user=user,
                product=product,
                project=project,
                source_asset=source_asset,
                storage=storage,
            )
            notify_generation_queue(request)
            return job
    except RuntimeError as exc:
        if str(exc).startswith("LOCK_BUSY"):
            raise_error(status.HTTP_429_TOO_MANY_REQUESTS, "ACTIVE_JOB_LIMIT_REACHED", "Generation active job limit reached.")
        raise

    max_active_jobs = configured_positive_int("MAX_ACTIVE_JOBS_PER_USER", 3)
    if active_generation_job_count(storage, user["id"]) >= max_active_jobs:
        raise_error(status.HTTP_429_TOO_MANY_REQUESTS, "ACTIVE_JOB_LIMIT_REACHED", "褰撳墠璐﹀彿鐢熸垚浠诲姟杩囧锛岃绋嶅悗鍐嶈瘯銆?")

    try:
        with runtime_services.slot(f"slot:user:generation:{user['id']}", limit=max_active_jobs, ttl_seconds=generation_slot_ttl()):
            return run_generation_job(
                project_id=project_id,
                user=user,
                product=product,
                project=project,
                source_asset=source_asset,
                storage=storage,
                runtime_services=runtime_services,
            )
    except RuntimeError as exc:
        if str(exc).startswith("SLOT_BUSY"):
            raise_error(status.HTTP_429_TOO_MANY_REQUESTS, "ACTIVE_JOB_LIMIT_REACHED", "褰撳墠璐﹀彿鐢熸垚浠诲姟杩囧锛岃绋嶅悗鍐嶈瘯銆?")
        raise


@router.get("/generation-jobs/{job_id}")
async def get_generation_job(
    job_id: str,
    user: dict[str, Any] = Depends(current_user),
    storage: AppStorage = Depends(get_storage),
) -> dict[str, Any]:
    return get_job_payload(storage, job_id, user["id"])


@router.get("/projects/{project_id}/outputs")
async def list_project_outputs(
    project_id: str,
    user: dict[str, Any] = Depends(current_user),
    storage: AppStorage = Depends(get_storage),
) -> dict[str, Any]:
    if get_owned_row(storage, "projects", project_id, user["id"]) is None:
        raise_access_denied()
    recover_existing_project_outputs(storage, project_id=project_id, user_id=user["id"])
    return {"items": list_outputs(storage, project_id=project_id, user_id=user["id"])}


@router.get("/gallery/outputs")
async def list_gallery_outputs(
    limit: int = Query(30, ge=1, le=60),
    cursor: str | None = Query(None),
    user: dict[str, Any] = Depends(current_user),
    storage: AppStorage = Depends(get_storage),
) -> dict[str, Any]:
    # Gallery history is account-scoped: every output row is filtered by the authenticated user's id.
    offset = gallery_cursor_offset(cursor)
    rows = list_outputs(storage, user_id=user["id"], passed_only=True, newest_first=True, limit=limit + 1, offset=offset)
    items = rows[:limit]
    next_cursor = str(offset + limit) if len(rows) > limit else None
    return {"items": items, "next_cursor": next_cursor}


@router.get("/outputs/{output_id}/download")
async def download_output(
    output_id: str,
    user: dict[str, Any] = Depends(current_user),
    storage: AppStorage = Depends(get_storage),
) -> FileResponse:
    output = get_owned_row(storage, "generation_outputs", output_id, user["id"])
    if output is None:
        raise_access_denied()
    if output["quality_status"] != "passed":
        raise_error(status.HTTP_409_CONFLICT, "QUALITY_REVIEW_REQUIRED", "璐ㄦ鏈€氳繃鐨勫浘鐗囦笉鑳戒笅杞姐€?")
    path = Path(output["file_path"])
    if not path.exists():
        raise_error(status.HTTP_404_NOT_FOUND, "OUTPUT_FILE_NOT_FOUND", "杈撳嚭鏂囦欢涓嶅瓨鍦ㄣ€?")
    return FileResponse(
        path,
        media_type="image/png",
        filename=f"{output['output_type']}.png",
        headers=output_cache_headers(output),
    )


@router.get("/outputs/{output_id}/thumbnail")
async def thumbnail_output(
    output_id: str,
    user: dict[str, Any] = Depends(current_user),
    storage: AppStorage = Depends(get_storage),
) -> FileResponse:
    output = get_owned_row(storage, "generation_outputs", output_id, user["id"])
    if output is None:
        raise_access_denied()
    if output["quality_status"] != "passed":
        raise_error(status.HTTP_409_CONFLICT, "QUALITY_REVIEW_REQUIRED", "璐ㄦ鏈€氳繃鐨勫浘鐗囦笉鑳戒笅杞姐€?")
    path = Path(output["file_path"])
    if not path.exists():
        raise_error(status.HTTP_404_NOT_FOUND, "OUTPUT_FILE_NOT_FOUND", "杈撳嚭鏂囦欢涓嶅瓨鍦ㄣ€?")
    thumbnail_path = ensure_output_thumbnail(path)
    return FileResponse(
        thumbnail_path,
        media_type="image/png",
        filename=f"{output['output_type']}-thumb.png",
        headers=output_cache_headers(output),
    )


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["id"],
        "email": user["email"],
        "username": user.get("username", ""),
        "role": user.get("role", "user"),
        "status": user.get("status", "active"),
        "email_verified": bool(user.get("email_verified_at")),
    }


def create_access_session(connection: Any, *, user_id: str, token: str | None = None) -> str:
    access_token = token or secrets.token_urlsafe(32)
    connection.execute(
        "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
        (access_token, user_id, utc_after(days=refresh_token_expire_days())),
    )
    return access_token


def create_refresh_session(connection: Any, *, user_id: str, request: Request) -> str:
    refresh_token = secrets.token_urlsafe(48)
    expires_at = utc_after(days=refresh_token_expire_days())
    # Store only a hash of the refresh token so a database leak cannot be used to log in directly.
    connection.execute(
        """
        INSERT INTO refresh_sessions
            (id, user_id, refresh_token_hash, device_id, ip_address, user_agent, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_id(),
            user_id,
            hash_token(refresh_token),
            request.headers.get("x-device-id", ""),
            request.client.host if request.client else "",
            request.headers.get("user-agent", ""),
            expires_at,
        ),
    )
    return refresh_token


def set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        refresh_cookie_name(),
        refresh_token,
        max_age=refresh_token_expire_days() * 24 * 60 * 60,
        httponly=True,
        secure=cookie_secure(),
        samesite=cookie_samesite(),
        path="/api/v1/auth",
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(refresh_cookie_name(), path="/api/v1/auth")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_registration_code(email: str, code: str) -> str:
    return hash_email_code(email, code, purpose="register")


def hash_password_reset_code(email: str, code: str) -> str:
    return hash_email_code(email, code, purpose="password_reset")


def hash_email_code(email: str, code: str, *, purpose: str) -> str:
    return hash_token(f"{email.lower()}:{code.strip()}:{purpose}")


def is_supported_registration_email(email: str) -> bool:
    domain = email.rsplit("@", 1)[-1].lower()
    return domain in registration_email_domains()


def registration_email_domains() -> set[str]:
    raw_domains = os.getenv("EMAIL_ALLOWED_DOMAINS", "qq.com,163.com,126.com,yeah.net")
    return {domain.strip().lower() for domain in raw_domains.split(",") if domain.strip()}


def expose_debug_email_code() -> bool:
    return os.getenv("APP_ENV", "development").strip().lower() != "production"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_after(*, minutes: int = 0, days: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes, days=days)).isoformat()


def registration_code_expire_minutes() -> int:
    return int(os.getenv("REGISTRATION_CODE_EXPIRE_MINUTES", "10"))


def refresh_token_expire_days() -> int:
    return int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))


def cookie_secure() -> bool:
    return os.getenv("COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes"}


def cookie_samesite() -> str:
    value = os.getenv("COOKIE_SAMESITE", "lax").strip().lower()
    return value if value in {"lax", "strict", "none"} else "lax"


def refresh_cookie_name() -> str:
    return os.getenv("REFRESH_COOKIE_NAME", REFRESH_COOKIE_NAME)


def products_cache_key(user_id: str) -> str:
    return f"cache:products:{user_id}"


def gallery_cache_key(user_id: str) -> str:
    return f"cache:gallery:outputs:{user_id}"


def configured_positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def generation_slot_ttl() -> int:
    return configured_positive_int("GENERATION_SLOT_TTL_SECONDS", 900)


def active_generation_job_count(storage: AppStorage, user_id: str) -> int:
    with storage.connect() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM generation_jobs
            WHERE user_id = ? AND status IN ('queued', 'running')
            """,
            (user_id,),
        ).fetchone()
    return int(row["count"] if row is not None else 0)


def queued_generation_job_count(storage: AppStorage) -> int:
    with storage.connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM generation_jobs WHERE status = 'queued'"
        ).fetchone()
    return int(row["count"] if row is not None else 0)


def active_project_generation_job(storage: AppStorage, *, project_id: str, user_id: str) -> dict[str, Any] | None:
    with storage.connect() as connection:
        row = connection.execute(
            """
            SELECT id FROM generation_jobs
            WHERE project_id = ? AND user_id = ? AND status IN ('queued', 'running')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (project_id, user_id),
        ).fetchone()
    if row is None:
        return None
    return get_job_payload(storage, row["id"], user_id)


def notify_generation_queue(request: Request) -> None:
    queue = getattr(request.app.state, "generation_queue", None)
    if queue is not None:
        queue.notify()


def create_queued_generation_job(
    *,
    project_id: str,
    user: dict[str, Any],
    product: dict[str, Any],
    project: dict[str, Any],
    source_asset: dict[str, Any],
    storage: AppStorage,
) -> dict[str, Any]:
    job_id = new_id()
    provider = build_image_generation_provider()
    try:
        reserve_generation_charge(storage, user=user, job_id=job_id)
    except InsufficientBalance as exc:
        raise_error(
            status.HTTP_402_PAYMENT_REQUIRED,
            "INSUFFICIENT_BALANCE",
            f"Insufficient balance: required {exc.required_points}, available {exc.available_points}.",
        )
    with storage.connect() as connection:
        connection.execute(
            """
            INSERT INTO generation_jobs
                (id, user_id, project_id, status, provider_name, source_asset_version_id)
            VALUES (?, ?, ?, 'queued', ?, ?)
            """,
            (job_id, user["id"], project_id, provider.name, source_asset["version_id"]),
        )
        connection.execute("UPDATE projects SET status = 'generating', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,))
    return get_job_payload(storage, job_id, user["id"])


def process_next_queued_generation_job(storage: AppStorage, runtime_services: Any) -> bool:
    job_id = claim_next_queued_generation_job(storage)
    if job_id is None:
        return False
    return execute_claimed_generation_job(job_id=job_id, storage=storage, runtime_services=runtime_services)


def claim_next_queued_generation_job(storage: AppStorage) -> str | None:
    with storage.connect() as connection:
        row = connection.execute(
            """
            SELECT id, project_id
            FROM generation_jobs
            WHERE status = 'queued'
            ORDER BY created_at ASC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        updated = connection.execute(
            """
            UPDATE generation_jobs
            SET status = 'running', error_code = NULL, error_message = NULL
            WHERE id = ? AND status = 'queued'
            """,
            (row["id"],),
        )
        if updated.rowcount != 1:
            return None
        connection.execute("UPDATE projects SET status = 'generating', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (row["project_id"],))
        return row["id"]


def execute_claimed_generation_job(*, job_id: str, storage: AppStorage, runtime_services: Any) -> bool:
    context = generation_job_context(storage, job_id=job_id)
    if context is None:
        return True
    user = context["user"]
    project = context["project"]
    product = context["product"]
    source_asset = context["source_asset"]
    product_for_image = product_payload(product)
    project_for_image = project_payload(project)
    provider = build_image_generation_provider()

    try:
        with runtime_services.slot(
            "slot:provider:generation",
            limit=configured_positive_int("PROVIDER_MAX_CONCURRENCY", 2),
            ttl_seconds=generation_slot_ttl(),
        ):
            generated = provider.generate_five_images(
                output_dir=storage.output_dir,
                job_id=job_id,
                product=product_for_image,
                project=project_for_image,
                source_image_path=Path(source_asset["file_path"]),
            )
    except Exception as exc:
        if str(exc).startswith("SLOT_BUSY"):
            requeue_generation_job(storage, job_id=job_id, user_id=user["id"], project_id=project["id"])
            return False
        message = str(exc)
        logger.exception("Image provider failed for job_id=%s project_id=%s provider=%s", job_id, project["id"], provider.name)
        with storage.connect() as connection:
            record_existing_output_files(
                connection,
                output_dir=storage.output_dir,
                job_id=job_id,
                user_id=user["id"],
                project_id=project["id"],
                source_asset_version_id=source_asset["version_id"],
            )
            connection.execute(
                """
                UPDATE generation_jobs
                SET status = 'failed',
                    completed_at = CURRENT_TIMESTAMP,
                    error_code = ?,
                    error_message = ?
                WHERE id = ? AND user_id = ?
                """,
                ("IMAGE_PROVIDER_FAILED", _clip_error_message(message), job_id, user["id"]),
            )
            connection.execute("UPDATE projects SET status = 'failed', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project["id"],))
        release_generation_hold(storage, user_id=user["id"], job_id=job_id, remark="Generation failed; reserved points released.")
        runtime_services.delete_cache(gallery_cache_key(user["id"]))
        return True

    with storage.connect() as connection:
        connection.execute(
            """
            UPDATE generation_jobs
            SET status = 'completed',
                completed_at = CURRENT_TIMESTAMP,
                error_code = NULL,
                error_message = NULL
            WHERE id = ? AND user_id = ?
            """,
            (job_id, user["id"]),
        )
        for image in generated:
            insert_generation_output(
                connection,
                user_id=user["id"],
                project_id=project["id"],
                job_id=job_id,
                output_type=image.output_type,
                width=image.width,
                height=image.height,
                file_path=image.path,
                source_asset_version_id=source_asset["version_id"],
            )
        connection.execute("UPDATE projects SET status = 'completed', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project["id"],))
        output_count = int(
            connection.execute(
                "SELECT COUNT(*) AS count FROM generation_outputs WHERE job_id = ? AND user_id = ?",
                (job_id, user["id"]),
            ).fetchone()["count"]
        )

    if output_count >= len(OUTPUT_SPECS):
        charge_generation_hold(storage, user_id=user["id"], job_id=job_id)
    else:
        release_generation_hold(storage, user_id=user["id"], job_id=job_id, remark="Generation produced too few outputs; reserved points released.")

    runtime_services.delete_cache(gallery_cache_key(user["id"]))
    return True


def requeue_generation_job(storage: AppStorage, *, job_id: str, user_id: str, project_id: str) -> None:
    with storage.connect() as connection:
        connection.execute(
            """
            UPDATE generation_jobs
            SET status = 'queued'
            WHERE id = ? AND user_id = ? AND status = 'running'
            """,
            (job_id, user_id),
        )
        connection.execute("UPDATE projects SET status = 'generating', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,))


def generation_job_context(storage: AppStorage, *, job_id: str) -> dict[str, dict[str, Any]] | None:
    with storage.connect() as connection:
        job = row_to_dict(connection.execute("SELECT * FROM generation_jobs WHERE id = ?", (job_id,)).fetchone())
        if job is None:
            return None
        user = row_to_dict(connection.execute("SELECT * FROM users WHERE id = ?", (job["user_id"],)).fetchone())
        project = row_to_dict(
            connection.execute(
                "SELECT * FROM projects WHERE id = ? AND user_id = ?",
                (job["project_id"], job["user_id"]),
            ).fetchone()
        )
        if user is None or project is None:
            return None
        product = row_to_dict(
            connection.execute(
                "SELECT * FROM products WHERE id = ? AND user_id = ?",
                (project["product_id"], job["user_id"]),
            ).fetchone()
        )
        source_asset = row_to_dict(
            connection.execute(
                """
                SELECT
                    assets.id AS asset_id,
                    assets.asset_type,
                    asset_versions.id AS version_id,
                    asset_versions.file_path,
                    asset_versions.width,
                    asset_versions.height,
                    asset_versions.sha256
                FROM asset_versions
                JOIN assets ON assets.id = asset_versions.asset_id
                WHERE asset_versions.id = ? AND asset_versions.user_id = ?
                """,
                (job["source_asset_version_id"], job["user_id"]),
            ).fetchone()
        )
    if product is None or source_asset is None:
        mark_generation_job_failed(
            storage,
            job_id=job_id,
            user_id=job["user_id"],
            project_id=job["project_id"],
            error_code="GENERATION_CONTEXT_MISSING",
            error_message="Generation context is missing.",
        )
        return None
    return {"job": job, "user": user, "project": project, "product": product, "source_asset": source_asset}


def run_generation_job(
    *,
    project_id: str,
    user: dict[str, Any],
    product: dict[str, Any],
    project: dict[str, Any],
    source_asset: dict[str, Any],
    storage: AppStorage,
    runtime_services: Any,
) -> dict[str, Any]:
    job_id = new_id()
    product_for_image = product_payload(product)
    project_for_image = project_payload(project)
    provider = build_image_generation_provider()
    try:
        reserve_generation_charge(storage, user=user, job_id=job_id)
    except InsufficientBalance as exc:
        raise_error(
            status.HTTP_402_PAYMENT_REQUIRED,
            "INSUFFICIENT_BALANCE",
            f"Insufficient balance: required {exc.required_points}, available {exc.available_points}.",
        )
    with storage.connect() as connection:
        connection.execute(
            """
            INSERT INTO generation_jobs
                (id, user_id, project_id, status, provider_name, source_asset_version_id)
            VALUES (?, ?, ?, 'queued', ?, ?)
            """,
            (job_id, user["id"], project_id, provider.name, source_asset["version_id"]),
        )
        connection.execute("UPDATE projects SET status = 'generating', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,))

    try:
        with runtime_services.slot(
            "slot:provider:generation",
            limit=configured_positive_int("PROVIDER_MAX_CONCURRENCY", 2),
            ttl_seconds=generation_slot_ttl(),
        ):
            with storage.connect() as connection:
                connection.execute(
                    "UPDATE generation_jobs SET status = 'running' WHERE id = ? AND user_id = ?",
                    (job_id, user["id"]),
                )
            generated = provider.generate_five_images(
                output_dir=storage.output_dir,
                job_id=job_id,
                product=product_for_image,
                project=project_for_image,
                source_image_path=Path(source_asset["file_path"]),
            )
    except Exception as exc:
        if str(exc).startswith("SLOT_BUSY"):
            mark_generation_job_failed(
                storage,
                job_id=job_id,
                user_id=user["id"],
                project_id=project_id,
                error_code="PROVIDER_BUSY",
                error_message="Provider concurrency limit reached.",
            )
            raise_error(status.HTTP_429_TOO_MANY_REQUESTS, "PROVIDER_BUSY", "褰撳墠鐢熸垚闃熷垪绻佸繖锛岃绋嶅悗鍐嶈瘯銆?")
        message = str(exc)
        logger.exception("Image provider failed for job_id=%s project_id=%s provider=%s", job_id, project_id, provider.name)
        with storage.connect() as connection:
            record_existing_output_files(
                connection,
                output_dir=storage.output_dir,
                job_id=job_id,
                user_id=user["id"],
                project_id=project_id,
                source_asset_version_id=source_asset["version_id"],
            )
            connection.execute(
                """
                UPDATE generation_jobs
                SET status = 'failed',
                    completed_at = CURRENT_TIMESTAMP,
                    error_code = ?,
                    error_message = ?
                WHERE id = ? AND user_id = ?
                """,
                ("IMAGE_PROVIDER_FAILED", _clip_error_message(message), job_id, user["id"]),
            )
            connection.execute("UPDATE projects SET status = 'failed', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,))
        release_generation_hold(storage, user_id=user["id"], job_id=job_id, remark="鐢熸垚澶辫触锛岄噴鏀鹃鍗犵偣鏁?")
        release_generation_hold(storage, user_id=user["id"], job_id=job_id, remark="Generation failed; reserved points released.")
        raise_error(status.HTTP_502_BAD_GATEWAY, "IMAGE_PROVIDER_FAILED", message)

    with storage.connect() as connection:
        connection.execute(
            """
            UPDATE generation_jobs
            SET status = 'completed',
                completed_at = CURRENT_TIMESTAMP,
                error_code = NULL,
                error_message = NULL
            WHERE id = ? AND user_id = ?
            """,
            (job_id, user["id"]),
        )
        for image in generated:
            insert_generation_output(
                connection,
                user_id=user["id"],
                project_id=project_id,
                job_id=job_id,
                output_type=image.output_type,
                width=image.width,
                height=image.height,
                file_path=image.path,
                source_asset_version_id=source_asset["version_id"],
            )
        connection.execute("UPDATE projects SET status = 'completed', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,))
        output_count = int(
            connection.execute(
                "SELECT COUNT(*) AS count FROM generation_outputs WHERE job_id = ? AND user_id = ?",
                (job_id, user["id"]),
            ).fetchone()["count"]
        )

    if output_count >= len(OUTPUT_SPECS):
        charge_generation_hold(storage, user_id=user["id"], job_id=job_id)
    else:
        release_generation_hold(storage, user_id=user["id"], job_id=job_id, remark="鐢熸垚缁撴灉涓嶈冻5寮狅紝閲婃斁棰勫崰鐐规暟")

    runtime_services.delete_cache(gallery_cache_key(user["id"]))
    return get_job_payload(storage, job_id, user["id"])


def mark_generation_job_failed(
    storage: AppStorage,
    *,
    job_id: str,
    user_id: str,
    project_id: str,
    error_code: str,
    error_message: str,
) -> None:
    with storage.connect() as connection:
        connection.execute(
            """
            UPDATE generation_jobs
            SET status = 'failed',
                completed_at = CURRENT_TIMESTAMP,
                error_code = ?,
                error_message = ?
            WHERE id = ? AND user_id = ?
            """,
            (error_code, _clip_error_message(error_message), job_id, user_id),
        )
        connection.execute("UPDATE projects SET status = 'failed', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,))
    release_generation_hold(storage, user_id=user_id, job_id=job_id, remark="鐢熸垚澶辫触锛岄噴鏀鹃鍗犵偣鏁?")
    release_generation_hold(storage, user_id=user_id, job_id=job_id, remark="Generation failed; reserved points released.")

def get_product_payload(storage: AppStorage, product_id: str, user_id: str) -> dict[str, Any]:
    product = get_owned_row(storage, "products", product_id, user_id)
    if product is None:
        raise_access_denied()
    return product_payload(product)


def get_project_payload(storage: AppStorage, project_id: str, user_id: str) -> dict[str, Any]:
    project = get_owned_row(storage, "projects", project_id, user_id)
    if project is None:
        raise_access_denied()
    return project_payload(project)


def normalize_uploaded_image(file_path: Path, content_type: str) -> dict[str, Any]:
    if content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise_error(HTTP_422, "UPLOAD_MIME_NOT_ALLOWED", "浠呮敮鎸?PNG銆丣PEG 鍜?WebP 鍟嗗搧鍥剧墖銆?")
    try:
        with Image.open(file_path) as image:
            normalized = ImageOps.exif_transpose(image).convert("RGB")
    except (OSError, UnidentifiedImageError) as exc:
        raise_error(HTTP_422, "UPLOAD_IMAGE_DECODE_FAILED", "鍥剧墖鏃犳硶瑙ｇ爜銆?")
        raise exc
    width, height = normalized.size
    if width * height > MAX_IMAGE_PIXELS:
        raise_error(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "UPLOAD_IMAGE_PIXELS_TOO_LARGE", "鍥剧墖鍍忕礌鏁伴噺瓒呰繃闄愬埗銆?")
    buffer = BytesIO()
    normalized.save(buffer, format="PNG")
    content = buffer.getvalue()
    return {
        "bytes": content,
        "width": width,
        "height": height,
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def get_asset_version_payload(storage: AppStorage, version_id: str, user_id: str) -> dict[str, Any]:
    with storage.connect() as connection:
        row = connection.execute(
            """
            SELECT
                assets.id AS asset_id,
                assets.asset_type,
                assets.product_id,
                assets.project_id,
                assets.status AS asset_status,
                asset_versions.id AS version_id,
                asset_versions.version,
                asset_versions.filename,
                asset_versions.content_type,
                asset_versions.file_path,
                asset_versions.size_bytes,
                asset_versions.width,
                asset_versions.height,
                asset_versions.sha256,
                asset_versions.created_at
            FROM asset_versions
            JOIN assets ON assets.id = asset_versions.asset_id
            WHERE asset_versions.id = ? AND asset_versions.user_id = ?
            """,
            (version_id, user_id),
        ).fetchone()
    payload = row_to_dict(row)
    if payload is None:
        raise_access_denied()
    payload["id"] = payload["asset_id"]
    payload.pop("file_path", None)
    return payload


def get_latest_product_original_asset(storage: AppStorage, product_id: str, user_id: str) -> dict[str, Any] | None:
    with storage.connect() as connection:
        row = connection.execute(
            """
            SELECT
                assets.id AS asset_id,
                assets.asset_type,
                asset_versions.id AS version_id,
                asset_versions.file_path,
                asset_versions.width,
                asset_versions.height,
                asset_versions.sha256
            FROM assets
            JOIN asset_versions ON asset_versions.asset_id = assets.id
            WHERE assets.user_id = ?
              AND assets.product_id = ?
              AND assets.asset_type = 'product_original'
              AND assets.deleted_at IS NULL
              AND assets.status = 'active'
            ORDER BY asset_versions.created_at DESC
            LIMIT 1
            """,
            (user_id, product_id),
        ).fetchone()
    return row_to_dict(row)


def product_payload(product: dict[str, Any]) -> dict[str, Any]:
    payload = dict(product)
    payload["specs"] = json_loads(payload.pop("specs_json", "[]"))
    return payload


def project_payload(project: dict[str, Any]) -> dict[str, Any]:
    payload = dict(project)
    payload["style_config"] = json_loads(payload.pop("style_config_json", "{}"))
    payload["certificate_config"] = json_loads(payload.pop("certificate_config_json", "{}"))
    payload["package_config"] = json_loads(payload.pop("package_config_json", "{}"))
    payload["detail_config"] = json_loads(payload.pop("detail_config_json", "{}"))
    payload["barcode_confirmed"] = bool(payload["barcode_confirmed"])
    return payload


def get_job_payload(storage: AppStorage, job_id: str, user_id: str) -> dict[str, Any]:
    job = get_owned_row(storage, "generation_jobs", job_id, user_id)
    if job is None:
        raise_access_denied()
    payload = dict(job)
    payload["outputs"] = list_outputs(storage, job_id=job_id, user_id=user_id)
    if payload.get("source_asset_version_id"):
        payload["source_asset"] = get_asset_version_payload(storage, payload["source_asset_version_id"], user_id)
    return payload


def list_outputs(
    storage: AppStorage,
    *,
    user_id: str,
    project_id: str | None = None,
    job_id: str | None = None,
    passed_only: bool = False,
    newest_first: bool = False,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]:
    clauses = ["user_id = ?"]
    params: list[Any] = [user_id]
    if project_id is not None:
        clauses.append("project_id = ?")
        params.append(project_id)
    if job_id is not None:
        clauses.append("job_id = ?")
        params.append(job_id)
    if passed_only:
        clauses.append("quality_status = 'passed'")
    created_order = "DESC" if newest_first else "ASC"
    limit_sql = ""
    if limit is not None:
        limit_sql = "LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    with storage.connect() as connection:
        rows = connection.execute(
            f"""
            SELECT * FROM generation_outputs
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at {created_order},
                CASE output_type
                    WHEN 'main' THEN 1
                    WHEN 'certificate' THEN 2
                    WHEN 'package' THEN 3
                    WHEN 'detail' THEN 4
                    WHEN 'scene' THEN 5
                    ELSE 99
                END
            {limit_sql}
            """,
            params,
        ).fetchall()
    return [output_payload(dict(row)) for row in rows]


def output_payload(row: dict[str, Any]) -> dict[str, Any]:
    output_id = row["id"]
    row["download_url"] = f"/api/v1/outputs/{output_id}/download"
    row["thumbnail_url"] = f"/api/v1/outputs/{output_id}/thumbnail"
    return row


def gallery_cursor_offset(cursor: str | None) -> int:
    if cursor is None or cursor == "":
        return 0
    try:
        offset = int(cursor)
    except ValueError:
        raise_error(status.HTTP_400_BAD_REQUEST, "INVALID_GALLERY_CURSOR", "Invalid gallery cursor.")
    if offset < 0:
        raise_error(status.HTTP_400_BAD_REQUEST, "INVALID_GALLERY_CURSOR", "Invalid gallery cursor.")
    return offset


def ensure_output_thumbnail(path: Path) -> Path:
    thumbnail_path = path.with_name(f"{path.stem}.thumb.png")
    if thumbnail_path.exists() and thumbnail_path.stat().st_mtime >= path.stat().st_mtime:
        return thumbnail_path
    with Image.open(path) as image:
        thumbnail = ImageOps.contain(image.convert("RGB"), (320, 320), method=Image.Resampling.LANCZOS)
        thumbnail.save(thumbnail_path, format="PNG", optimize=True)
    return thumbnail_path


def output_cache_headers(output: dict[str, Any]) -> dict[str, str]:
    return {
        "Cache-Control": "private, max-age=86400",
        "ETag": f"\"{output['id']}-{output.get('version', 1)}\"",
    }


def record_existing_output_files(
    connection: Any,
    *,
    output_dir: Path,
    job_id: str,
    user_id: str,
    project_id: str,
    source_asset_version_id: str,
) -> None:
    job_dir = output_dir / job_id
    if not job_dir.exists():
        return
    for output_type, _expected_width, _expected_height in OUTPUT_SPECS:
        path = job_dir / f"{output_type}.png"
        if not path.exists():
            continue
        try:
            with Image.open(path) as image:
                width, height = image.size
        except (OSError, UnidentifiedImageError):
            continue
        insert_generation_output(
            connection,
            user_id=user_id,
            project_id=project_id,
            job_id=job_id,
            output_type=output_type,
            width=width,
            height=height,
            file_path=path,
            source_asset_version_id=source_asset_version_id,
        )


def recover_existing_project_outputs(storage: AppStorage, *, project_id: str, user_id: str) -> None:
    with storage.connect() as connection:
        jobs = connection.execute(
            """
            SELECT id, source_asset_version_id
            FROM generation_jobs
            WHERE project_id = ? AND user_id = ? AND source_asset_version_id IS NOT NULL
            """,
            (project_id, user_id),
        ).fetchall()
        for job in jobs:
            record_existing_output_files(
                connection,
                output_dir=storage.output_dir,
                job_id=job["id"],
                user_id=user_id,
                project_id=project_id,
                source_asset_version_id=job["source_asset_version_id"],
            )


def insert_generation_output(
    connection: Any,
    *,
    user_id: str,
    project_id: str,
    job_id: str,
    output_type: str,
    width: int,
    height: int,
    file_path: Path,
    source_asset_version_id: str,
) -> None:
    existing = connection.execute(
        "SELECT id FROM generation_outputs WHERE job_id = ? AND user_id = ? AND output_type = ?",
        (job_id, user_id, output_type),
    ).fetchone()
    if existing is not None:
        return
    connection.execute(
        """
        INSERT INTO generation_outputs
            (id, user_id, project_id, job_id, output_type, width, height, format,
             file_path, quality_status, source_asset_version_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'png', ?, 'passed', ?)
        """,
        (
            new_id(),
            user_id,
            project_id,
            job_id,
            output_type,
            width,
            height,
            str(file_path),
            source_asset_version_id,
        ),
    )


def get_owned_row(storage: AppStorage, table: str, row_id: str, user_id: str) -> dict[str, Any] | None:
    allowed_tables = {"products", "projects", "generation_jobs", "generation_outputs", "assets", "asset_versions"}
    if table not in allowed_tables:
        raise ValueError(f"Unsupported table: {table}")
    with storage.connect() as connection:
        row = connection.execute(f"SELECT * FROM {table} WHERE id = ? AND user_id = ?", (row_id, user_id)).fetchone()
    return row_to_dict(row)


def build_image_generation_provider() -> Any:
    provider_name = os.getenv("IMAGE_PROVIDER", "mock").strip().lower()
    if provider_name in {"mock", "local"}:
        return MockImageProvider()
    if provider_name in {"kele", "code28", "kele-gpt-image-2", "gpt-image-2"}:
        return KeleFiveImagePipeline(
            KeleGptImage2Provider(load_kele_config()),
            font_path=os.getenv("CHINESE_FONT_PATH", ""),
            edit_size=os.getenv("KELE_IMAGE_SIZE", "1024x1024"),
        )
    raise_error(status.HTTP_503_SERVICE_UNAVAILABLE, "IMAGE_PROVIDER_UNSUPPORTED", f"Unsupported IMAGE_PROVIDER: {provider_name}")


def load_kele_config() -> KeleConfig:
    extra_headers_raw = os.getenv("KELE_EXTRA_HEADERS_JSON", "{}") or "{}"
    try:
        extra_headers = json.loads(extra_headers_raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("KELE_EXTRA_HEADERS_JSON is not valid JSON") from exc
    if not isinstance(extra_headers, dict):
        raise RuntimeError("KELE_EXTRA_HEADERS_JSON must be a JSON object")
    return KeleConfig(
        base_url=os.getenv("KELE_BASE_URL") or os.getenv("KELE_API_BASE_URL", "https://code28.ccwu.cc/v1"),
        api_key=os.getenv("KELE_API_KEY", ""),
        model=os.getenv("KELE_MODEL", "gpt-image-2"),
        timeout_seconds=int(os.getenv("KELE_TIMEOUT_SECONDS", "300")),
        extra_headers={str(key): str(value) for key, value in extra_headers.items()},
    )


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), 120_000).hex()
    return f"pbkdf2_sha256${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, salt, digest = stored.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), 120_000).hex()
    return hmac.compare_digest(candidate, digest)


def raise_access_denied() -> None:
    raise_error(status.HTTP_404_NOT_FOUND, "RESOURCE_ACCESS_DENIED", "璧勬簮涓嶅瓨鍦ㄦ垨鏃犳潈璁块棶銆?")


def raise_error(status_code: int, code: str, message: str) -> None:
    raise HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _clip_error_message(message: str, limit: int = 2000) -> str:
    return message[:limit]
