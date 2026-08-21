"""Main-process-only, per-sidecar credential hydration capability."""
import hmac, os, re
from fastapi import Request

_HEADER="x-growthmap-hydration-capability"
_FORMAT=re.compile(r"[A-Za-z0-9_-]{43,128}\Z")
_EXPECTED=os.getenv("GROWTHMAP_HYDRATION_CAPABILITY","")
_sealed=False

def valid(request: Request) -> bool:
    supplied=request.headers.get(_HEADER,"")
    return bool(not _sealed and _FORMAT.fullmatch(supplied) and _FORMAT.fullmatch(_EXPECTED) and hmac.compare_digest(supplied,_EXPECTED))

def require(request: Request) -> None:
    from fastapi import HTTPException
    if not valid(request): raise HTTPException(403,detail={"code":"HYDRATION_CAPABILITY_INVALID","message":"Private hydration capability is invalid or sealed"})

def seal(request: Request) -> None:
    global _sealed
    require(request);_sealed=True
