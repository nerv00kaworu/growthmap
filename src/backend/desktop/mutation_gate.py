"""Central desktop extraction-mode gate.

The allowlist is intentionally small. Authoring web mode never enters this policy.
"""
import os
from pathlib import Path
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from desktop.startup_verdict import effective_entitlement
from desktop.secrets import desktop_mode

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# License recovery is the only state-changing HTTP operation available in extraction mode.
EXTRACTION_MUTATION_ALLOWLIST = frozenset({("POST", "/api/desktop/license/import"), ("POST", "/api/desktop/trial/start")})

class DesktopMutationGateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not desktop_mode() or request.method in SAFE_METHODS or (request.method,request.url.path) in EXTRACTION_MUTATION_ALLOWLIST:
            return await call_next(request)
        # This is not a public path allowlist: only Electron main's live,
        # unsealed per-sidecar capability may cross the read-only gate.
        path=request.url.path
        hydration_path=(path=="/api/desktop/secrets/hydration/seal" or (path.startswith("/api/desktop/secrets/") and path.endswith("/hydrate")))
        if hydration_path:
            from desktop.hydration_auth import valid as valid_hydration
            if valid_hydration(request): return await call_next(request)
        recovery_marker=os.getenv("GROWTHMAP_UPDATE_PENDING_FILE")
        recovery_locked=bool(recovery_marker and Path(recovery_marker).exists())
        entitlement=effective_entitlement()
        if recovery_locked or not entitlement.mutations_allowed:
            return JSONResponse(status_code=403,content={"detail":"GrowthMap is in read-only extraction mode. Viewing, search, export, backup, database reveal, and license activation remain available.","code":"ENTITLEMENT_READ_ONLY","reason":"update_recovery" if recovery_locked else entitlement.reason})
        return await call_next(request)
