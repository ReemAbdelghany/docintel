from uuid import UUID

from pydantic import BaseModel


class CaseResponse(BaseModel):
    case_id: UUID
    documents_url: str
