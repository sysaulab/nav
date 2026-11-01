from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import Organization, Service
from ..schemas import ServiceIn, ServiceOut

router = APIRouter(prefix="/services", tags=["services"])


@router.get("", response_model=list[ServiceOut])
async def list_services(
    db: AsyncSession = Depends(get_db),
    organization_id: UUID | None = None,
):
    stmt = select(Service)
    if organization_id is not None:
        stmt = stmt.where(Service.organization_id == organization_id)
    rows = (await db.execute(stmt.order_by(Service.name))).scalars().all()
    return rows


@router.post("", response_model=ServiceOut, status_code=status.HTTP_201_CREATED)
async def create_service(payload: ServiceIn, db: AsyncSession = Depends(get_db)):
    if await db.get(Organization, payload.organization_id) is None:
        raise HTTPException(400, f"organization {payload.organization_id} does not exist")

    svc = Service(**payload.model_dump())
    db.add(svc)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(400, f"integrity error: {e.orig}")
    await db.refresh(svc)
    return svc


@router.get("/{service_id}", response_model=ServiceOut)
async def get_service(service_id: UUID, db: AsyncSession = Depends(get_db)):
    svc = await db.get(Service, service_id)
    if not svc:
        raise HTTPException(404, "service not found")
    return svc


@router.patch("/{service_id}", response_model=ServiceOut)
async def update_service(
    service_id: UUID, payload: ServiceIn, db: AsyncSession = Depends(get_db)
):
    svc = await db.get(Service, service_id)
    if not svc:
        raise HTTPException(404, "service not found")
    if payload.organization_id != svc.organization_id:
        if await db.get(Organization, payload.organization_id) is None:
            raise HTTPException(400, f"organization {payload.organization_id} does not exist")
    for k, v in payload.model_dump().items():
        setattr(svc, k, v)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(400, f"integrity error: {e.orig}")
    await db.refresh(svc)
    return svc


@router.delete("/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_service(service_id: UUID, db: AsyncSession = Depends(get_db)):
    svc = await db.get(Service, service_id)
    if not svc:
        raise HTTPException(404, "service not found")
    await db.delete(svc)
    await db.commit()