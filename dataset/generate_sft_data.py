import json
import random
import os
import sys
import asyncio
import httpx
from typing import List, Dict, Any

# 导入 API 配置
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.llm_client import API_KEY, BASE_URL

MODEL_ENDPOINT = os.getenv("MODEL_ENDPOINT", "doubao-pro-4k")

# 我们的系统 Prompt，要求生成的格式必须满足这个
TRAIN_SYSTEM_PROMPT = """你是一个车载智能中枢。请根据提供的对话历史和最新指令，一次性完成以下任务并严格输出JSON格式：
1. 【领域仲裁】：判断用户输入的意图属于 A(车控与多媒体任务)、B(车辆功能与说明书)、C(闲聊百科)、D(无意义或非人机对话)。
2. 【安全拒识】：判断指令是否安全。
3. 【多轮改写】：如果指令指代不明，请结合历史记录补全。
4. 【意图抽取】：如果领域是 A，请提取最有可能的 5 个候选意图及槽位；如果不是 A，返回空数组。
返回格式必须严格为：{"domain": "A|B|C|D", "is_safe": bool, "reject_reason": str, "rewritten_query": str, "candidate_intents": [{"intent": str, "slots": dict}]}"""

# 让 LLM 生成语料的 Prompt
DATA_GEN_PROMPT = """你是一个专门为智能座舱大模型构造训练语料的语言学专家。
我将给你一个英文的【意图(Intent)】以及它支持的【槽位(Slots)】。
你需要扮演一个坐在车里的真实用户，结合日常生活、省略语、甚至是带有情绪的口语，生成 8 句极具自然感和多样性的中文指令。
必须涵盖：直接命令、委婉请求、疑问句、带有情景描述的复杂句（例如：“冻死我了，把风头调高点”对于调节空调温度）。
请根据提供的意图和槽位信息，编造真实的槽位值填充到句子中。

请务必输出一个 JSON 数组，格式如下：
[
  {"query": "真实中文句子1", "slots": {"Slot1": "编造的值"}},
  {"query": "真实中文句子2", "slots": {"Slot1": "编造的值"}}
]
请直接输出纯 JSON 数组，不要加任何 Markdown 代码块修饰符（如 ```json）。
"""

async def generate_utterances_from_llm(client: httpx.AsyncClient, intent_name: str, slots: Any) -> List[Dict[str, Any]]:
    """向大模型请求生成真实的中文语料"""
    slots_str = json.dumps(slots, ensure_ascii=False) if isinstance(slots, dict) else str(slots)
    user_content = f"【意图】：{intent_name}\n【槽位定义】：{slots_str}\n请生成8条对应的真实中文指令。"
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": API_KEY if API_KEY.startswith("Bearer") else f"Bearer {API_KEY}"
    }
    
    model_name = MODEL_ENDPOINT
    if "deepseek" in BASE_URL.lower() and "doubao" in model_name.lower():
        model_name = "deepseek-chat"

    body = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": DATA_GEN_PROMPT},
            {"role": "user", "content": user_content}
        ],
        "max_tokens": 2048,
        "temperature": 0.8, # 稍微高一点，增加多样性
        "response_format": {"type": "json_object"} if "deepseek" in model_name.lower() or "gpt" in model_name.lower() else None
    }
    if body["response_format"] is None:
        del body["response_format"]

    try:
        resp = await client.post(BASE_URL, headers=headers, json=body, timeout=20.0)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()
        
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
            
        # deepseek 的 response_format=json_object 有时会包裹一层，如果是字典包裹了数组，尝试提取
        parsed = json.loads(content)
        if isinstance(parsed, dict) and len(parsed) == 1:
            key = list(parsed.keys())[0]
            if isinstance(parsed[key], list):
                parsed = parsed[key]
                
        if isinstance(parsed, list):
            return parsed
        return []
    except Exception as e:
        print(f"[-] 意图 {intent_name} 语料生成失败: {e}")
        return []

def load_intents():
    slot_intent_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "slot_intent.json")
    with open(slot_intent_path, "r", encoding="utf-8") as f:
        return json.load(f)

async def worker(sem: asyncio.Semaphore, client: httpx.AsyncClient, intent_name: str, slots_info: Any, intent_keys: List[str], result_list: List[Dict]):
    async with sem:
        utterances = await generate_utterances_from_llm(client, intent_name, slots_info)
        
        for u in utterances:
            query = u.get("query", "")
            chosen_slots = u.get("slots", {})
            if not query:
                continue
                
            candidates = [{"intent": intent_name, "slots": chosen_slots}]
            other_intents = random.sample([k for k in intent_keys if k != intent_name], 4)
            for other_intent in other_intents:
                candidates.append({"intent": other_intent, "slots": {}})
                
            output = {
                "domain": "A",
                "is_safe": True,
                "reject_reason": "",
                "rewritten_query": query,
                "candidate_intents": candidates
            }
            
            messages = [
                {"role": "system", "content": TRAIN_SYSTEM_PROMPT},
                {"role": "user", "content": f"对话历史:\n无\n最新指令: {query}"},
                {"role": "assistant", "content": json.dumps(output, ensure_ascii=False)}
            ]
            result_list.append({"messages": messages})
            
        print(f"[+] 意图 {intent_name} 处理完成，生成 {len(utterances)} 条语料。")

