"""
CARdle 端侧大模型 (Gemma 3 1B) SFT 微调脚本
使用 LoRA + 4-bit 量化技术，实现在单张 RTX 3090 上高效微调端侧大模型。
"""

import os
import argparse
import torch
from datasets import load_dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    TrainingArguments,
    BitsAndBytesConfig
)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from trl import SFTTrainer

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

def main():
    parser = argparse.ArgumentParser()
    # 默认指向刚才下载好的本地模型路径
    default_model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pretrained", "gemma-3-1b-it")
    parser.add_argument("--model_name_or_path", type=str, default=default_model_path, help="模型路径或名称")
    parser.add_argument("--data_path", type=str, default="../dataset/sft_train.jsonl", help="SFT 训练数据路径 (JSONL格式)")
    parser.add_argument("--output_dir", type=str, default="./checkpoints", help="模型输出目录")
    parser.add_argument("--epochs", type=int, default=3, help="训练轮数")
    parser.add_argument("--batch_size", type=int, default=4, help="微批次大小")
    args = parser.parse_args()

    print(f"[*] 开始准备 Gemma 3 1B 微调 (LoRA + SFT)...")
    print(f"[*] 基础模型: {args.model_name_or_path}")
    print(f"[*] 数据集: {args.data_path}")

    # 1. 4-bit 量化配置 (极其节省显存，完美适配 RTX 3090)
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16
    )

    # 2. 加载模型与分词器
    print("[*] 正在加载模型与分词器...")
    tokenizer = AutoTokenizer.from_pretrained(args.model_name_or_path, trust_remote_code=True)
    # Gemma 分词器通常需要特定的 pad token
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        args.model_name_or_path,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True
    )
    model = prepare_model_for_kbit_training(model)

    # 3. LoRA 配置
    lora_config = LoraConfig(
        r=16,
        lora_alpha=32,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM"
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # 4. 加载数据集
    print("[*] 正在加载数据集...")
    dataset = load_dataset("json", data_files=args.data_path, split="train")

    def format_prompt(example):
        # 将 messages 格式转换为 Gemma 期待的 prompt
        # 使用 tokenizer.apply_chat_template 自动处理
        return tokenizer.apply_chat_template(example["messages"], tokenize=False, add_generation_prompt=False)

    # 5. 训练参数配置
    training_args = TrainingArguments(
        output_dir=args.output_dir,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=4,
        learning_rate=2e-4,
        logging_steps=10,
        num_train_epochs=args.epochs,
        save_strategy="epoch",
        optim="paged_adamw_32bit",
        fp16=False,
        bf16=True, # 3090 支持 bf16
        max_grad_norm=0.3,
        warmup_ratio=0.03,
        lr_scheduler_type="cosine",
    )

    # 6. 开始训练 (SFT)
    print("[*] 启动 Trainer...")
    trainer = SFTTrainer(
        model=model,
        train_dataset=dataset,
        peft_config=lora_config,
        formatting_func=lambda example: [format_prompt(ex) for ex in [example]], # 简单适配
        max_seq_length=512,
        tokenizer=tokenizer,
        args=training_args,
        packing=False
    )

    trainer.train()
    
    # 7. 保存最终的 LoRA 权重
    final_save_path = os.path.join(args.output_dir, "gemma-3-1b-cardle-lora")
    trainer.model.save_pretrained(final_save_path)
    tokenizer.save_pretrained(final_save_path)
    print(f"[+] 训练结束！LoRA 权重已保存至: {final_save_path}")

if __name__ == "__main__":
    main()
