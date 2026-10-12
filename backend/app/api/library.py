from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException

from backend.app.core.paths import UnsafePathError
from backend.app.core.schemas import ApiResponse
from backend.app.services.archive_service import ArchivePathCollisionError
from backend.app.services.library_service import library_service
from backend.app.services.task_runner import task_runner

router = APIRouter(prefix="/api/library", tags=["library"])


@router.get("", response_model=ApiResponse)
async def list_library(
    q: str | None = None,
    status: str | None = None,
    sort_by: str = "updated_at",
    sort_order: Literal["asc", "desc"] = "desc",
    zip_status: Literal["zipped", "unzipped"] | None = None,
):
    return ApiResponse(data=await library_service.list(
        q=q, status=status, sort_by=sort_by, sort_order=sort_order, zip_status=zip_status,
    ))


@router.get("/{manga_id}", response_model=ApiResponse)
async def get_library_item(manga_id: str):
    item = await library_service.get(manga_id)
    if item is None:
        raise HTTPException(status_code=404, detail="资料库项目不存在")
    return ApiResponse(data=item)


@router.post("/{manga_id}/verify", response_model=ApiResponse)
async def verify_library_item(manga_id: str):
    item = await library_service.verify(manga_id)
    if item is None:
        raise HTTPException(status_code=404, detail="资料库项目不存在")
    return ApiResponse(data=item)


@router.post("/{manga_id}/zip", response_model=ApiResponse)
async def zip_library_item(manga_id: str, overwrite: bool = True):
    try:
        item = await library_service.zip(manga_id, overwrite=overwrite)
    except ArchivePathCollisionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except UnsafePathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if item is None:
        raise HTTPException(status_code=404, detail="资料库项目不存在")
    return ApiResponse(data=item)


@router.post("/{manga_id}/retry-failed", response_model=ApiResponse)
async def retry_failed_library_files(manga_id: str, background_tasks: BackgroundTasks):
    result = await library_service.create_failed_retry_task(manga_id)
    if result is None:
        raise HTTPException(status_code=404, detail="资料库项目不存在")
    task = result.get("task")
    if result["status"] == "queued" and task:
        background_tasks.add_task(task_runner.run_failed_images, task["task_id"])
    return ApiResponse(data=result)


@router.delete("/{manga_id}", response_model=ApiResponse)
async def delete_library_item(manga_id: str, delete_files: bool = False):
    try:
        item = await library_service.delete(manga_id, delete_files=delete_files)
    except ArchivePathCollisionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except UnsafePathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if item is None:
        raise HTTPException(status_code=404, detail="资料库项目不存在")
    return ApiResponse(data=item)
