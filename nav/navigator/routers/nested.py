"""Hierarchical endpoints: org → locations → services.

These are convenience endpoints that enforce the drill-down invariants:
- A location returned under an org is guaranteed to have organization_id == org_id.
- A service created under a location gets its organization_id from that location.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import Location, Organization, Service, ServiceAtLocation
from ..schemas import (
    LocationOut,
    LocationServiceIn,
    LocationServiceOut,
    ServiceIn,
)

router = APIRouter(tags=["nested"])


# ── Organizations → Locations ─────────────────────────────
@router.get(
    "/organizations/{org_id}/locations",
    response_model=list[LocationOut],
)
async def list_org_locations(org_id: UUID, db: AsyncSession = Depends(get_db)):
    if await db.get(Organization, org_id) is None:
        raise HTTPException(404, "organization not found")
    rows = (
        await db.execute(
            select(Location)
            .where(Location.organization_id == org_id)
            .order_by(Location.name.nulls_last(), Location.id)
        )
    ).scalars().all()
    return rows


# ── Locations → Services ──────────────────────────────────
@router.get(
    "/locations/{loc_id}/services",
    response_model=list[LocationServiceOut],
)
async def list_location_services(loc_id: UUID, db: AsyncSession = Depends(get_db)):
    if await db.get(Location, loc_id) is None:
        raise HTTPException(404, "location not found")

    stmt = (
        select(ServiceAtLocation, Service)
        .join(Service, Service.id == ServiceAtLocation.service_id)
        .where(ServiceAtLocation.location_id == loc_id)
        .order_by(Service.name)
    )
    rows = (await db.execute(stmt)).all()
    return [
        LocationServiceOut(
            **{k: getattr(svc, k) for k in LocationServiceOut.model_fields
               if hasattr(svc, k) and k != "service_at_location_id"},
            service_at_location_id=sal.id,
        )
        for sal, svc in rows
    ]


@router.post(
    "/locations/{loc_id}/services",
    response_model=LocationServiceOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_location_service(
    loc_id: UUID,
    payload: LocationServiceIn,
    db: AsyncSession = Depends(get_db),
):
    loc = await db.get(Location, loc_id)
    if loc is None:
        raise HTTPException(404, "location not found")
    if loc.organization_id is None:
        raise HTTPException(
            400,
            "location has no organization; assign one before adding services",
        )

    svc = Service(
        **payload.model_dump(exclude={"organization_id"}),
        organization_id=loc.organization_id,
    )
    db.add(svc)
    await db.flush()  # need svc.id for the link

    sal = ServiceAtLocation(service_id=svc.id, location_id=loc.id)
    db.add(sal)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(400, f"integrity error: {e.orig}")
    await db.refresh(svc)
    await db.refresh(sal)

    return LocationServiceOut(
        **{k: getattr(svc, k) for k in LocationServiceOut.model_fields
           if hasattr(svc, k) and k != "service_at_location_id"},
        service_at_location_id=sal.id,
    )


@router.delete(
    "/locations/{loc_id}/services/{service_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_location_service(
    loc_id: UUID, service_id: UUID, db: AsyncSession = Depends(get_db)
):
    sal = (
        await db.execute(
            select(ServiceAtLocation).where(
                ServiceAtLocation.location_id == loc_id,
                ServiceAtLocation.service_id == service_id,
            )
        )
    ).scalar_one_or_none()
    if sal is None:
        raise HTTPException(404, "service not found at this location")

    await db.delete(sal)
    await db.flush()

    # If the service is no longer linked anywhere, delete it too.
    remaining = (
        await db.execute(
            select(ServiceAtLocation.id).where(
                ServiceAtLocation.service_id == service_id
            )
        )
    ).scalars().all()
    if not remaining:
        svc = await db.get(Service, service_id)
        if svc is not None:
            await db.delete(svc)

    await db.commit()