from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import Organization
from ..schemas import OrganizationIn, OrganizationOut

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("", response_model=list[OrganizationOut])
async def list_organizations(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Organization).order_by(Organization.name))).scalars().all()
    return rows


@router.post("", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
async def create_organization(payload: OrganizationIn, db: AsyncSession = Depends(get_db)):
    org = Organization(**payload.model_dump())
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


@router.get("/{org_id}", response_model=OrganizationOut)
async def get_organization(org_id: UUID, db: AsyncSession = Depends(get_db)):
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, "organization not found")
    return org


@router.patch("/{org_id}", response_model=OrganizationOut)
async def update_organization(
    org_id: UUID, payload: OrganizationIn, db: AsyncSession = Depends(get_db)
):
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, "organization not found")
    for k, v in payload.model_dump().items():
        setattr(org, k, v)
    await db.commit()
    await db.refresh(org)
    return org


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(org_id: UUID, db: AsyncSession = Depends(get_db)):
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, "organization not found")
    await db.delete(org)
    await db.commit()