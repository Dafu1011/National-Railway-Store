from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from app.api.phase_one import current_user, get_storage, raise_error
from app.core.billing import get_account_payload, list_transactions, recharge_account
from app.storage import AppStorage, row_to_dict


router = APIRouter(prefix="/api/v1", tags=["account"])


class RechargePayload(BaseModel):
    points: int = Field(gt=0, le=10_000_000)
    remark: str = Field(default="", max_length=120)


@router.get("/account/me")
async def get_my_account(
    user: dict[str, Any] = Depends(current_user),
    storage: AppStorage = Depends(get_storage),
) -> dict[str, Any]:
    return get_account_payload(storage, user)


@router.get("/account/transactions")
async def get_my_account_transactions(
    user: dict[str, Any] = Depends(current_user),
    storage: AppStorage = Depends(get_storage),
) -> dict[str, Any]:
    return {"items": list_transactions(storage, user["id"])}


@router.post("/admin/accounts/{user_id}/recharge")
async def admin_recharge_account(
    user_id: str,
    payload: RechargePayload,
    admin: dict[str, Any] = Depends(current_user),
    storage: AppStorage = Depends(get_storage),
) -> dict[str, Any]:
    if admin.get("role") != "admin":
        raise_error(status.HTTP_403_FORBIDDEN, "ADMIN_REQUIRED", "需要管理员权限。")
    with storage.connect() as connection:
        target_user = row_to_dict(connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())
    if target_user is None:
        raise_error(status.HTTP_404_NOT_FOUND, "USER_NOT_FOUND", "用户不存在。")
    return recharge_account(storage, target_user=target_user, points=payload.points, remark=payload.remark)
