import math
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import Location
from ..schemas import LocationIn, LocationOut

router = APIRouter(prefix="/locations", tags=["locations"])


def _degree_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Euclidean distance in degrees. No cos(lat) correction — see module docstring."""
    return math.hypot(lat2 - lat1, lng2 - lng1)


@router.get("", response_model=list[LocationOut])
async def list_locations(
    db: AsyncSession = Depends(get_db),
    bbox: str | None = Query(
        None,
        description="Fencing box: min_lat,min_lng,max_lat,max_lng",
        examples=["45.40,-75.80,45.55,-75.60"],
    ),
    near: str | None = Query(
        None,
        description="Ranking origin: lat,lng. Sorts results by Euclidean degree distance.",
        examples=["49.2827,-123.1207"],
    ),
    max_deg: float | None = Query(
        None,
        gt=0,
        le=10,
        description="Optional degree-radius prefilter around `near` (requires `near`).",
    ),
):
    stmt = select(Location)

    if bbox:
        try:
            min_lat, min_lng, max_lat, max_lng = (float(x) for x in bbox.split(","))
        except ValueError:
            raise HTTPException(400, "bbox must be 'min_lat,min_lng,max_lat,max_lng'")
        stmt = stmt.where(
            Location.latitude.between(min_lat, max_lat),
            Location.longitude.between(min_lng, max_lng),
        )

    origin: tuple[float, float] | None = None
    if near:
        try:
            origin = (float(x) for x in near.split(","))
            lat0, lng0 = origin
        except (ValueError, TypeError):
            raise HTTPException(400, "near must be 'lat,lng'")
        origin = (lat0, lng0)

    if max_deg is not None:
        if origin is None:
            raise HTTPException(400, "max_deg requires near")
        # Degree-space bounding box enclosing the circle of radius max_deg.
        lat0, lng0 = origin
        stmt = stmt.where(
            Location.latitude.between(lat0 - max_deg, lat0 + max_deg),
            Location.longitude.between(lng0 - max_deg, lng0 + max_deg),
        )

    rows = (await db.execute(stmt)).scalars().all()

    out: list[LocationOut] = [LocationOut.model_validate(row) for row in rows]

    if origin is not None:
        lat0, lng0 = origin
        for item, row in zip(out, rows):
            if row.latitude is not None and row.longitude is not None:
                item.distance_deg = _degree_distance(
                    lat0, lng0, float(row.latitude), float(row.longitude)
                )
        if max_deg is not None:
            out = [x for x in out if x.distance_deg is not None and x.distance_deg <= max_deg]
        out.sort(key=lambda x: (x.distance_deg is None, x.distance_deg or 0.0))
    else:
        out.sort(key=lambda x: (x.name is None, x.name or ""))

    return out


@router.post("", response_model=LocationOut, status_code=status.HTTP_201_CREATED)
async def create_location(payload: LocationIn, db: AsyncSession = Depends(get_db)):
    loc = Location(**payload.model_dump())
    db.add(loc)
    await db.commit()
    await db.refresh(loc)
    return loc


@router.get("/{loc_id}", response_model=LocationOut)
async def get_location(loc_id: UUID, db: AsyncSession = Depends(get_db)):
    loc = await db.get(Location, loc_id)
    if not loc:
        raise HTTPException(404, "location not found")
    return loc


@router.patch("/{loc_id}", response_model=LocationOut)
async def update_location(loc_id: UUID, payload: LocationIn, db: AsyncSession = Depends(get_db)):
    loc = await db.get(Location, loc_id)
    if not loc:
        raise HTTPException(404, "location not found")
    for k, v in payload.model_dump().items():
        setattr(loc, k, v)
    await db.commit()
    await db.refresh(loc)
    return loc


@router.delete("/{loc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_location(loc_id: UUID, db: AsyncSession = Depends(get_db)):
    loc = await db.get(Location, loc_id)
    if not loc:
        raise HTTPException(404, "location not found")
    await db.delete(loc)
    await db.commit()