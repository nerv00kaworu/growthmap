"""Provider authority invariants shared by schemas, routes and migrations."""
from fastapi import HTTPException

# Provider revisions cross the JSON boundary as numbers, so they must remain
# exactly representable by every supported JavaScript client.
MAX_PROVIDER_REVISION = 9_007_199_254_740_991
REVISION_EXHAUSTED_CODE = "PROVIDER_REVISION_EXHAUSTED"


def revision_exhausted() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": REVISION_EXHAUSTED_CODE,
            "message": "Provider revision capacity is exhausted; create a new profile.",
        },
    )
