from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core import license as license_core

router = APIRouter(prefix="/api/license", tags=["license"])


class CardBody(BaseModel):
    card: str


@router.get("/status")
async def license_status():
    enforced = license_core.is_license_enforced()
    has_srv = license_core.has_card_server_config()
    stored = await license_core.get_stored_card()
    if not enforced:
        valid = True
    else:
        valid = await license_core.ensure_license_valid()
    return {
        "enforced": enforced,
        "has_server_config": has_srv,
        "has_stored_card": bool(stored),
        "valid": valid,
    }


@router.post("/activate")
async def license_activate(body: CardBody):
    ok, msg = await license_core.activate_license(body.card)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg}


@router.post("/unbind")
async def license_unbind(body: CardBody):
    ok, msg, _raw = await license_core.unbind_license(body.card)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg}
