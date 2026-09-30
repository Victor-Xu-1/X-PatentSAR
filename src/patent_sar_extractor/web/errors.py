"""Public errors deliberately carry no underlying paths or exception text."""

from __future__ import annotations

from starlette.exceptions import HTTPException


class WebError(HTTPException):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(status_code=status, detail=message)
        self.status = status
        self.code = code
        self.message = message

    def payload(self) -> dict[str, dict[str, str]]:
        return {"error": {"code": self.code, "message": self.message}}
