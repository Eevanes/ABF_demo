"""Independent operator credentials; chat text never supplies identity."""

import hashlib
import hmac
import json
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class StaffIdentity:
    userid: str
    role: str = "public"
    work_ids: tuple[str, ...] | None = None

    def require_staff(self, work_id: str | None = None) -> None:
        if self.role not in {"staff", "admin"} or not self.userid:
            raise PermissionError("需要独立认证的工作人员身份")
        if work_id and self.work_ids is not None and work_id not in self.work_ids:
            raise PermissionError("作品不在当前身份授权范围内")


class StaffAuth:
    """Use a server-configured digest mapping, never participant team keys."""

    def __init__(self, credentials: str | None = None):
        raw = credentials if credentials is not None else os.environ.get("ARENA_STAFF_CREDENTIALS", "[]")
        try:
            rows = json.loads(raw)
            if not isinstance(rows, list):
                raise ValueError
            self._identities: dict[str, StaffIdentity] = {}
            for row in rows:
                digest, userid, role = row["token_sha256"], row["userid"], row["role"]
                if (
                    not isinstance(digest, str) or len(digest) != 64
                    or any(c not in "0123456789abcdef" for c in digest)
                    or not isinstance(userid, str) or not userid.strip()
                    or role not in {"public", "staff", "admin"}
                    or digest in self._identities
                ):
                    raise ValueError
                work_ids = row.get("work_ids")
                if work_ids is not None and (
                    not isinstance(work_ids, list)
                    or any(not isinstance(value, str) or not value for value in work_ids)
                ):
                    raise ValueError
                self._identities[digest] = StaffIdentity(
                    userid, role, None if work_ids is None else tuple(work_ids)
                )
        except (ValueError, TypeError, KeyError):
            raise ValueError("ARENA_STAFF_CREDENTIALS 格式无效；须使用独立凭据摘要和可信身份映射") from None

    def identify(self, authorization: str) -> StaffIdentity:
        if not authorization:
            return StaffIdentity("")
        if not authorization.startswith("Bearer ") or not authorization[7:]:
            raise PermissionError("无效的工作人员凭据")
        candidate = hashlib.sha256(authorization[7:].encode()).hexdigest()
        for digest, identity in self._identities.items():
            if hmac.compare_digest(digest, candidate):
                return identity
        raise PermissionError("无效的工作人员凭据")
