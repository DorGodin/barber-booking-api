"""Domain refusals carry a stable machine-readable code next to the message.

A client branches on `code`, never on the wording of `detail`, so the message
can be improved without breaking anyone.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class DomainError(Exception):
    def __init__(self, status: int, code: str, detail: str):
        self.status, self.code, self.detail = status, code, detail


async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"detail": exc.detail, "code": exc.code})


def not_found(what: str) -> DomainError:
    return DomainError(404, "not_found", f"{what} not found")
