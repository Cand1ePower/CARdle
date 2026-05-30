import os
import httpx
from dotenv import load_dotenv

# 加载 .env 环境变量
current_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(os.path.dirname(current_dir), ".env")
if os.path.exists(env_path):
    load_dotenv(dotenv_path=env_path)

API_KEY = os.getenv("API_KEY", "")
BASE_URL = os.getenv("BASE_URL", "https://ark.cn-beijing.volces.com/api/v3/chat/completions")

# 标准化 BASE_URL，兼容 DeepSeek/OpenAI 等厂商填入裸域名的情景，自动补齐标准 OpenAI 路由
if BASE_URL:
    BASE_URL_LOWER = BASE_URL.lower()
    if not BASE_URL_LOWER.endswith("/chat/completions") and not BASE_URL_LOWER.endswith("/chat/completions/"):
        if "deepseek" in BASE_URL_LOWER:
            BASE_URL = BASE_URL.rstrip("/") + "/v1/chat/completions"
        elif "api.openai.com" in BASE_URL_LOWER:
            BASE_URL = BASE_URL.rstrip("/") + "/v1/chat/completions"
        else:
            BASE_URL = BASE_URL.rstrip("/") + "/v1/chat/completions"

# 判断是否是 Mock 模式（如果 API_KEY 包含 xxxx 或是空的，则为 Mock 模式）
IS_MOCK = not API_KEY or "xxxx" in API_KEY

try:
    from langfuse import observe, get_client
except ImportError:
    # 如果没安装，提供一个哑装饰器
    def observe(*args, **kwargs):
        def decorator(func):
            return func
        return decorator
    def get_client(): return None

async def call_llm_async(messages: list, stream: bool = False, temperature: float = 0.3) -> str:
    """
    通用异步 LLM 调用函数，具备 Mock 自动降级与 OpenAI 协议兼容性。
    """
    from utils.logger import session

    @observe(as_type="generation")
    async def _inner_call(messages: list, stream: bool, temperature: float, langfuse_trace_id: str = None):
        client = get_client()
        if client:
            client.update_current_generation(
                model=os.getenv("MODEL_ENDPOINT", "doubao-pro-4k"),
            )

        if IS_MOCK:
            user_content = messages[-1]["content"] if messages else ""
            system_content = messages[0]["content"] if messages else ""
            
            # 1. 意图仲裁的 Mock
            if "意图识别" in system_content or "A、B、C、D" in system_content:
                task_keywords = ["空调", "导航", "播放", "打开", "关闭", "去", "地图", "温度", "音量", "一点"]
                is_task = any(word in user_content for word in task_keywords)
                return "A" if is_task else "C"
                
            # 2. 多轮改写的 Mock
            if "句子改写" in system_content or "指代消解" in system_content:
                if "调高一点" in user_content:
                    return "帮我把空调温度调高一点"
                return user_content
                
            # 3. 关联性判定的 Mock
            if "相关性" in system_content or "相关" in system_content:
                context_words = ["一点", "这个", "那个", "再", "它", "不要了", "换一首", "继续"]
                is_correlated = any(word in user_content for word in context_words)
                return "是" if is_correlated else "否"
                
            # 4. 闲聊/NLG 的 Mock
            if "AI智能座舱助手" in system_content:
                if "谁" in user_content:
                    return "我是 CARdle 语音智能控制网联中心，是您的全能特斯拉风车机小管家。"
                return "您说得太有趣了！很高兴为您服务。"
                
            return "模拟的 LLM 答复"

        # 真实 API 调用
        headers = {
            "Authorization": f"{API_KEY}" if API_KEY.startswith("Bearer") else f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        
        model_name = os.getenv("MODEL_ENDPOINT", "doubao-pro-4k")
        if "deepseek" in BASE_URL.lower() and "doubao" in model_name.lower():
            model_name = "deepseek-chat"
        
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "stream": stream
        }
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(BASE_URL, json=payload, headers=headers)
            if resp.status_code == 200:
                result = resp.json()
                return result["choices"][0]["message"]["content"].strip()
            else:
                raise Exception(f"LLM API Error {resp.status_code}: {resp.text}")

    # 调用内层函数并显式传递 trace_id，Langfuse v4 会自动提取 langfuse_trace_id 作为父 Trace 标识
    trace_id = session.trace_id if session.trace_id and session.trace_id != "unknown" else None
    return await _inner_call(messages, stream, temperature, langfuse_trace_id=trace_id)
