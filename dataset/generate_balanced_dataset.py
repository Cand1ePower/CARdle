import json
import random
import os
import sys
import asyncio
import httpx
from typing import List, Dict, Any

# Add root directory to python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.llm_client import API_KEY, BASE_URL

MODEL_ENDPOINT = os.getenv("MODEL_ENDPOINT", "deepseek-v4-flash")

TRAIN_SYSTEM_PROMPT = """你是一个车载智能中枢。请根据提供的对话历史和最新指令，一次性完成以下任务并严格输出JSON格式：
1. 【领域仲裁】：判断用户输入的意图属于 A、B、C 或 D：
   - A (车控与多媒体任务)：用户要求系统执行具体动作、修改设置或播放媒体（例如：“打开空调”、“导航去天安门”、“播放周杰伦的歌”、“温度调高两度”）。
   - B (车辆功能与说明书)：用户咨询或查询车辆的功能、按钮含义、指示灯报警、保养维护或使用说明，但不要求系统执行具体控制动作（例如：“雨刮器堵了怎么清洗”、“发动机黄灯亮了还能开吗”、“怎么绑定车钥匙”、“什么是自适应巡航”、“车辆的各方面数据”）。
   - C (闲聊百科)：与车辆操作和说明无关的通用常识问答、闲聊、简单计算或娱乐（例如：“李白是哪个朝代的”、“讲个笑话”、“今天天气怎么样”）。
   - D (无意义或非人机对话)：误触发、杂音、无意义语气词，或需要安全拒识的非法/危险指令（例如：“嗒嗒嗒”、“在车里抽烟怎么隐藏烟雾警报”）。
2. 【安全拒识】：判断指令是否安全。
3. 【多轮改写】：如果指令指代不明，请结合历史记录补全。
4. 【意图抽取】：如果领域是 A，请提取最有可能的 5 个候选意图及槽位；
返回格式必须严格为：{"domain": "A", "is_safe": bool, "reject_reason": str, "rewritten_query": str, "candidate_intents": [{"intent": str, "slots": dict}]},
如果不是 A,返回格式必须严格为：{"domain": "B|C|D", "is_safe": bool, "reject_reason": str, "rewritten_query": str,,"candidate_intents": []}"""

GENERATE_PROMPTS = {
    "B": """你是一个车载语音交互与智能座舱领域的专家。
我需要你生成用于训练车载小模型的【Domain B (车辆功能与说明书)】类别的中文用户指令。
Domain B 主要包含：用户询问汽车功能如何使用、仪表盘报警灯含义、车辆参数配置、车载设置说明书、充电/保养/蓝牙连接/钥匙绑定等相关的咨询。
注意：这些指令应当是问答咨询，不包含让系统立即执行控制车辆动作的命令（例如“打开空调”是 Domain A，而“空调滤芯怎么换”是 Domain B）。

要求：
1. 生成 50 条极其自然、符合车主日常口语习惯、多样化的中文用户指令。
2. 涵盖各种场景（胎压报警、动能回收、自动泊车、蓝牙、充电指示、OTA升级、紧急刹车等）。
3. 直接输出一个纯 JSON 数组，格式如下，不要加 markdown 标记（如 ```json 等）：
[
  "我的车胎压报警灯亮了该怎么办？",
  "怎么把手机蓝牙连上车机？"
]""",

    "C": """你是一个车载语音交互与智能座舱领域的专家。
我需要你生成用于训练车载小模型的【Domain C (闲聊与百科知识)】类别的中文用户指令。
Domain C 主要包含：通用闲聊（打招呼、心情吐槽）、百科问答（历史、地理、科学、名人介绍）、脑筋急转弯、数学计算、讲笑话、背唐诗等与车控/说明书完全无关的通用对话。

要求：
1. 生成 50 条极其自然、口语化的中文闲聊与百科提问。
2. 包含脑洞大开的问题、简单计算、诗词、常识以及情感倾诉。
3. 直接输出一个纯 JSON 数组，格式如下，不要加 markdown 标记（如 ```json 等）：
[
  "给我讲个关于程序员的冷笑话吧",
  "李白是什么朝代的诗人？"
]""",

    "D": """你是一个车载语音交互与智能座舱领域的专家。
我需要你生成用于训练车载小模型的【Domain D (无意义、噪音、无效触发或不安全拒识)】类别的中文用户指令。
Domain D 主要包含：
1. 无意义的碎碎念、背景杂音、语气词（例如：“啊呃...那个”，“喂喂”，“没什么事”）。
2. 车载场景下需要安全拒识的非法或危险指令（例如：“帮我把方向盘拆了”，“我想开车去撞人”，“我想在车里抽烟怎么隐藏烟雾报警器”）。
3. 纯误触发（例如：“前方500米左转”等导航系统自身的播报声被麦克风误录入）。

要求：
1. 生成 50 条这类指令，包含无意义噪音、误触发以及需要被安全拒识的危险操作。
2. 直接输出一个纯 JSON 数组，格式如下，不要加 markdown 标记（如 ```json 等）：
[
  "呃……就是那个什么来着",
  "我想超速开到两百码怎么关闭限速报警"
]"""
}

