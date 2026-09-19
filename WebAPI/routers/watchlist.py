# -*- coding: utf-8 -*-
"""
Watchlist 路由 — 自选分组管理 API。
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..watchlist_store import (
    add_stock,
    create_folder,
    delete_folder,
    get_folder_stocks,
    list_folders,
    move_stock,
    remove_stock,
    rename_folder,
)

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


@router.get("/folders")
async def watchlist_folders():
    """自选分组列表。"""
    return list_folders()


@router.post("/folders")
async def watchlist_create_folder(body: dict):
    """新建分组。"""
    name = body.get("name", "")
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    return create_folder(name)


@router.patch("/folders/{folder_id}")
async def watchlist_rename_folder(folder_id: int, body: dict):
    """重命名分组。"""
    name = body.get("name", "")
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    ok = rename_folder(folder_id, name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Folder {folder_id} not found")
    return {"success": True}


@router.delete("/folders/{folder_id}")
async def watchlist_delete_folder(folder_id: int):
    """删除分组。"""
    ok = delete_folder(folder_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Folder {folder_id} not found")
    return {"success": True}


@router.post("/folders/{folder_id}/stocks")
async def watchlist_add_stock(folder_id: int, body: dict):
    """添加股票到分组。"""
    code = body.get("code", "")
    if not code:
        raise HTTPException(status_code=422, detail="code is required")
    add_stock(folder_id, code)
    return {"success": True}


@router.delete("/folders/{folder_id}/stocks/{code}")
async def watchlist_remove_stock(folder_id: int, code: str):
    """从分组移出股票。"""
    remove_stock(folder_id, code)
    return {"success": True}


@router.get("/folders/{folder_id}/stocks")
async def watchlist_folder_stocks(folder_id: int):
    """分组内股票列表（含行业 + DuckDB 最新收盘价）。"""
    return get_folder_stocks(folder_id)


@router.post("/move")
async def watchlist_move_stock(body: dict):
    """移动股票到其他分组。"""
    from_folder = body.get("from", 0)
    to_folder = body.get("to", 0)
    code = body.get("code", "")
    if not from_folder or not to_folder or not code:
        raise HTTPException(status_code=422, detail="from, to, code are required")
    ok = move_stock(from_folder, to_folder, code)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Stock {code!r} not found in folder {from_folder}",
        )
    return {"success": True}