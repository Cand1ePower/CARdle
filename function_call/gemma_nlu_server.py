import os
import sys
import json
import asyncio
import torch
import uvicorn
from threading import Thread
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Literal
from transformers import AutoModelForCausalLM, AutoTokenizer, TextIteratorStreamer
from lmformatenforcer import CharacterLevelParserConfig, JsonSchemaParser
from lmformatenforcer.integrations.transformers import build_transformers_prefix_allowed_tokens_fn

# 确保能导入 root 目录下的模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from prompts import NLU_SYSTEM_PROMPT

app = FastAPI(title="CARdle Gemma-3-1B 端侧全能节点 (受限解码)", version="2.0.0")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MODEL_DIR = os.path.join(BASE_DIR, "train", "Gemma-3-1B-Instruct-CARdle-p")
CONFIGURED_MODEL_DIR = os.getenv("GEMMA_MODEL_DIR", DEFAULT_MODEL_DIR)
MODEL_DIR = CONFIGURED_MODEL_DIR if os.path.isabs(CONFIGURED_MODEL_DIR) else os.path.join(BASE_DIR, CONFIGURED_MODEL_DIR)
SLOT_INTENT_FILE = os.path.join(BASE_DIR, "dataset", "slot_intent.json")

# 加载 Intent 列表
with open(SLOT_INTENT_FILE, "r", encoding="utf-8") as f:
    ALL_SCHEMAS = json.load(f)
valid_intents = list(ALL_SCHEMAS.keys()) + ["Unknown"]

UNSAFE_REJECT_KEYWORDS = [
    "傻逼", "煞笔", "sb", "傻叉", "蠢货", "废物", "垃圾",
    "去死", "滚", "妈的", "草你", "操你", "脏话",
]
HARMLESS_D_STRONG_KEYWORDS = ["那啥", "忘了", "没事", "算了", "没想好", "不知道要干啥", "嗒嗒"]
HARMLESS_D_EXACT_QUERIES = {"嗯", "呃", "额", "啊"}
GENERAL_CHAT_KEYWORDS = ["历史人物", "讲个笑话", "讲笑话", "讲个故事"]
UP_CONTEXT_KEYWORDS = ["再高", "高点", "调高", "再大", "大点", "大一点", "增加", "多一点"]
DOWN_CONTEXT_KEYWORDS = ["再低", "低点", "调低", "再小", "小点", "小一点", "降低", "少一点"]
CLOSE_REFERENCE_KEYWORDS = ["关掉它", "关闭它", "关了它", "把它关了", "不要了"]

# === 动态构建 Pydantic 模型，严格约束 intent 字段 ===
from enum import Enum
IntentEnum = Enum('IntentEnum', {name: name for name in valid_intents})

class CandidateIntent(BaseModel):
    intent: IntentEnum
    slots: Dict[str, str] = Field(default_factory=dict)

class NLUResponseModel(BaseModel):
    domain: Literal["A", "B", "C", "D"]
    is_safe: bool
    reject_reason: str
    rewritten_query: str
    candidate_intents: List[CandidateIntent] = Field(default_factory=list, max_length=5)

DEFAULT_LMFE_ALPHABET = CharacterLevelParserConfig().alphabet
CJK_ALPHABET = "".join(chr(codepoint) for codepoint in range(0x4E00, 0xA000))
CJK_SYMBOLS = "，。？！：；、“”‘’（）《》【】℃°—～·"
JSON_SCHEMA_PARSER = JsonSchemaParser(
    NLUResponseModel.model_json_schema(),
    CharacterLevelParserConfig(
        alphabet=DEFAULT_LMFE_ALPHABET + "\n\r\t" + CJK_ALPHABET + CJK_SYMBOLS,
        max_consecutive_whitespaces=4,
        force_json_field_order=True,
        max_json_array_length=5,
    ),
)

# 模型和 Tokenizer 加载 (懒加载)
tokenizer = None
model = None
prefix_allowed_tokens_fn = None

