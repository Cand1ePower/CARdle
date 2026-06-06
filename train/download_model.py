import os
from huggingface_hub import snapshot_download

# 配置环境变量以使用国内镜像加速下载
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

def download_gemma_model():
    model_id = "google/gemma-3-1b-it"
    # 模型将保存在 CARdle/train/pretrained/gemma-3-1b-it 目录下
    save_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pretrained", "gemma-3-1b-it")
    
    print(f"[*] 开始准备下载模型: {model_id}")
    print(f"[*] 目标保存路径: {save_dir}")
    
    try:
        # 只下载模型文件和配置文件，忽略不需要的大文件（如原版 safetensors 如果有 GGUF，但对于微调我们需要 safetensors）
        path = snapshot_download(
            repo_id=model_id,
            local_dir=save_dir,
            local_dir_use_symlinks=False,
            resume_download=True
        )
        print(f"[+] 下载完成! 模型已成功保存至: {path}")
    except Exception as e:
        print(f"[-] 下载失败: {str(e)}")
        print("[!] 提示: 如果提示 401 Unauthorized，请在终端执行 'huggingface-cli login' 并输入你的 Access Token。")

if __name__ == "__main__":
    download_gemma_model()
