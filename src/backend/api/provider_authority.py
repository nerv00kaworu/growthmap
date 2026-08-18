"""Fail-closed provider authority and external-secret transition protocol."""
import asyncio, secrets
from collections.abc import Callable
from fastapi import HTTPException
from sqlalchemy import update, select
from sqlalchemy.ext.asyncio import AsyncSession
from models.models import ProviderConfig
from models.provider_authority import MAX_PROVIDER_REVISION, revision_exhausted
from api.provider_lock import ProviderLock

_locks: dict[str, asyncio.Lock] = {}
def _lock(provider_id: str) -> asyncio.Lock: return _locks.setdefault(provider_id, asyncio.Lock())

def transition_busy() -> HTTPException:
    return HTTPException(409, detail={"code":"PROVIDER_SECRET_CHANGE_PENDING","message":"Provider secret reconciliation is pending."})

async def guarded_provider_update(db: AsyncSession, provider: ProviderConfig, **values) -> None:
    provider_id=provider.id
    revision=provider.revision
    if not isinstance(revision,int) or isinstance(revision,bool) or not 1<=revision<=MAX_PROVIDER_REVISION: raise revision_exhausted()
    if provider.secret_change_pending: raise transition_busy()
    if revision==MAX_PROVIDER_REVISION: raise revision_exhausted()
    result=await db.execute(update(ProviderConfig).where(ProviderConfig.id==provider_id,ProviderConfig.revision==revision,ProviderConfig.revision<MAX_PROVIDER_REVISION,ProviderConfig.secret_change_pending.is_(False)).values(**values,revision=revision+1))
    if result.rowcount!=1: raise HTTPException(409,detail={"code":"PROVIDER_PROFILE_CHANGED","message":"Provider profile changed; retry."})

async def recover_external_secret(db: AsyncSession, provider: ProviderConfig, expected_revision: int, mutate: Callable[[], None], *, after_claim: Callable[[], None] | None = None, after_mutate: Callable[[], None] | None = None) -> None:
    """Claim durably before external I/O; same-process lock spans claim/store/finalize.

    A confirmed force reclaim is serialized behind a live local winner. In another
    process, replacing the durable claim makes the old attempt unable to finalize;
    authoring file-store deployments are restricted to the one writable app process.
    """
    provider_id=provider.id
    async with _lock(provider_id), ProviderLock(provider_id):
        await db.rollback()  # discard stale identity-map/read transaction
        current=(await db.execute(select(ProviderConfig).where(ProviderConfig.id==provider_id))).scalar_one_or_none()
        if not current or not current.secret_change_pending or current.revision!=expected_revision:
            raise HTTPException(409,detail={"code":"PROVIDER_SECRET_RECOVERY_STALE","message":"Credential recovery revision is stale."})
        token=secrets.token_hex(24)
        claim_where=[ProviderConfig.id==provider_id,ProviderConfig.revision==expected_revision,ProviderConfig.secret_change_pending.is_(True)]
        # Holding the OS lock proves any persisted claim has no live owner: every
        # participant must hold this lock across claim, external I/O and finalize.
        # A crash releases the kernel lock, so replacing its claim is safe.
        result=await db.execute(update(ProviderConfig).where(*claim_where).values(secret_change_claim=token))
        if result.rowcount!=1:
            raise HTTPException(409,detail={"code":"PROVIDER_SECRET_RECOVERY_CLAIMED","message":"Credential recovery is already in progress."})
        await db.commit()
        if after_claim is not None: after_claim()
        mutate()
        if after_mutate is not None: after_mutate()
        try:
            result=await db.execute(update(ProviderConfig).where(ProviderConfig.id==provider_id,ProviderConfig.revision==expected_revision,ProviderConfig.secret_change_pending.is_(True),ProviderConfig.secret_change_claim==token).values(secret_change_pending=False,secret_change_claim=None))
            if result.rowcount!=1: raise transition_busy()
            await db.commit()
        except BaseException:
            await db.rollback(); raise transition_busy()

async def change_external_secret(db: AsyncSession, provider: ProviderConfig, mutate: Callable[[], None]) -> None:
    provider_id=provider.id
    revision=provider.revision
    if not isinstance(revision,int) or isinstance(revision,bool) or not 1<=revision<MAX_PROVIDER_REVISION: raise revision_exhausted()
    if provider.secret_change_pending: raise transition_busy()
    try:
        result=await db.execute(update(ProviderConfig).where(ProviderConfig.id==provider_id,ProviderConfig.revision==revision,ProviderConfig.revision<MAX_PROVIDER_REVISION,ProviderConfig.secret_change_pending.is_(False)).values(revision=revision+1,secret_change_pending=True,secret_change_claim=None))
        if result.rowcount!=1: raise HTTPException(409,detail={"code":"PROVIDER_PROFILE_CHANGED","message":"Provider profile changed; retry."})
        await db.commit()
    except BaseException:
        await db.rollback(); raise
    await recover_external_secret(db,provider,revision+1,mutate)