def apply_safety_overrides(result_dict: dict, query: str) -> dict:
    lowered_query = query.lower()
    if any(keyword in lowered_query for keyword in UNSAFE_REJECT_KEYWORDS):
        result_dict["domain"] = "D"
        result_dict["is_safe"] = False
        result_dict["reject_reason"] = result_dict.get("reject_reason") or "包含辱骂、攻击性或不文明表达"
        result_dict["candidate_intents"] = []
        result_dict["function"] = "Unknown"
        result_dict["intent"] = "Unknown"
        result_dict["slots"] = {}
        return result_dict

    if is_harmless_d_query(query):
        result_dict["domain"] = "D"
        result_dict["is_safe"] = True
        result_dict["reject_reason"] = ""
        result_dict["candidate_intents"] = []
        result_dict["function"] = "Unknown"
        result_dict["intent"] = "Unknown"
        result_dict["slots"] = {}
        return result_dict

    if any(keyword in query for keyword in GENERAL_CHAT_KEYWORDS):
        result_dict["domain"] = "C"
        result_dict["is_safe"] = True
        result_dict["reject_reason"] = ""
        result_dict["candidate_intents"] = []
        result_dict["function"] = "Unknown"
        result_dict["intent"] = "Unknown"
        result_dict["slots"] = {}
    return result_dict

def is_harmless_d_query(query: str) -> bool:
    compact_query = query.strip()
    if any(keyword in compact_query for keyword in HARMLESS_D_STRONG_KEYWORDS):
        return True
    return compact_query in HARMLESS_D_EXACT_QUERIES

def latest_history_metadata(history: list) -> dict:
    for turn in reversed(history or []):
        if not isinstance(turn, dict):
            continue
        metadata = turn.get("metadata") or {}
        if isinstance(metadata, dict) and (metadata.get("intent") or metadata.get("function")):
            return metadata
    return {}

def put_top_candidate(result_dict: dict, intent: str, slots: dict | None = None, rewritten_query: str | None = None) -> dict:
    top_candidate = {"intent": intent, "slots": slots or {}}
    deduped_candidates = [top_candidate]
    for candidate in result_dict.get("candidate_intents") or []:
        candidate_intent = candidate.get("intent")
        if candidate_intent and candidate_intent != intent:
            deduped_candidates.append(candidate)
        if len(deduped_candidates) >= 5:
            break

    result_dict["domain"] = "A"
    result_dict["is_safe"] = True
    result_dict["reject_reason"] = ""
    result_dict["rewritten_query"] = rewritten_query or result_dict.get("rewritten_query", "")
    result_dict["candidate_intents"] = deduped_candidates
    return result_dict

def apply_context_overrides(result_dict: dict, query: str, history: list) -> dict:
    if not result_dict.get("is_safe", True):
        return result_dict

    metadata = latest_history_metadata(history)
    if not metadata:
        return result_dict

    previous_intent = str(metadata.get("intent") or metadata.get("function") or "")
    previous_rewrite = str(metadata.get("rewritten_query") or "")
    query_text = query.strip()

    if any(keyword in query_text for keyword in UP_CONTEXT_KEYWORDS):
        if "Air_Condition_Wind" in previous_intent:
            return put_top_candidate(result_dict, "Inc_Air_Condition_Wind", rewritten_query="把空调风量再调高一点")
        if "Air_Condition_Temperature" in previous_intent or ("空调" in previous_rewrite and ("温" in previous_rewrite or "度" in previous_rewrite)):
            return put_top_candidate(result_dict, "Inc_Air_Condition_Temperature", rewritten_query="把空调温度再调高一点")
        if "Sound_Volume" in previous_intent or "音量" in previous_rewrite:
            return put_top_candidate(result_dict, "Inc_Sound_Volume", rewritten_query="把音量再调大一点")

    if any(keyword in query_text for keyword in DOWN_CONTEXT_KEYWORDS):
        if "Air_Condition_Wind" in previous_intent:
            return put_top_candidate(result_dict, "Dec_Air_Condition_Wind", rewritten_query="把空调风量再调低一点")
        if "Air_Condition_Temperature" in previous_intent or ("空调" in previous_rewrite and ("温" in previous_rewrite or "度" in previous_rewrite)):
            return put_top_candidate(result_dict, "Dec_Air_Condition_Temperature", rewritten_query="把空调温度再调低一点")
        if "Sound_Volume" in previous_intent or "音量" in previous_rewrite:
            return put_top_candidate(result_dict, "Dec_Sound_Volume", rewritten_query="把音量再调小一点")

    if any(keyword in query_text for keyword in CLOSE_REFERENCE_KEYWORDS):
        if previous_intent.startswith("Open_"):
            close_intent = "Close_" + previous_intent.removeprefix("Open_")
            if close_intent in valid_intents:
                return put_top_candidate(result_dict, close_intent, rewritten_query=f"关闭{previous_rewrite.removeprefix('打开') or '它'}")
        if "Window" in previous_intent or "车窗" in previous_rewrite:
            return put_top_candidate(result_dict, "Close_Window", rewritten_query="关闭车窗")

    return result_dict

