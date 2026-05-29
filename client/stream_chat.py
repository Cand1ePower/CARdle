"""
CARdle 多轮流式闲聊模块（非 FastAPI 服务，被 server.py 直接 import 调用）

核心设计：
  - request_chat_async : 预热/准备闲聊上下文，在 asyncio.gather 5 路并发中提前启动
  - process_chat_frames: 异步生成器，实现三帧推送协议 + TTS 分包优化
      * 开始帧 (status=0, frame="")
      * 中间帧 (status=1, frame=chunk) —— 标点断句 + 5字分包
      * 结束帧 (status=2, frame="")

TTS 分包逻辑：
  - 遇到 ，。？；！ 标点立即推送当前缓冲
  - 每积累 5 个字符推送一次
"""

import os
import re
import sys
import json
import httpx

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.llm_client import API_KEY, BASE_URL, IS_MOCK
from prompts import BOT_CHAT_SYSTEM_PROMPT
from utils import logger

MAX_HIS = 6
REMIND_TIMEOUT = 5.0
MODEL_ENDPOINT = os.getenv("MODEL_ENDPOINT", "doubao-pro-4k")


async def request_chat_async(query: str, sender_id: str = "default") -> dict:
    """
    预热闲聊请求：在 asyncio.gather 并发的第 5 路中提前准备好 LLM 调用上下文。
    仲裁结果出来前提前"排队"，若走闲聊分支可立即开始推流。

    Returns:
        dict: 包含 mode/reply/messages/degraded 等字段的上下文字典
    """
    logger.info(f"[StreamChat] 预热闲聊 sender_id={sender_id} query='{query}'")

    if IS_MOCK:
        # Mock 模式：预计算好回复，避免后续延迟
        if "谁" in query or "你是" in query:
            reply = "我是 CARdle 语音智能控制网联中心，是您的全能特斯拉风车机小管家。"
        elif "你好" in query or "好" == query:
            reply = "你好呀！有什么可以帮您的？"
        elif "笑话" in query:
            reply = "为什么电脑不能喝水？因为会蓝屏呀！"
        else:
            reply = "您说得太有意思了！很高兴为您服务~"
        return {"mode": "mock", "reply": reply, "degraded": False}

    # 真实模式：准备消息列表，实际流式调用在 process_chat_frames 中发起
    messages = [
        {"role": "system", "content": BOT_CHAT_SYSTEM_PROMPT},
        {"role": "user", "content": query}
    ]
    return {"mode": "real", "messages": messages, "query": query, "degraded": False}


async def process_chat_frames(chat_ctx: dict):
    """
    流式三帧协议异步生成器。
    调用方（server.py）通过 async for 遍历，对每一帧调用 sio.emit()。

    Yields:
        (frame_content: str, status: int)
        status=0 开始帧, status=1 中间帧, status=2 结束帧
    """
    # ── 开始帧 ──
    yield ("", 0)

    mode = chat_ctx.get("mode", "mock")

    if mode == "mock":
        reply = chat_ctx.get("reply", "抱歉，网络开小差了~")
        async for chunk in _tts_chunk_text(reply):
            yield (chunk, 1)

    else:
        # ── 真实流式调用 ──
        messages = chat_ctx.get("messages", [])
        headers = {
            "Content-Type": "application/json",
            "Authorization": API_KEY if API_KEY.startswith("Bearer") else f"Bearer {API_KEY}"
        }
        model_name = MODEL_ENDPOINT
        if "deepseek" in BASE_URL.lower() and "doubao" in model_name.lower():
            model_name = "deepseek-chat"

        body = {
            "model": model_name,
            "messages": messages,
            "stream": True
        }
        try:
            async with httpx.AsyncClient(timeout=REMIND_TIMEOUT) as client:
                async with client.stream("POST", BASE_URL, headers=headers, json=body) as response:
                    buffer = ""
                    counter = 1
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        line = line.lstrip("data: ")
                        if line == "[DONE]":
                            break
                        try:
                            data = json.loads(line)
                            if data["choices"][0].get("finish_reason") == "stop":
                                break
                            text = data["choices"][0]["delta"].get("content", "")
                            buffer += text

                            # TTS 优化1：标点立即断句推送
                            if re.search(r'[，。？；！]', text):
                                yield (buffer, 1)
                                buffer = ""
                                counter = 1
                                continue

                            # TTS 优化2：每 5 字推送一次
                            if counter % 5 == 0:
                                yield (buffer, 1)
                                buffer = ""
                            counter += 1

                        except Exception:
                            continue

                    # 剩余尾巴内容推送
                    if buffer and buffer.strip():
                        yield (buffer, 1)

        except Exception as e:
            logger.error(f"[StreamChat] 流式调用失败: {e}")
            yield ("抱歉，舱舱现在网络开小差了，请您再说一遍呢~", 1)

    # ── 结束帧 ──
    yield ("", 2)


async def _tts_chunk_text(text: str):
    """对非流式文本做相同的 TTS 标点断句+5字分包，保持帧结构完全一致"""
    buffer = ""
    counter = 1
    for char in text:
        buffer += char
        if re.search(r'[，。？；！]', char):
            yield buffer
            buffer = ""
            counter = 1
            continue
        if counter % 5 == 0:
            yield buffer
            buffer = ""
        counter += 1
    if buffer.strip():
        yield buffer
