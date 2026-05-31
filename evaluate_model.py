import os
import json
import sys
import asyncio
import httpx

# 引入配置
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from utils.llm_client import API_KEY, BASE_URL

MODEL_ENDPOINT = os.getenv("MODEL_ENDPOINT", "doubao-pro-4k")

# 评估指标统计
stats = {
    "total": 0,
    "json_success": 0,
    "domain_match": 0,
    "top1_intent_match": 0,
    "top5_intent_match": 0,
    "failed_requests": 0
}

async def evaluate_single(client: httpx.AsyncClient, data: dict, sem: asyncio.Semaphore):
    """请求模型并进行单条数据的准确率对比"""
    async with sem:
        # data["messages"] 结构: [system, user, assistant]
        system_msg = data["messages"][0]["content"]
        user_msg = data["messages"][1]["content"]
        ground_truth_str = data["messages"][2]["content"]
        
        try:
            ground_truth = json.loads(ground_truth_str)
        except json.JSONDecodeError:
            return # 原生数据损坏则跳过
            
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
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg}
            ],
            "max_tokens": 1024,
            "temperature": 0.0, # 评估时使用 Greedy Search
            "response_format": {"type": "json_object"} if "deepseek" in model_name.lower() or "gpt" in model_name.lower() else None
        }
        if body["response_format"] is None:
            del body["response_format"]

        stats["total"] += 1
        
        try:
            resp = await client.post(BASE_URL, headers=headers, json=body, timeout=15.0)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
            
            # 清理格式
            if content.startswith("```json"): content = content[7:]
            if content.startswith("```"): content = content[3:]
            if content.endswith("```"): content = content[:-3]
            
            # 1. 评估 JSON 合法率
            try:
                prediction = json.loads(content)
                stats["json_success"] += 1
            except json.JSONDecodeError:
                print(f"[x] JSON 解析失败:\n输入: {user_msg}\n输出: {content[:100]}...")
                return
                
            # 2. 评估 Domain 准确率
            gt_domain = ground_truth.get("domain")
            pred_domain = prediction.get("domain")
            if gt_domain == pred_domain:
                stats["domain_match"] += 1
                
            # 3. 评估意图命中率 (仅当 GT domain 为 A 时才有候选意图)
            if gt_domain == "A":
                gt_intent = ground_truth["candidate_intents"][0]["intent"] if ground_truth.get("candidate_intents") else ""
                pred_intents = [c.get("intent") for c in prediction.get("candidate_intents", [])]
                
                if pred_intents and pred_intents[0] == gt_intent:
                    stats["top1_intent_match"] += 1
                if gt_intent in pred_intents:
                    stats["top5_intent_match"] += 1
            else:
                # B/C/D 类不需要匹配意图，只要 Domain 对了就算命中
                stats["top1_intent_match"] += 1
                stats["top5_intent_match"] += 1

        except Exception as e:
            stats["failed_requests"] += 1
            # print(f"[-] 请求失败: {e}")

async def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    test_path = os.path.join(base_dir, "dataset", "test.jsonl")
    
    if not os.path.exists(test_path):
        print(f"[-] 找不到测试集: {test_path}")
        return
        
    print(f"[*] 开始加载测试集并发送推理请求至 {MODEL_ENDPOINT} ...")
    test_data = []
    with open(test_path, "r", encoding="utf-8") as f:
        for line in f:
            test_data.append(json.loads(line.strip()))
            
    # 取前 100 条进行快速评估（可修改为全量）
    test_data = test_data[:100]
    print(f"[*] 选取 {len(test_data)} 条样本进行评估。这可能需要一两分钟...")
    
    sem = asyncio.Semaphore(10)
    async with httpx.AsyncClient() as client:
        tasks = [evaluate_single(client, d, sem) for d in test_data]
        await asyncio.gather(*tasks)
        
    # 打印评估报告
    total = stats["total"]
    if total == 0:
        print("[-] 评估失败，有效样本为 0。")
        return
        
    print("\n" + "="*40)
    print("         大模型 SFT 效果评估报告")
    print("="*40)
    print(f"总测试样本数:    {total}")
    print(f"网络/API失败:    {stats['failed_requests']}")
    print("-" * 40)
    
    valid_total = total - stats["failed_requests"]
    if valid_total > 0:
        json_rate = stats["json_success"] / valid_total * 100
        domain_rate = stats["domain_match"] / valid_total * 100
        top1_rate = stats["top1_intent_match"] / valid_total * 100
        top5_rate = stats["top5_intent_match"] / valid_total * 100
        
        print(f"JSON 解析成功率: {json_rate:.2f}% ({stats['json_success']}/{valid_total})")
        print(f"领域分类准确率 : {domain_rate:.2f}% ({stats['domain_match']}/{valid_total})")
        print(f"Top-1 意图命中率: {top1_rate:.2f}% ({stats['top1_intent_match']}/{valid_total})")
        print(f"Top-5 意图命中率: {top5_rate:.2f}% ({stats['top5_intent_match']}/{valid_total})")
    print("="*40)

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
