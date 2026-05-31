import os
import json
import random

def split_dataset(input_file="sft_train.jsonl", train_ratio=0.85):
    """
    将生成的全量 JSONL 数据集按照给定的比例打散拆分为训练集和测试集。
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    input_path = os.path.join(base_dir, input_file)
    train_path = os.path.join(base_dir, "train.jsonl")
    test_path = os.path.join(base_dir, "test.jsonl")
    
    if not os.path.exists(input_path):
        print(f"[-] 找不到全量数据集文件: {input_path}")
        return
        
    print(f"[*] 正在读取全量数据集: {input_path}")
    data = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                data.append(json.loads(line))
                
    total_len = len(data)
    print(f"[*] 共读取到 {total_len} 条数据")
    
    # 打乱数据
    random.seed(42) # 固定随机种子，保证可复现
    random.shuffle(data)
    
    train_size = int(total_len * train_ratio)
    train_data = data[:train_size]
    test_data = data[train_size:]
    
    # 写入训练集
    with open(train_path, "w", encoding="utf-8") as f:
        for item in train_data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
            
    # 写入测试集
    with open(test_path, "w", encoding="utf-8") as f:
        for item in test_data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
            
    print(f"[+] 数据拆分完成！")
    print(f"[+] 训练集 ({train_ratio*100:.0f}%): {len(train_data)} 条 -> {train_path}")
    print(f"[+] 测试集 ({(1-train_ratio)*100:.0f}%): {len(test_data)} 条 -> {test_path}")

if __name__ == "__main__":
    split_dataset()
