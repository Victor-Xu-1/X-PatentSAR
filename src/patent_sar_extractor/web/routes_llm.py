"""LLM routes mounted by the parent's existing session/Origin/CSRF app."""

from fastapi import APIRouter

from .llm_models import LLMSettings, LLMSettingsRequest, LLMTestRequest, LLMTestResult
from .llm_settings import LLMSettingsService


def llm_routes(service: LLMSettingsService) -> APIRouter:
    router = APIRouter(prefix="/api/v1/llm")

    @router.get("/settings", response_model=LLMSettings)
    def settings() -> LLMSettings:
        return service.get_settings()

    @router.put("/settings", response_model=LLMSettings)
    def save(body: LLMSettingsRequest) -> LLMSettings:
        return service.save_settings(body)

    @router.post("/test", response_model=LLMTestResult)
    def test(body: LLMTestRequest) -> LLMTestResult:
        return service.test_connection(body)

    return router
