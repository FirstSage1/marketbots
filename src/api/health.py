"""Health check эндпоинт.

Содержит endpoint для проверки работоспособности сервиса:
- GET /health — health check для мониторинга и liveness probes
"""

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(request: Request) -> dict[str, str | bool | int | None]:
    """Проверка состояния сервиса.

    Используется для мониторинга и проверки доступности.
    Timeweb, Amvera и другие хостинги используют этот эндпоинт
    для определения, что приложение живо.

    Returns:
        Словарь со статусом "ok"
    """
    legal = getattr(request.app.state, "legal_consent", {})
    result: dict[str, str | bool | int | None] = {
        "status": "ok",
        "telegram_mode": getattr(request.app.state, "telegram_mode", "starting"),
        "legal_enabled": bool(legal.get("enabled", False)),
        "legal_documents_configured": bool(
            legal.get("documents_configured", False)
        ),
        "legal_version": str(legal.get("version", "unknown")),
    }
    polling_task = getattr(request.app.state, "polling_task", None)
    if polling_task is not None:
        polling_alive = not polling_task.done()
        if not polling_alive:
            result["status"] = "degraded"
        result.update(
            {
                "polling_alive": polling_alive,
                "polling_restarts": getattr(
                    request.app.state, "polling_restarts", 0
                ),
                "polling_last_error": getattr(
                    request.app.state, "polling_last_error", None
                ),
            }
        )
    return result