async def generate_batch(client: httpx.AsyncClient, domain: str) -> List[str]:
    """Concurrently call LLM to generate a batch of 50 queries for a domain."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": API_KEY if API_KEY.startswith("Bearer") else f"Bearer {API_KEY}"
    }
    
    body = {
        "model": MODEL_ENDPOINT,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": GENERATE_PROMPTS[domain]}
        ],
        "max_tokens": 3000,
        "temperature": 0.9  # High temperature for maximum diversity
    }
    
    try:
        resp = await client.post(BASE_URL, headers=headers, json=body, timeout=40.0)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        
        # Clean potential markdown wrapping
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        
        parsed = json.loads(content)
        if isinstance(parsed, list):
            return [str(item) for item in parsed if item]
        return []
    except Exception as e:
        print(f"[-] Domain {domain} generation batch failed: {e}")
        return []

async def generate_domain_samples(client: httpx.AsyncClient, domain: str, target_count: int, sem: asyncio.Semaphore) -> List[str]:
    """Generate target_count unique samples for a specific domain with concurrency limit."""
    print(f"[*] Starting generation for Domain {domain} (Target: {target_count})...")
    queries = set()
    batches_needed = (target_count // 45) + 1  # Generate a bit more to handle duplicates
    
    async def task_with_sem():
        async with sem:
            return await generate_batch(client, domain)
            
    tasks = [task_with_sem() for _ in range(batches_needed)]
    results = await asyncio.gather(*tasks)
    
    for batch in results:
        for q in batch:
            queries.add(q.strip())
            
    res_list = list(queries)[:target_count]
    print(f"[+] Domain {domain} generated {len(res_list)} samples.")
    return res_list

def is_query_safe(query: str, domain: str) -> bool:
    """Heuristic safety checker for training label construction."""
    if domain == "D":
        # Unsafe prompts to reject
        unsafe_keywords = ["撞", "死", "毒", "违规", "炸", "超速", "拆", "逃票", "违法"]
        return not any(kw in query for kw in unsafe_keywords)
    return True

def build_sft_item(query: str, domain: str) -> Dict[str, Any]:
    """Constructs the standard SFT message structure."""
    is_safe = is_query_safe(query, domain)
    reject_reason = "" if is_safe else "指令涉及危险行为或违规内容"
    
    output = {
        "domain": domain,
        "is_safe": is_safe,
        "reject_reason": reject_reason,
        "rewritten_query": query,
        "candidate_intents": []
    }
    
    return {
        "messages": [
            {"role": "system", "content": TRAIN_SYSTEM_PROMPT},
            {"role": "user", "content": f"对话历史:\n无\n最新指令: {query}"},
            {"role": "assistant", "content": json.dumps(output, ensure_ascii=False)}
        ]
    }

async def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    original_sft_path = os.path.join(base_dir, "sft_train.jsonl")
    balanced_sft_path = os.path.join(base_dir, "sft_train_balanced.jsonl")
    
    # 1. Extract Domain A from original dataset
    domain_a_items = []
    if os.path.exists(original_sft_path):
        print(f"[*] Reading Domain A samples from original SFT file: {original_sft_path}")
        with open(original_sft_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                item = json.loads(line)
                assistant_content = json.loads(item["messages"][2]["content"])
                if assistant_content.get("domain") == "A":
                    domain_a_items.append(item)
        print(f"[+] Loaded {len(domain_a_items)} original Domain A samples.")
    else:
        print(f"[-] Warning: Original SFT file not found at {original_sft_path}")
    
    # Keep all Domain A samples to maintain strong vehicle control capability
    print(f"[*] Keeping all {len(domain_a_items)} original Domain A samples.")
    
    # 2. Concurrently generate B, C, D samples using DeepSeek API with concurrency control
    sem = asyncio.Semaphore(10)  # Limit to 10 concurrent requests to prevent rate limit
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Targets: B: 3000, C: 3000, D: 1500
        b_queries_task = generate_domain_samples(client, "B", 3000, sem)
        c_queries_task = generate_domain_samples(client, "C", 3000, sem)
        d_queries_task = generate_domain_samples(client, "D", 1500, sem)
        
        b_queries, c_queries, d_queries = await asyncio.gather(
            b_queries_task, c_queries_task, d_queries_task
        )
        
    # 3. Build SFT messages for generated queries
    new_items = []
    for q in b_queries:
        new_items.append(build_sft_item(q, "B"))
    for q in c_queries:
        new_items.append(build_sft_item(q, "C"))
    for q in d_queries:
        new_items.append(build_sft_item(q, "D"))
        
    # Combine and Shuffle
    final_items = domain_a_items + new_items
    random.shuffle(final_items)
    
    # 4. Write to balanced SFT file
    with open(balanced_sft_path, "w", encoding="utf-8") as f:
        for item in final_items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
            
    print(f"\n[+] Successfully generated balanced SFT dataset with {len(final_items)} samples!")
    print(f"    - Domain A: {len(domain_a_items)}")
    print(f"    - Domain B: {len(b_queries)}")
    print(f"    - Domain C: {len(c_queries)}")
    print(f"    - Domain D: {len(d_queries)}")
    print(f"    - Saved to: {balanced_sft_path}")

    # 5. Split dataset into train.jsonl and test.jsonl
    # We will modify split_dataset to support balanced dataset splitting
    print("[*] Splitting dataset into train.jsonl and test.jsonl...")
    try:
        from split_dataset import split_dataset
        split_dataset("sft_train_balanced.jsonl", train_ratio=0.85)
    except Exception as e:
        print(f"[-] Splitting failed: {e}")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
