"""Authenticated Whop Experience delivery plus existing desktop activation contract."""
from __future__ import annotations

from typing import Any, Protocol

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictStr, ValidationError

from .whop_fulfillment import BuyerDeliveryStore


class VerifiedWhopExperience(Protocol):
    """Adapter for the live Experience token verification and checkAccess calls."""
    def authenticate(self, request: Request) -> dict[str, Any]: ...
    def check_access(self, *, user_id: str) -> bool: ...


class ActivationChallengeBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    order_id: StrictStr
    recovery_code: StrictStr
    device_public_key: StrictStr


class ActivationRefreshChallengeBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    activation_id: StrictStr
    license_id: StrictStr
    device_public_key: StrictStr

class ActivationRefreshCompleteBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    challenge_id: StrictStr
    proof: StrictStr

class ActivationCompleteBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    challenge_id: StrictStr
    proof: StrictStr


async def _body(request: Request, model):
    raw = await request.body()
    if not raw or len(raw) > 8192:
        raise ValueError
    try:
        return model.model_validate_json(raw, strict=True)
    except (ValueError, ValidationError):
        raise ValueError from None


_PRIVATE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache", "Referrer-Policy": "no-referrer"}


def _not_found():
    return JSONResponse({"state": "not_found_or_unavailable"}, status_code=404, headers=_PRIVATE_HEADERS)


def create_buyer_activation_router(*, store: BuyerDeliveryStore, authority: Any) -> APIRouter:
    """Public desktop contract; license ids cross only the signed loopback adapter."""
    router = APIRouter()

    @router.post("/v1/activation/challenge")
    async def activation_challenge(request: Request):
        try:
            body = await _body(request, ActivationChallengeBody)
            row = store.authenticated_entitlement(body.order_id, body.recovery_code)
            if not row or type(row) is not dict or type(row.get("license_id")) is not str:
                raise ValueError
            challenge = authority.issue_activation_challenge(
                license_id=row["license_id"], device_public_key=body.device_public_key)
        except Exception:
            return _not_found()
        return JSONResponse({"state": "challenge_issued", "challenge": challenge}, headers=_PRIVATE_HEADERS)

    @router.post("/v1/activation/refresh/challenge")
    async def activation_refresh_challenge(request: Request):
        try:
            body=await _body(request,ActivationRefreshChallengeBody)
            challenge=authority.issue_activation_refresh_challenge(activation_id=body.activation_id,license_id=body.license_id,device_public_key=body.device_public_key,expected_flow_kind="payment")
        except Exception:return _not_found()
        return JSONResponse({"state":"challenge_issued","challenge":challenge},headers=_PRIVATE_HEADERS)

    @router.post("/v1/activation/refresh/complete")
    async def activation_refresh_complete(request: Request):
        try:
            body=await _body(request,ActivationRefreshCompleteBody);certificate=authority.complete_activation_refresh(challenge_id=body.challenge_id,proof=body.proof,expected_flow_kind="payment")
        except Exception:return _not_found()
        return JSONResponse({"state":"activated","certificate":certificate},headers=_PRIVATE_HEADERS)

    @router.post("/v1/activation/complete")
    async def activation_complete(request: Request):
        try:
            body = await _body(request, ActivationCompleteBody)
            certificate = authority.activate_challenge(
                challenge_id=body.challenge_id, proof=body.proof, expected_flow_kind="payment")
        except Exception:
            return _not_found()
        return JSONResponse({"state": "activated", "certificate": certificate}, headers=_PRIVATE_HEADERS)

    return router


def create_buyer_activation_app(*, store: BuyerDeliveryStore, authority: Any) -> FastAPI:
    """Dedicated composition suitable for a separately terminated loopback/public edge."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False)
    app.include_router(create_buyer_activation_router(store=store, authority=authority))
    return app


def create_whop_buyer_router(*, store: BuyerDeliveryStore, experience: VerifiedWhopExperience,
                             authority: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/whop/experience/licenses")
    async def buyer_licenses(request: Request):
        try:
            identity = experience.authenticate(request)
            if type(identity) is not dict or set(identity) != {"user_id"} or type(identity["user_id"]) is not str:
                raise ValueError
            user_id = identity["user_id"]
            if experience.check_access(user_id=user_id) is not True:
                raise ValueError
            licenses = store.list_for_verified_user(user_id)
        except Exception:
            return JSONResponse({"state": "not_authorized"}, status_code=403)
        return JSONResponse({"licenses": licenses}, headers=_PRIVATE_HEADERS)

    router.include_router(create_buyer_activation_router(store=store, authority=authority))
    return router
