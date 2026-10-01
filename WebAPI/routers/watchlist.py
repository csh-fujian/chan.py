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
    reorder_folder_stocks,
    reorder_folders,
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


@router.put("/folders/reorder")
async def watchlist_reorder_folders(body: dict):
    """文件夹拖拽排序：body {"ids": [3, 1, 2]}，按下标全量覆盖 sort_order。"""
    ids = body.get("ids", None)
    if ids is None:
        raise HTTPException(status_code=422, detail="ids is required")
    if not isinstance(ids, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        raise HTTPException(status_code=422, detail="ids must be a list of folder ids")
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=422, detail="ids must not contain duplicates")
    ok = reorder_folders(ids)
    if not ok:
        raise HTTPException(status_code=404, detail="Some folders in ids not found")
    return {"success": True}


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
async def watchlist_folder_stocks(folder_id: int, q: str = Query("")):
    """分组内股票列表（含行业 + DuckDB 最新收盘价）；q 按 code/name 子串过滤。"""
    return get_folder_stocks(folder_id, q)


@router.put("/folders/{folder_id}/stocks/reorder")
async def watchlist_reorder_folder_stocks(folder_id: int, body: dict):
    """分组内股票拖拽排序：body {"codes": ["sz.000001", ...]}，按下标全量覆盖 sort_order。"""
    codes = body.get("codes", None)
    if codes is None:
        raise HTTPException(status_code=422, detail="codes is required")
    if not isinstance(codes, list) or not all(isinstance(c, str) for c in codes):
        raise HTTPException(status_code=422, detail="codes must be a list of stock codes")
    if len(set(codes)) != len(codes):
        raise HTTPException(status_code=422, detail="codes must not contain duplicates")
    ok = reorder_folder_stocks(folder_id, codes)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Some codes not found in folder {folder_id}")
    return {"success": True}


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