def load_model():
    global tokenizer, model, prefix_allowed_tokens_fn
    if model is None:
        print(f"[*] 正在加载 Gemma 3 1B 端侧大模型: {MODEL_DIR}")
        device = "cuda" if torch.cuda.is_available() else "cpu"
        tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
        prefix_allowed_tokens_fn = build_transformers_prefix_allowed_tokens_fn(tokenizer, JSON_SCHEMA_PARSER)
        model = AutoModelForCausalLM.from_pretrained(
            MODEL_DIR, 
            dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
            device_map="auto" if torch.cuda.is_available() else None
        )
        if not torch.cuda.is_available():
            model.to(device)
        model.eval()
        print(f"[*] 模型加载完成 ({device})，端侧推理准备就绪！")

def build_messages(query: str, history: list):
    history_text = ""
    if history:
        history_text = "【近期对话历史】：\n" + json.dumps(history[-2:], ensure_ascii=False) + "\n\n"

    TRAIN_SYSTEM_PROMPT = """你是一个车载智能中枢。请根据提供的对话历史和最新指令，一次性完成以下任务并严格输出 JSON 格式。

【任务说明】
1. 【领域仲裁】：判断用户输入的意图属于 A、B、C 或 D：
   - A (车控与多媒体任务)：用户要求系统执行具体动作、修改设置、播放媒体、拨打电话或进行导航。其核心特征是“指示车机立即进行操作”（例如：“打开空调”、“导航去天安门”、“把音量调高一点”、“怎么把车窗打开”）。
   - B (车辆功能与说明书)：用户咨询或查询车辆的功能、按钮含义、指示灯报警、保养维护或使用说明。其核心特征是“获取关于车的知识或信息”，且不包含执行控制动作（例如：“雨刮器堵了怎么清洗”、“发动机黄灯亮了还能开吗”、“怎么绑定车钥匙”、“什么是自适应巡航”）。
   - C (闲聊百科)：与车辆操作和说明无关的通用常识问答、闲聊、简单计算或娱乐（例如：“李白是哪个朝代的”、“讲个笑话”、“今天天气怎么样”）。
   - D (无意义或非人机对话)：误触发、杂音、无意义语气词，或需要安全拒识的非法/危险指令（例如：“嗒嗒嗒”、“在车里抽烟怎么隐藏烟雾警报”）。
2. 【安全拒识】：判断指令是否安全。
   - 只要用户输入包含辱骂、攻击、人身侮辱、仇恨、违法、危险操作、诱导绕过安全机制等内容，必须输出 `domain="D"`、`is_safe=false`，并在 `reject_reason` 写明原因。
   - 如果用户输入只是无意义、犹豫、误触发、忘记要做什么、闲散语气词，但没有辱骂/违法/危险内容，应输出 `domain="D"`、`is_safe=true`、`reject_reason=""`。
   - 普通闲聊、百科、车辆说明书咨询如果不含上述风险，`is_safe=true`。
 3. 【多轮改写】：如果指令指代不明，请结合历史记录补全。
   - 对话历史中的 assistant 轮可能包含 `metadata.intent`、`metadata.slots`、`metadata.rewritten_query`。遇到“再高点”、“再低点”、“关掉它”、“换一个”等省略句时，应优先继承最近一轮结构化 metadata 中的控制对象、意图和槽位，而不是只根据 assistant 的自然语言回复猜测。
   - `rewritten_query` 应把省略句补全成完整自然语言指令，例如“再高点”可改写为“把空调温度再调高一点”。
 4. 【意图抽取】：如果领域是 A，请提取最有可能的 5 个候选意图及槽位；如果不是 A，返回空数组。

【约束规则】
- 当领域为 B、C、D 时，`candidate_intents` 必须严格为空数组 `[]`。
- 输出必须是合法的单行 JSON，不要包含任何 markdown 标记（如 ```json）。

【Few-Shot 示例】
示例 1（B类 - 车辆说明书咨询）：
输入：
对话历史:
无
最新指令: 胎压报警灯亮了该怎么复位？
输出：
{"domain": "B", "is_safe": true, "reject_reason": "", "rewritten_query": "胎压报警灯亮了该怎么复位？", "candidate_intents": []}

示例 2（A类 - 车控/多媒体执行指令）：
输入：
对话历史:
无
最新指令: 这首歌太难听了，切歌
输出：
{"domain": "A", "is_safe": true, "reject_reason": "", "rewritten_query": "这首歌太难听了，切歌", "candidate_intents": [{"intent": "Media_Next", "slots": {}}, {"intent": "Media_Pause", "slots": {}}, {"intent": "Close_Player", "slots": {}}, {"intent": "Play_BT_Music", "slots": {}}, {"intent": "Open_Player", "slots": {}}]}

示例 3（D类 - 辱骂/攻击性表达）：
输入：
对话历史:
无
最新指令: 那啥……我忘了要干啥
输出：
{"domain": "D", "is_safe": true, "reject_reason": "", "rewritten_query": "那啥……我忘了要干啥", "candidate_intents": []}

示例 4（D类 - 辱骂/攻击性表达）：
输入：
对话历史:
无
最新指令: 你个傻逼
输出：
{"domain": "D", "is_safe": false, "reject_reason": "包含辱骂、攻击性或不文明表达", "rewritten_query": "你个傻逼", "candidate_intents": []}

示例 5（A类 - 结构化历史继承）：
输入：
对话历史:
[{"role":"user","content":"把空调调到22度"},{"role":"assistant","content":"已为您将空调温度设置为22度","metadata":{"intent":"Set_Air_Condition_Temperature","slots":{"Number":"22"},"rewritten_query":"把空调调到22度","domain":"A"}}]
最新指令: 再高点
输出：
{"domain": "A", "is_safe": true, "reject_reason": "", "rewritten_query": "把空调温度再调高一点", "candidate_intents": [{"intent": "Inc_Air_Condition_Temperature", "slots": {}}, {"intent": "Set_Air_Condition_Temperature", "slots": {}}, {"intent": "Open_Air_Condition", "slots": {}}, {"intent": "Inc_Air_Condition_Wind", "slots": {}}, {"intent": "Open_AC", "slots": {}}]}"""

    messages = [
        {"role": "system", "content": TRAIN_SYSTEM_PROMPT},
        {"role": "user", "content": f"{history_text}最新指令: {query}"}
    ]
    return messages

