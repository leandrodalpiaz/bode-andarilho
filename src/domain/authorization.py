from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet, Mapping


ROLE_MEMBER = "member"
ROLE_SECRETARY = "secretary"
ROLE_ADMIN = "admin"


@dataclass(frozen=True)
class Actor:
    """Contexto de autorização obtido do Auth e dos vínculos reais."""

    profile_id: str
    auth_user_id: str
    email: str
    is_global_admin: bool = False
    roles_by_store: Mapping[int, FrozenSet[str]] = field(default_factory=dict)

    def roles_for(self, store_id: int) -> FrozenSet[str]:
        return self.roles_by_store.get(int(store_id), frozenset())

    def has_role(self, store_id: int, *roles: str) -> bool:
        if self.is_global_admin:
            return True
        return bool(self.roles_for(store_id).intersection(roles))

    def can_read_store(self, store_id: int) -> bool:
        return self.has_role(store_id, ROLE_MEMBER, ROLE_SECRETARY, ROLE_ADMIN)

    def can_manage_events(self, store_id: int) -> bool:
        return self.has_role(store_id, ROLE_SECRETARY, ROLE_ADMIN)

    def can_manage_store(self, store_id: int | None = None) -> bool:
        if self.is_global_admin:
            return True
        return store_id is not None and self.has_role(store_id, ROLE_ADMIN)

    def can_invite(self, store_id: int | None = None) -> bool:
        return self.can_manage_store(store_id)
