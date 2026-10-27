"""Mounts the versioned routers."""

from fastapi import APIRouter

from docintel.routers.v1alpha1.components import cases, documents, health

api_router = APIRouter(prefix="/v1alpha1")
api_router.include_router(cases.router)
api_router.include_router(documents.router)

# health endpoints are unversioned: orchestrators probe a stable path
health_router = health.router