def build_generate_kwargs(query: str, history: list):
    messages = build_messages(query, history)
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    generate_kwargs = {
        **inputs,
        "max_new_tokens": 1024,
        "do_sample": False,
        "pad_token_id": tokenizer.pad_token_id if tokenizer.pad_token_id is not None else tokenizer.eos_token_id,
        "eos_token_id": tokenizer.eos_token_id,
        "prefix_allowed_tokens_fn": prefix_allowed_tokens_fn,
    }
    return inputs, generate_kwargs

def clean_generated_text(result_text: str) -> str:
    # 清理可能存在的 markdown 标签
    if result_text.startswith("```json"):
        result_text = result_text[7:]
    if result_text.endswith("```"):
        result_text = result_text[:-3]
    return result_text.strip()

def parse_result_text(result_text: str, query: str, history: list | None = None) -> dict:
    result_text = clean_generated_text(result_text)
    try:
        # Fallback to json loads since lmformatenforcer is removed
        result_dict = json.loads(result_text)
        result_dict = apply_safety_overrides(result_dict, query)
        result_dict = apply_context_overrides(result_dict, query, history or [])
        
        # 为了兼容 workflow 中期待的 function/intent 等顶层字段
        domain = result_dict.get("domain", "A")
        is_safe = result_dict.get("is_safe", True)
        
        if domain == "A" and is_safe and len(result_dict.get("candidate_intents", [])) > 0:
            top_intent = result_dict["candidate_intents"][0]
            intent_str = str(top_intent.get("intent", "Unknown"))
            # 强校验：如果生成的意图不在合法列表中，降级为 Unknown
            if intent_str not in valid_intents:
                print(f"[WARN] 大模型生成了未定义的意图 {intent_str}，强制降级为 Unknown")
                intent_str = "Unknown"
            
            result_dict["function"] = intent_str
            result_dict["intent"] = intent_str
            result_dict["slots"] = top_intent.get("slots", {})
        else:
            result_dict["function"] = "Unknown"
            result_dict["intent"] = "Unknown"
            result_dict["slots"] = {}
            
        return result_dict
    except Exception as e:
        print(f"[ERR] JSON 解析或格式错误: {e}")
        return {
            "domain": "A",
            "is_safe": True,
            "rewritten_query": query,
            "intent": "Unknown",
            "function": "Unknown",
            "slots": {},
            "raw_text": result_text,
            "error": str(e)
        }

