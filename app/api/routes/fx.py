"""환율 변환 + 과거 추이 — Frankfurter(ECB 공식 환율, 키 불필요) 프록시 (본인만의 신규 기능)."""

from __future__ import annotations

from datetime import date, timedelta, datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/fx", tags=["fx"])

_BASE_URL = "https://api.frankfurter.dev/v1"
_cache: dict[str, tuple[datetime, dict[str, Any]]] = {}
_ttl = timedelta(minutes=15)


def _cached(key: str) -> dict[str, Any] | None:
    hit = _cache.get(key)
    if hit and datetime.now(timezone.utc) - hit[0] < _ttl:
        return hit[1]
    return None


@router.get("/rate")
async def convert(
    frm: str = Query(alias="from", pattern=r"^[A-Z]{3}$"),
    to: str = Query(pattern=r"^[A-Z]{3}$"),
    amount: float = Query(default=1, gt=0, le=1_000_000_000),
) -> dict[str, Any]:
    key = f"rate:{frm}:{to}"
    cached = _cached(key)
    if cached is None:
        try:
            async with httpx.AsyncClient(timeout=6.0, follow_redirects=True) as client:
                response = await client.get(f"{_BASE_URL}/latest", params={"from": frm, "to": to})
                response.raise_for_status()
            data = response.json()
            rate = data["rates"].get(to)
            if rate is None:
                raise HTTPException(status_code=404, detail=f"{to} 환율을 찾을 수 없습니다.")
            cached = {"rate": rate, "date": data.get("date")}
            _cache[key] = (datetime.now(timezone.utc), cached)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="환율 정보를 불러오지 못했습니다.") from exc

    return {
        "from": frm,
        "to": to,
        "rate": cached["rate"],
        "amount": amount,
        "converted": round(amount * cached["rate"], 4),
        "as_of": cached["date"],
    }


@router.get("/history")
async def history(
    frm: str = Query(alias="from", pattern=r"^[A-Z]{3}$"),
    to: str = Query(pattern=r"^[A-Z]{3}$"),
    days: int = Query(default=30, ge=7, le=365),
) -> dict[str, Any]:
    key = f"hist:{frm}:{to}:{days}"
    cached = _cached(key)
    if cached is None:
        end = date.today()
        start = end - timedelta(days=days)
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                response = await client.get(
                    f"{_BASE_URL}/{start.isoformat()}..{end.isoformat()}",
                    params={"from": frm, "to": to},
                )
                response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="환율 이력을 불러오지 못했습니다.") from exc

        points = sorted(
            ({"date": d, "rate": rates.get(to)} for d, rates in data.get("rates", {}).items() if rates.get(to) is not None),
            key=lambda p: p["date"],
        )
        if not points:
            raise HTTPException(status_code=502, detail="표시할 환율 이력이 없습니다.")
        cached = {"points": points}
        _cache[key] = (datetime.now(timezone.utc), cached)

    return {"from": frm, "to": to, "days": days, "points": cached["points"]}
