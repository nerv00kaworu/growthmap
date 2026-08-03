import hmac
import os
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

DESKTOP_MODE = os.getenv("GROWTHMAP_DESKTOP_MODE") == "1"
SESSION_TOKEN = os.getenv("GROWTHMAP_SESSION_TOKEN", "")

class DesktopSessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path.startswith("/agent/v1") or not DESKTOP_MODE:
            return await call_next(request)
        if not SESSION_TOKEN:
            return JSONResponse({"detail": "Desktop session is not initialized"}, status_code=503)
        supplied = request.headers.get("authorization", "")
        expected = f"Bearer {SESSION_TOKEN}"
        if not hmac.compare_digest(supplied, expected):
            return JSONResponse({"detail": "Invalid desktop session"}, status_code=401)
        return await call_next(request)
