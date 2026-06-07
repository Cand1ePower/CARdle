import json
import os
import sys

def evaluate_offline(prediction_file):
    stats = {
        "total": 0,
        "json_success": 0,
        "domain_match": 0,
        "top1_intent_match": 0,
        "top5_intent_match": 0,
        "failed_format": 0
    }
    
    with open(prediction_file, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            data = json.loads(line)
            stats["total"] += 1
            
            ground_truth_str = data.get("label", "{}")
            prediction_str = data.get("predict", "{}")
            
            try:
                ground_truth = json.loads(ground_truth_str)
            except json.JSONDecodeError:
                continue
                
            try:
                prediction = json.loads(prediction_str)
                stats["json_success"] += 1
            except json.JSONDecodeError:
                stats["failed_format"] += 1
                continue
                
            # 评估 Domain 准确率
            gt_domain = ground_truth.get("domain")
            pred_domain = prediction.get("domain")
            if gt_domain == pred_domain:
                stats["domain_match"] += 1
                
            # 评估意图命中率
            if gt_domain == "A":
                gt_intent = ground_truth.get("candidate_intents", [{}])[0].get("intent", "") if ground_truth.get("candidate_intents") else ""
                pred_intents = [c.get("intent") for c in prediction.get("candidate_intents", [])]
                
                if pred_intents and pred_intents[0] == gt_intent:
                    stats["top1_intent_match"] += 1
                if gt_intent in pred_intents:
                    stats["top5_intent_match"] += 1
            else:
                stats["top1_intent_match"] += 1
                stats["top5_intent_match"] += 1

    total = stats["total"]
    if total == 0:
        print("[-] 评估失败，有效样本为 0。")
        return
        
    print("\n" + "="*40)
    print("         大模型离线评估报告 (工业级)")
    print("="*40)
    print(f"总测试样本数:    {total}")
    print(f"JSON解析失败:    {stats['failed_format']}")
    print("-" * 40)
    
    json_rate = stats["json_success"] / total * 100
    domain_rate = stats["domain_match"] / total * 100
    top1_rate = stats["top1_intent_match"] / total * 100
    top5_rate = stats["top5_intent_match"] / total * 100
    
    print(f"JSON 解析成功率: {json_rate:.2f}% ({stats['json_success']}/{total})")
    print(f"领域分类准确率 : {domain_rate:.2f}% ({stats['domain_match']}/{total})")
    print(f"Top-1 意图命中率: {top1_rate:.2f}% ({stats['top1_intent_match']}/{total})")
    print(f"Top-5 意图命中率: {top5_rate:.2f}% ({stats['top5_intent_match']}/{total})")
    print("="*40)

if __name__ == "__main__":
    file_path = r"y:\LLM\CARdle\train\eval_2026-06-06-20-38-55\generated_predictions.jsonl"
    if not os.path.exists(file_path):
        print(f"文件未找到: {file_path}")
    else:
        evaluate_offline(file_path)
