"""文案分段、生成与检索词建议。"""
from __future__ import annotations

import logging
import re

import aiosqlite
from fastapi import HTTPException

from app.core.llm import LLMClient, LLMConfig
from app.db.database import DB_PATH
from app.models.script_stock import (
    ScriptStockGenerateScriptRequest,
    ScriptStockGenerateScriptResponse,
    ScriptStockSplitRequest,
    ScriptStockSplitResponse,
    ScriptStockSuggestQueriesRequest,
    ScriptStockSuggestQueriesResponse,
)

from app.api.script_stock_shared import parse_json_array, router, split_script_text

logger = logging.getLogger(__name__)


@router.post("/split", response_model=ScriptStockSplitResponse)
async def split_script(req: ScriptStockSplitRequest) -> ScriptStockSplitResponse:
    segs = split_script_text(req.script, req.mode)
    if not segs:
        raise HTTPException(400, "文案为空或无法分段")
    return ScriptStockSplitResponse(segments=segs)


@router.post("/generate-script", response_model=ScriptStockGenerateScriptResponse)
async def generate_script(req: ScriptStockGenerateScriptRequest) -> ScriptStockGenerateScriptResponse:
    topic = (req.topic or "").strip()
    if not topic:
        raise HTTPException(400, "请填写主题或关键词")
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            llm_cfg = await LLMConfig.get_llm_params_with_defaults(db)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))

    style = (req.style_hint or "").strip()
    n = int(req.num_paragraphs)
    sys_msg = (
        "你是短视频旁白撰稿人。根据用户给的主题写出中文口播/旁白文案。"
        "要求：分段清晰，每段 1~3 句，段落之间语义连贯；不要编号列表符号；不要 Markdown。"
        f"输出恰好 {n} 个段落，段落之间用一个空行分隔。"
    )
    user_msg = f"主题：{topic}\n"
    if style:
        user_msg += f"风格补充：{style}\n"

    try:
        llm = LLMClient(
            base_url=llm_cfg["base_url"],
            api_key=llm_cfg["api_key"],
            model=llm_cfg["model"],
            temperature=min(0.9, float(llm_cfg.get("temperature") or 0.7)),
            max_tokens=min(8192, int(llm_cfg.get("max_tokens") or 65536)),
            timeout=120.0,
        )
        content = await llm.chat(
            [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}],
            temperature=0.75,
            max_tokens=min(8192, int(llm_cfg.get("max_tokens") or 65536)),
        )
    except Exception as e:
        logger.error("generate-script LLM error: %s", e)
        raise HTTPException(502, detail=f"LLM 生成失败: {e}")

    script = (content or "").strip()
    if not script:
        raise HTTPException(502, detail="LLM 返回为空")
    return ScriptStockGenerateScriptResponse(script=script)


@router.post("/suggest-queries", response_model=ScriptStockSuggestQueriesResponse)
async def suggest_queries(req: ScriptStockSuggestQueriesRequest) -> ScriptStockSuggestQueriesResponse:
    if not req.segments:
        raise HTTPException(400, "segments 不能为空")
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            llm_cfg = await LLMConfig.get_llm_params_with_defaults(db)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))

    lines = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(req.segments))
    sys_msg = (
        "你是素材检索助手。给定多条中文短视频文案，请为每一条提取一个英文关键词短语，"
        "用于在免费素材站搜索短视频（风景、人物、城市、科技等）。"
        "输出必须是 JSON 数组，长度与输入条数相同，例如："
        '[\"ocean sunset\",\"coffee shop\"] ，不要其它解释文字。'
    )
    user_msg = f"文案段落：\n{lines}"

    try:
        llm = LLMClient(
            base_url=llm_cfg["base_url"],
            api_key=llm_cfg["api_key"],
            model=llm_cfg["model"],
            temperature=0.3,
            max_tokens=min(65536, int(llm_cfg.get("max_tokens") or 2048)),
            timeout=90.0,
        )
        content = await llm.chat(
            [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}],
            temperature=0.2,
            max_tokens=min(65536, int(llm_cfg.get("max_tokens") or 2048)),
        )
        arr = parse_json_array(content)
        if not isinstance(arr, list):
            raise ValueError("not a list")
        queries = [str(x).strip() for x in arr][: len(req.segments)]
        while len(queries) < len(req.segments):
            queries.append(queries[-1] if queries else "nature")
    except Exception as e:
        logger.warning("suggest-queries fallback: %s", e)
        queries = []
        for t in req.segments:
            toks = re.findall(r"[A-Za-z]{3,}", t)
            queries.append(" ".join(toks[:4]) if toks else "lifestyle")

    return ScriptStockSuggestQueriesResponse(queries=queries[: len(req.segments)])
