from pathlib import PurePosixPath
from typing import Optional
import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.schemas.watch_path import WatchPathCreate, WatchPathRead, WatchPathUpdate
from app.db.session import async_session
from app.models.watch_path import WatchPath

router = APIRouter(tags=["library"])


def validate_watch_path(path: str) -> str:
    parsed = PurePosixPath(path)
    if not parsed.is_absolute():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Watch path must be an absolute container path.",
        )
    return str(parsed)


@router.post("", response_model=WatchPathRead, status_code=status.HTTP_201_CREATED)
async def create_watch_path(payload: WatchPathCreate) -> WatchPathRead:
    watch_path = WatchPath(
        path=validate_watch_path(payload.path),
        label=payload.label,
        scan_recursive=payload.scan_recursive,
        enabled=True,
    )

    async with async_session() as session:
        session.add(watch_path)
        try:
            await session.commit()
            await session.refresh(watch_path)
        except IntegrityError:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A watch path with this path already exists.",
            )

    return watch_path


@router.get("", response_model=list[WatchPathRead])
async def list_watch_paths() -> list[WatchPathRead]:
    async with async_session() as session:
        result = await session.execute(select(WatchPath))
        watch_paths = result.scalars().all()
    return watch_paths


@router.get("/{watch_path_id}", response_model=WatchPathRead)
async def get_watch_path(watch_path_id: uuid.UUID) -> WatchPathRead:
    async with async_session() as session:
        result = await session.execute(
            select(WatchPath).where(WatchPath.id == watch_path_id)
        )
        watch_path = result.scalar_one_or_none()

    if watch_path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Watch path not found.",
        )

    return watch_path


@router.patch("/{watch_path_id}", response_model=WatchPathRead)
async def update_watch_path(
    watch_path_id: uuid.UUID, payload: WatchPathUpdate
) -> WatchPathRead:
    async with async_session() as session:
        result = await session.execute(
            select(WatchPath).where(WatchPath.id == watch_path_id)
        )
        watch_path = result.scalar_one_or_none()

        if watch_path is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Watch path not found.",
            )

        updates = payload.model_dump(exclude_unset=True)
        if "label" in updates:
            watch_path.label = updates["label"]
        if "enabled" in updates:
            watch_path.enabled = updates["enabled"]
        if "scan_recursive" in updates:
            watch_path.scan_recursive = updates["scan_recursive"]

        session.add(watch_path)
        await session.commit()
        await session.refresh(watch_path)

    return watch_path


@router.delete("/{watch_path_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watch_path(watch_path_id: uuid.UUID) -> None:
    async with async_session() as session:
        result = await session.execute(
            select(WatchPath).where(WatchPath.id == watch_path_id)
        )
        watch_path = result.scalar_one_or_none()

        if watch_path is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Watch path not found.",
            )

        session.delete(watch_path)
        await session.commit()
