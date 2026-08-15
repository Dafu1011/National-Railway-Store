from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class ResourceAccessDenied(Exception):
    code: str = "RESOURCE_ACCESS_DENIED"
    message: str = "资源不存在或无权访问。"


def owner_filter(resource_id: UUID, current_user_id: UUID) -> dict[str, UUID]:
    return {"id": resource_id, "user_id": current_user_id}


def assert_owned_by_user(*, resource_user_id: UUID, current_user_id: UUID) -> None:
    if resource_user_id != current_user_id:
        raise ResourceAccessDenied()