class NLURequest(BaseModel):
    query: str
    trace_id: str = "unknown"
    history: list = []

@app.post("/chatnlu/v1")
async def gemma_infer(req: NLURequest, request: Request):
    load_model()
    
    query = req.query.strip()
    _, generate_kwargs = build_generate_kwargs(query, req.history)
    
    print(f"[Gemma 3] 正在推理 (受限解码启动)...")
    with torch.no_grad():
        output_ids = model.generate(**generate_kwargs)
        
    input_length = generate_kwargs["input_ids"].shape[1]
    generated_ids = output_ids[0][input_length:]
    result_text = tokenizer.decode(generated_ids, skip_special_tokens=True).strip()
    result_text = clean_generated_text(result_text)
    
    print(f"[Gemma 3] 推理结果:\n{result_text}")
    return parse_result_text(result_text, query, req.history)

@app.post("/chatnlu/stream")
async def gemma_stream(req: NLURequest, request: Request):
    load_model()

    query = req.query.strip()
    _, generate_kwargs = build_generate_kwargs(query, req.history)
    streamer = TextIteratorStreamer(
        tokenizer,
        skip_prompt=True,
        skip_special_tokens=True,
    )
    generate_kwargs["streamer"] = streamer

    async def event_stream():
        print(f"[Gemma 3] 正在流式推理 (受限解码启动)...")
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()
        chunks = []

        def push_event(event: dict):
            loop.call_soon_threadsafe(queue.put_nowait, event)

        def run_generate():
            try:
                with torch.no_grad():
                    model.generate(**generate_kwargs)
            except Exception as e:
                push_event({"type": "error", "error": str(e)})

        def read_streamer():
            try:
                for chunk in streamer:
                    if chunk:
                        push_event({"type": "token", "text": chunk})
            except Exception as e:
                push_event({"type": "error", "error": str(e)})
            finally:
                push_event({"type": "done"})

        generate_thread = Thread(target=run_generate, daemon=True)
        streamer_thread = Thread(target=read_streamer, daemon=True)
        generate_thread.start()
        streamer_thread.start()

        yield json.dumps({"type": "start"}, ensure_ascii=False) + "\n"

        while True:
            event = await queue.get()
            if event.get("type") == "done":
                break
            if event.get("type") == "token":
                chunks.append(event.get("text", ""))
            yield json.dumps(event, ensure_ascii=False) + "\n"

        generate_thread.join(timeout=1.0)
        streamer_thread.join(timeout=1.0)

        result_text = clean_generated_text("".join(chunks))
        print(f"[Gemma 3] 流式推理结果:\n{result_text}")
        final_result = parse_result_text(result_text, query, req.history)
        yield json.dumps({"type": "final", "data": final_result}, ensure_ascii=False) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8011)
