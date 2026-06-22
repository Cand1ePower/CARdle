"""
tools/eval_model_online.py
============================
在线 LLM 模型评估脚本（原根目录 evaluate_model.py）
功能：向 API 发送测试集，计算 JSON 合法率、Domain 准确率、Top-K 意图命中率
用法：python tools/eval_model_online.py [--limit N]

需要 .env 中配置 API_KEY 和 BASE_URL。
"""

import argparse
import os
import json
import sys
import asyncio
import httpx

# 确保能导入根模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
        system_msg = data["messages"][0]["content"]
        user_msg = data["messages"][1]["content"]
        ground_truth_str = data["messages"][2]["content"]

        try:
            ground_truth = json.loads(ground_truth_str)
        except json.JSONDecodeError:
            return  # 原生数据损坏则跳过

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
            "temperature": 0.0,  # 评估时使用 Greedy Search
        }
        if "deepseek" in model_name.lower() or "gpt" in model_name.lower():
            body["response_format"] = {"type": "json_object"}

        stats["total"] += 1

        try:
            resp = await client.post(BASE_URL, headers=headers, json=body, timeout=15.0)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()

            # 清理 Markdown 代码块格式
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]

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

            # 3. 评估意图命中率（仅 domain=A 时有候选意图）
            if gt_domain == "A":
                gt_intent = (ground_truth.get("candidate_intents") or [{}])[0].get("intent", "")
                pred_intents = [c.get("intent") for c in prediction.get("candidate_intents", [])]
                if pred_intents and pred_intents[0] == gt_intent:
                    stats["top1_intent_match"] += 1
                if gt_intent in pred_intents:
                    stats["top5_intent_match"] += 1
            else:
                # B/C/D 类不需要匹配意图，只要 Domain 对了就算命中
                stats["top1_intent_match"] += 1
                stats["top5_intent_match"] += 1

        except Exception:
            stats["failed_requests"] += 1


async def main(limit: int, concurrency: int):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    test_path = os.path.join(base_dir, "dataset", "test.jsonl")

    if not os.path.exists(test_path):
        print(f"[-] 找不到测试集: {test_path}")
        return

    print(f"[*] 开始加载测试集并发送推理请求至 {MODEL_ENDPOINT} ...")
    test_data = []
    with open(test_path, "r", encoding="utf-8") as f:
        for line in f:
            test_data.append(json.loads(line.strip()))

    test_data = test_data[:limit]
    print(f"[*] 选取 {len(test_data)} 条样本进行评估...")

    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient() as client:
        tasks = [evaluate_single(client, d, sem) for d in test_data]
        await asyncio.gather(*tasks)

    # 打印评估报告
    total = stats["total"]
    if total == 0:
        print("[-] 评估失败，有效样本为 0。")
        return

    print("\n" + "=" * 40)
    print("         大模型 SFT 效果评估报告")
    print("=" * 40)
    print(f"总测试样本数:    {total}")
    print(f"网络/API失败:    {stats['failed_requests']}")
    print("-" * 40)

    valid_total = total - stats["failed_requests"]
    if valid_total > 0:
        print(f"JSON 解析成功率: {stats['json_success'] / valid_total * 100:.2f}% ({stats['json_success']}/{valid_total})")
        print(f"领域分类准确率 : {stats['domain_match'] / valid_total * 100:.2f}% ({stats['domain_match']}/{valid_total})")
        print(f"Top-1 意图命中率: {stats['top1_intent_match'] / valid_total * 100:.2f}% ({stats['top1_intent_match']}/{valid_total})")
        print(f"Top-5 意图命中率: {stats['top5_intent_match'] / valid_total * 100:.2f}% ({stats['top5_intent_match']}/{valid_total})")
    print("=" * 40)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="在线 LLM 模型评估")
    parser.add_argument("--limit", type=int, default=100, help="评估样本数量（默认100）")
    parser.add_argument("--concurrency", type=int, default=10, help="并发请求数（默认10）")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main(args.limit, args.concurrency))
