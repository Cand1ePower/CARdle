import json
import random
import os

# 定义基础系统 Prompt
SYSTEM_PROMPT = """你是一个车载中枢。请根据提供的对话历史和最新指令，一次性完成以下任务并严格输出JSON格式：
1. 【安全拒识】：判断用户指令是否涉及危险操作。
2. 【多轮改写】：如果指令指代不明，请结合历史记录补全。
3. 【意图抽取】：如果指令安全，提取具体的车控意图和槽位。
返回格式必须为：{"is_safe": bool, "reject_reason": str, "rewritten_query": str, "intent": str, "slots": dict}"""

# 模拟一些生成数据的规则
INTENT_TEMPLATES = {
    "Vehicle_Hardware_Control": [
        ("把{Position}车窗打开", {"Position": ["主驾", "副驾", "左后", "右后"]}),
        ("车窗降一半", {"Position": ["全部"], "Ratio": ["一半"]})
    ],
    "Navigation_Location_Query": [
        ("导航去{POI}", {"POI": ["体育中心", "天安门", "最近的加油站"]}),
        ("去{City}的{POI}", {"City": ["北京", "上海"], "POI": ["火车站", "机场"]})
    ],
    "Request_Specific_Song": [
        ("播放{Singer}的{Song}", {"Singer": ["周杰伦", "林俊杰"], "Song": ["七里香", "江南"]}),
        ("我想听{Song}", {"Song": ["三只小猪", "挪威的森林"]})
    ]
}

REJECT_EXAMPLES = [
    "帮我把方向盘拆了",
    "给我播放被封禁的反动歌曲",
    "开车撞向人群"
]

def generate_dataset(num_samples=1000):
    dataset = []
    
    for _ in range(num_samples):
        # 10% 的数据是拒识数据
        if random.random() < 0.1:
            query = random.choice(REJECT_EXAMPLES)
            output = {
                "is_safe": False,
                "reject_reason": "指令涉及危险行为或违规内容",
                "rewritten_query": query,
                "intent": "",
                "slots": {}
            }
        else:
            # 正常意图数据
            intent = random.choice(list(INTENT_TEMPLATES.keys()))
            template_info = random.choice(INTENT_TEMPLATES[intent])
            template_str, slot_options = template_info
            
            chosen_slots = {}
            query = template_str
            for slot_name, options in slot_options.items():
                if "{" + slot_name + "}" in query:
                    val = random.choice(options)
                    query = query.replace("{" + slot_name + "}", val)
                    chosen_slots[slot_name] = val
                    
            output = {
                "is_safe": True,
                "reject_reason": "",
                "rewritten_query": query,
                "intent": intent,
                "slots": chosen_slots
            }
            
        # 组装为 HuggingFace SFT 支持的 messages 格式
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"对话历史:\n无\n最新指令: {query}"},
            {"role": "assistant", "content": json.dumps(output, ensure_ascii=False)}
        ]
        
        dataset.append({"messages": messages})
        
    return dataset

if __name__ == "__main__":
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sft_train.jsonl")
    data = generate_dataset(2000)
    
    with open(output_path, "w", encoding="utf-8") as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
            
    print(f"[+] 成功生成 {len(data)} 条大模型 SFT 训练数据！")
    print(f"[+] 保存路径: {output_path}")
    print(f"[+] 格式示例: {json.dumps(data[0], ensure_ascii=False, indent=2)}")
