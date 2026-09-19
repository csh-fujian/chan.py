# -*- coding: utf-8 -*-
"""
QA 路由 — 大模型问答 API（stub）。
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/qa", tags=["qa"])


@router.post("")
async def qa_ask(body: dict):
    """大模型问答。"""
    return {
        "id": 0,
        "question": body.get("question", ""),
        "answer": "",
        "starred": False,
        "created_at": 0,
    }


@router.get("")
async def qa_records():
    """问答记录列表。"""
    return []


@router.post("/star")
async def qa_batch_star(body: dict):
    """批量打星。"""
    return {"success": True}


@router.delete("/unstarred")
async def qa_delete_unstarred():
    """删除未打星记录。"""
    return {"success": True}


@router.patch("/{qa_id}/star")
async def qa_star(qa_id: int, body: dict):
    """打星/取消收藏。"""
    return {"success": True}