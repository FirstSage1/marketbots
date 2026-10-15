"""Health check эндпоинт.

Содержит endpoint для проверки работоспособности сервиса:
- GET /health — health check для мониторинга и liveness probes
"""

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(request: Request) -> dict[str, str | bool]:
    """Проверка состояния сервиса.

    Используется для мониторинга и проверки доступности.
    Timeweb, Amvera и другие хостинги используют этот эндпоинт
    для определения, что приложение живо.

    Returns:
        Словарь со статусом "ok"
    """
    legal = getattr(request.app.state, "legal_consent", {})
    return {
        "status": "ok",
        "telegram_mode": getattr(request.app.state, "telegram_mode", "starting"),
        "legal_enabled": bool(legal.get("enabled", False)),
        "legal_documents_configured": bool(
            legal.get("documents_configured", False)
        ),
    }
