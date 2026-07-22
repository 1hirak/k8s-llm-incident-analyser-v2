"""RFC 7807 Problem Details error model (contracts/README.md §4.6).

All 4xx and 5xx responses across all services use this shape.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

ERROR_BASE_URL = "https://errors.k8s-llm.io"


class ProblemDetail(BaseModel):
    type: str
    title: str
    status: int
    detail: str
    instance: Optional[str] = None

    @classmethod
    def of(
        cls,
        status: int,
        title: str,
        detail: str,
        *,
        type_slug: Optional[str] = None,
        instance: Optional[str] = None,
    ) -> "ProblemDetail":
        slug = type_slug or title.lower().replace(" ", "-")
        return cls(
            type=f"{ERROR_BASE_URL}/{slug}",
            title=title,
            status=status,
            detail=detail,
            instance=instance,
        )
