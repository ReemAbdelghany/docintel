from fastapi import APIRouter

from docintel.routers.dependencies import ContainerDep
from docintel.routers.v1alpha1.schemas.cases import CaseResponse

router = APIRouter(tags=["cases"])


@router.post("/cases", status_code=201)
async def create_case(c: ContainerDep) -> CaseResponse:
    case_id = await c.create_case()
    return CaseResponse(case_id=case_id, documents_url=f"/v1alpha1/cases/{case_id}/documents")