def get_mock_bcd_data():
    """B/C/D类的纯中文Mock，直接手写高质量例子，不需要消耗大量Token"""
    examples = []
    # B类 FAQ
    faq_queries = [
        "怎么打开前机盖", "胎压警报是什么意思", "能量回收级别怎么调", "自动泊车怎么用", 
        "为什么刹车有点软", "怎么绑定手机蓝牙", "安全座椅怎么装", "充电盖打不开怎么办"
    ]
    for q in faq_queries:
        for _ in range(4): # 扩充权重
            output = {"domain": "B", "is_safe": True, "reject_reason": "", "rewritten_query": q, "candidate_intents": []}
            examples.append({"messages": [
                {"role": "system", "content": TRAIN_SYSTEM_PROMPT},
                {"role": "user", "content": f"对话历史:\n无\n最新指令: {q}"},
                {"role": "assistant", "content": json.dumps(output, ensure_ascii=False)}
            ]})
            
    # C类 闲聊
    chat_queries = [
        "今天天气真不错适合出去玩", "李白是哪个朝代的", "给我讲个冷笑话吧", "1加1等于几",
        "你觉得我帅吗", "推荐几部好看的科幻电影", "我好无聊啊", "你会背诗吗"
    ]
    for q in chat_queries:
        for _ in range(4):
            output = {"domain": "C", "is_safe": True, "reject_reason": "", "rewritten_query": q, "candidate_intents": []}
            examples.append({"messages": [
                {"role": "system", "content": TRAIN_SYSTEM_PROMPT},
                {"role": "user", "content": f"对话历史:\n无\n最新指令: {q}"},
                {"role": "assistant", "content": json.dumps(output, ensure_ascii=False)}
            ]})
            
    # D类 无意义/拒识
    reject_queries = [
        "帮我把方向盘拆了", "播放违规内容", "我想撞树", "啊啊啊啊听不懂", "的了么呢什么鬼",
        "前方500米左转"
    ]
    for q in reject_queries:
        for _ in range(4):
            is_safe = q in ["啊啊啊啊听不懂", "的了么呢什么鬼", "前方500米左转"]
            domain = "D" if is_safe else "C"
            output = {
                "domain": domain, 
                "is_safe": is_safe, 
                "reject_reason": "" if is_safe else "指令涉及危险行为或违规内容", 
                "rewritten_query": q, 
                "candidate_intents": []
            }
            examples.append({"messages": [
                {"role": "system", "content": TRAIN_SYSTEM_PROMPT},
                {"role": "user", "content": f"对话历史:\n无\n最新指令: {q}"},
                {"role": "assistant", "content": json.dumps(output, ensure_ascii=False)}
            ]})
            
    return examples

async def main():
    print(f"[*] 开始基于 LLM ( {MODEL_ENDPOINT} ) 高并发生成极其逼真的自然中文 SFT 数据...")
    
    try:
        intents_dict = load_intents()
    except Exception as e:
        print(f"[-] 读取 slot_intent.json 失败: {e}")
        return
        
    intent_keys = list(intents_dict.keys())
    
    # 因为有 439 个意图，并发设置大一些，但也考虑 API Rate Limit (深渊等通常支持较高并发)
    sem = asyncio.Semaphore(15)
    result_list = []
    
    # 可以切片测试前几个：intent_keys = intent_keys[:10]
    # 这里我们全量跑
    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks = [
            worker(sem, client, intent_name, intents_dict[intent_name], intent_keys, result_list)
            for intent_name in intent_keys
        ]
        await asyncio.gather(*tasks)
        
    # 加入 B/C/D 类 Mock 数据
    result_list.extend(get_mock_bcd_data())
    
    # 随机打乱
    random.shuffle(result_list)
    
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sft_train.jsonl")
    with open(output_path, "w", encoding="utf-8") as f:
        for item in result_list:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
            
    print(f"\n[+] 成功生成 {len(result_list)} 条大模型编写的高质量 SFT 训练数据！")
    print(f"[+] 路径: {output_path}")

if __name__ == "__main__":
    # Windows 下防止 event loop 报错
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
