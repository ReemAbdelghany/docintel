"""RFC 9457 problem-details response."""

from pydantic import BaseModel


class ProblemDetails(BaseModel):
    type: str
    title: str
    status: int
    detail: str
    correlation_id: str | None = None
