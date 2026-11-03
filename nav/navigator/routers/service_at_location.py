from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import Location, Service, ServiceAtLocation
from ..schemas import ServiceAtLocationIn, ServiceAtLocationOut

router = APIRouter(prefix="/service_at_location", tags=["service_at_location"])


@router.get("", response_model=list[ServiceAtLocationOut])
async def list_service_at_location(
    db: AsyncSession = Depends(get_db),
    service_id: UUID | None = None,
    location_id: UUID | None = None,
):
    stmt = select(ServiceAtLocation)
    if service_id is not None:
        stmt = stmt.where(ServiceAtLocation.service_id == service_id)
    if location_id is not None:
        stmt = stmt.where(ServiceAtLocation.location_id == location_id)
    rows = (await db.execute(stmt.order_by(ServiceAtLocation.created_at))).scalars().all()
    return rows


@router.post("", response_model=ServiceAtLocationOut, status_code=status.HTTP_201_CREATED)
async def create_service_at_location(
    payload: ServiceAtLocationIn, db: AsyncSession = Depends(get_db)
):
    if await db.get(Service, payload.service_id) is None:
        raise HTTPException(400, f"service {payload.service_id} does not exist")
    if await db.get(Location, payload.location_id) is None:
        raise HTTPException(400, f"location {payload.location_id} does not exist")

    sal = ServiceAtLocation(**payload.model_dump())
    db.add(sal)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        # UniqueConstraint (service_id, location_id)
        raise HTTPException(409, "this service is already linked to this location")
    await db.refresh(sal)
    return sal


@router.get("/{sal_id}", response_model=ServiceAtLocationOut)
async def get_service_at_location(sal_id: UUID, db: AsyncSession = Depends(get_db)):
    sal = await db.get(ServiceAtLocation, sal_id)
    if not sal:
        raise HTTPException(404, "service_at_location not found")
    return sal


@router.delete("/{sal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_service_at_location(sal_id: UUID, db: AsyncSession = Depends(get_db)):
    sal = await db.get(ServiceAtLocation, sal_id)
    if not sal:
        raise HTTPException(404, "service_at_location not found")
    await db.delete(sal)
    await db.commit()