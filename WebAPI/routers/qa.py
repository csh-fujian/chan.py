# -*- coding: utf-8 -*-
"""
QA 路由 — 大模型问答 API（kline-page-change design D4/D5/D8）。

- POST /api/qa                    SSE 流式问答（delta/done/error，D8.2）
- GET /api/qa                     本人问答记录（created_at 倒序，按 user_id 隔离）
- PATCH /api/qa/{qa_id}/star      单条打星/取消（校验归属，不属本人 → 404）
- POST /api/qa/star               批量打星（WHERE user_id=当前用户 AND id=ANY(ids)）
- DELETE /api/qa/unstarred        删除本人未打星记录
- GET/PUT /api/qa/system-prompt   系统提示词（user_setting，D8.3）

全部路由挂 get_current_user（仓库首个鉴权业务路由）。
"""

import asyncio
import json
import threading
from datetime import datetime
from typing import Iterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .. import qa_store
from ..auth import get_current_user
from ..chan_service import get_serialized_chan
from ..llm_client import complete_stream
from ..llm_prompts import DEFAULT_SYSTEM_PROMPT
from ..llm_store import resolve_llm_config

router = APIRouter(prefix="/api/qa", tags=["qa"])

# ask 流式块间空闲超时（design D8.2：requests timeout=(5, 30)）
STREAM_BLOCK_TIMEOUT = 30

# 结构注入裁剪上限（design D8.4）
CTX_KLINES = 20
CTX_BI = 10
CTX_SEG = 3
CTX_ZS = 3
CTX_BSP = 5


# ---- 请求体 ----

class AskBody(BaseModel):
    question: str
    code: Optional[str] = None
    period: Optional[str] = None


class StarBody(BaseModel):
    starred: bool


class BatchStarBody(BaseModel):
    ids: list[int]
    starred: bool


class SystemPromptBody(BaseModel):
    prompt: str


# ---- SSE 工具 ----

def _sse(obj: dict) -> str:
    """SSE 事件：data: 携带的单行 JSON（ensure_ascii=False）。"""
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _fmt_ts(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


def _fmt_endpoints(item: dict) -> str:
    return f"{_fmt_ts(item['begin']['t'])} {item['begin']['v']} → {_fmt_ts(item['end']['t'])} {item['end']['v']}"


def _fmt_sure(item: dict) -> str:
    return "" if item.get("is_sure") else "（未确认）"


# ---- 结构注入裁剪层（design D8.4，失败静默跳过） ----

def _build_structure_context(code: str, period: Optional[str]) -> str:
    """
    取 code/period 的缠论结构并裁剪拼成独立 context 段；任何失败静默返回空串。
    裁剪：最近 20 K线（OHLC 摘要）/ 10 笔 / 3 段 / 3+3 中枢 / 5 买卖点；is_sure=false 标注「未确认」。
    """
    try:
        data = get_serialized_chan(code, period or "1d")
    except Exception:
        return ""

    try:
        lines: list[str] = []
        kl_lines = [
            f"  {_fmt_ts(k['timestamp'])} O={k['open']} H={k['high']} L={k['low']} C={k['close']} V={k['volume']}"
            for k in data.get("klines", [])[-CTX_KLINES:]
        ]
        if kl_lines:
            lines.append("一、最近K线（OHLC 摘要）:")
            lines.extend(kl_lines)

        bi_lines = []
        for i, bi in enumerate(data.get("bi", [])[-CTX_BI:], 1):
            bi_lines.append(f"  {i}. {bi['dir']} {_fmt_endpoints(bi)} {_fmt_sure(bi)}")
        if bi_lines:
            lines.append("二、笔:")
            lines.extend(bi_lines)

        seg_lines = []
        for i, seg in enumerate(data.get("seg", [])[-CTX_SEG:], 1):
            seg_lines.append(f"  {i}. {seg['dir']} {_fmt_endpoints(seg)} {_fmt_sure(seg)}")
        if seg_lines:
            lines.append("三、线段:")
            lines.extend(seg_lines)

        zs_lines = [
            f"  {i}. [{_fmt_ts(zs['begin_t'])} → {_fmt_ts(zs['end_t'])}] ZG={zs['high']} ZD={zs['low']} 中枢={zs['mid']}"
            for i, zs in enumerate(data.get("zs", [])[-CTX_ZS:], 1)
        ]
        if zs_lines:
            lines.append("四、笔中枢:")
            lines.extend(zs_lines)

        seg_zs_lines = [
            f"  {i}. [{_fmt_ts(zs['begin_t'])} → {_fmt_ts(zs['end_t'])}] ZG={zs['high']} ZD={zs['low']} 中枢={zs['mid']}"
            for i, zs in enumerate(data.get("seg_zs", [])[-CTX_ZS:], 1)
        ]
        if seg_zs_lines:
            lines.append("五、线段中枢:")
            lines.extend(seg_zs_lines)

        bsp_lines = []
        for i, bsp in enumerate(data.get("bsp", [])[-CTX_BSP:], 1):
            kind = "买" if bsp["is_buy"] else "卖"
            types = "/".join(bsp.get("types") or [])
            bsp_lines.append(f"  {i}. {kind} {types} @{_fmt_ts(bsp['t'])} 价格={bsp['v']}")
        if bsp_lines:
            lines.append("六、买卖点:")
            lines.extend(bsp_lines)

        if not lines:
            return ""
        head = (
            f"【缠论结构上下文】标的 {code} 周期 {period or '1d'}"
            "（自动注入的最近片段，仅作分析参考；「未确认」为动态未完成结构）"
        )
        return head + "\n" + "\n".join(lines)
    except Exception:
        return ""


# ---- 问答路由 ----

@router.post("")
async def qa_ask(
    body: AskBody,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    大模型问答（SSE 流式，design D8.2）。

    事件契约（data: 单行 JSON）：
    - {"type":"delta","text":"..."}       LLM 增量文本
    - {"type":"done","record":{QaRecord}} 生成完成且落库成功（created_at 毫秒 epoch）
    - {"type":"error","detail":"..."}     生成/落库失败（LLM 失败不落库）
    """
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="question is required")

    # 1. 系统提示词（用户配置，空/缺省回退默认常量）
    system_prompt = (
        qa_store.get_setting(current_user["id"], "system_prompt") or DEFAULT_SYSTEM_PROMPT
    )

    # 2. LLM 配置解析（PG 激活预设 > env > 503）
    llm_cfg = resolve_llm_config()
    if llm_cfg is None:
        raise HTTPException(status_code=503, detail="LLM 未配置")

    user_id = current_user["id"]
    code, period = body.code, body.period

    # 客户端断开监听（design D8.2：中断即无记录）。响应任务被取消时，线程池中的
    # 同步生成器仍会跑完当前 next()，故显式监听 http.disconnect，生成器经标志位感知。
    aborted = threading.Event()
    loop = asyncio.get_running_loop()

    async def _watch_disconnect() -> None:
        while True:
            message = await request.receive()
            if message.get("type") == "http.disconnect":
                aborted.set()
                return

    watcher = asyncio.create_task(_watch_disconnect())

    def event_stream() -> Iterator[str]:
        # 3. 结构注入（失败静默跳过，不注入则纯文本）
        context = _build_structure_context(code, period) if code else ""
        prompt = f"{context}\n\n【用户问题】\n{question}" if context else question

        chunks: list[str] = []
        try:
            # 4. 边生成边发 delta
            for text in complete_stream(
                system_prompt, prompt, STREAM_BLOCK_TIMEOUT, config=llm_cfg
            ):
                if aborted.is_set():
                    return  # 客户端已断开：不落库、不发 done
                chunks.append(text)
                yield _sse({"type": "delta", "text": text})
            if aborted.is_set():
                return
            # 5. 全部完成后先落库，成功才发 done
            record = qa_store.create_record(user_id, question, "".join(chunks))
            yield _sse({"type": "done", "record": record})
        except HTTPException as e:
            yield _sse({"type": "error", "detail": e.detail})
        except Exception as e:
            yield _sse({"type": "error", "detail": str(e) or e.__class__.__name__})
        finally:
            try:
                loop.call_soon_threadsafe(watcher.cancel)
            except RuntimeError:
                pass  # 事件循环已关闭

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("")
async def qa_records(current_user: dict = Depends(get_current_user)):
    """本人问答记录列表（created_at 倒序）。"""
    return qa_store.list_records(current_user["id"])


@router.get("/system-prompt")
async def qa_get_system_prompt(current_user: dict = Depends(get_current_user)):
    """系统提示词（未设置/空 → 内置默认，design D8.3）。"""
    prompt = qa_store.get_setting(current_user["id"], "system_prompt")
    return {"prompt": prompt if prompt else DEFAULT_SYSTEM_PROMPT}


@router.put("/system-prompt")
async def qa_put_system_prompt(
    body: SystemPromptBody, current_user: dict = Depends(get_current_user)
):
    """写入系统提示词（空串即恢复默认）；仅当前用户。"""
    qa_store.set_setting(current_user["id"], "system_prompt", body.prompt)
    return {"success": True}


@router.post("/star")
async def qa_batch_star(body: BatchStarBody, current_user: dict = Depends(get_current_user)):
    """批量打星（仅当前用户的指定记录）。"""
    qa_store.batch_star(current_user["id"], body.ids, body.starred)
    return {"success": True}


@router.delete("/unstarred")
async def qa_delete_unstarred(current_user: dict = Depends(get_current_user)):
    """删除本人所有未打星记录。"""
    count = qa_store.delete_unstarred(current_user["id"])
    return {"success": True, "count": count}


@router.patch("/{qa_id}/star")
async def qa_star(
    qa_id: int, body: StarBody, current_user: dict = Depends(get_current_user)
):
    """单条打星/取消（记录不属本人 → 404）。"""
    ok = qa_store.star_record(current_user["id"], qa_id, body.starred)
    if not ok:
        raise HTTPException(status_code=404, detail=f"QA record {qa_id} not found")
    return {"success": True}
