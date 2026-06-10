# CARdle 智能座舱对话网关

CARdle 是一个面向智能座舱场景的语音对话网关项目，目标是在车载交互中同时支持车控指令、车辆知识问答、闲聊、安全拒识和多轮上下文理解。当前主链路采用 FastAPI、Socket.IO、LangGraph、Redis、SQLite 与本地微调 Gemma 3 1B NLU 服务构建，并通过受限解码约束模型输出结构化 JSON。

项目当前重点是验证“本地端侧 Gemma NLU + 云端仲裁 + 工具执行”的混合架构：Gemma 负责领域判断、安全拒识、多轮改写、候选意图与槽位抽取；网关负责会话隔离、状态机编排、工具调用和前端流式响应。

## 核心能力

- 车控与多媒体意图识别：支持空调、音量、车窗、媒体、导航、电话等座舱任务。
- 领域路由：将用户输入划分为 A 车控任务、B 车辆说明书/FAQ、C 闲聊百科、D 无意义或拒识输入。
- 安全拒识：对辱骂、危险、违法、诱导绕过安全机制等输入输出。
- 多轮上下文继承：Redis 历史保存结构化，支持省略句解析。
- 受限解码：动态构建合法意图枚举，限制 Gemma 只能生成合法 JSON 和合法 intent。
- 端到端评测：提供 HTTP NLU 回归测试和 Socket.IO 多轮 E2E 延迟测试工具。
- 前端演示：提供 React + Vite + Socket.IO 的车机交互界面。

## 服务端口

| 服务 | 默认端口 | 说明 |
| --- | ---: | --- |
| Gateway | `8000` | Socket.IO + FastAPI 主入口 |
| Arbitration | `8008` | 云端/规则仲裁候选意图 |
| Gemma NLU | `8011` | 本地 Gemma 3 1B NLU 服务 |
| Redis | `6379` | 会话历史、防抖锁、状态缓存 |
| Frontend | `5173` | Vite 开发服务器 |

历史上的 Rewrite、Reject、Correlation 等独立微服务仍保留代码，但当前主链路已由 Gemma NLU 的 `rewritten_query/is_safe/domain` 输出接管。

## 目录结构

```text
CARdle/
├── server.py                    # Socket.IO/FastAPI 主网关
├── workflow/                    # LangGraph 状态机
├── function_call/
│   ├── gemma_nlu_server.py      # 本地 Gemma NLU 服务
│   └── chatnlu_infer.py         # legacy ChatNLU 服务
├── client/                      # 仲裁、NLU 客户端、NLG、legacy 微服务
├── mcp_core/                    # 工具分发与车控/地图/媒体执行入口
├── db/                          # Redis/SQLite 数据层
├── dataset/                     # 意图 schema、SFT 数据、测试集
├── tools/                       # 启动器与评测工具
├── client_app/                  # React + Vite 前端
├── train/                       # 本地模型目录，权重文件不应提交
├── deploy/                      # Ubuntu 部署脚本
├── PROJECT_LOG.md               # 项目进展与阶段验收记录
└── SYSTEM_ARCHITECTURE.md       # 架构设计文档
```

## 环境要求

- Windows 10/11 或 Linux。
- Python 3.11+，建议使用项目根目录 `.venv`。
- Node.js 20+，用于前端开发服务器。
- Redis Server。Windows 环境下项目内置 `redis/redis-server.exe`。
- 本地 Gemma 模型目录，默认：

```text
train/Gemma-3-1B-Instruct-CARdle-p
```

模型权重、训练 checkpoint、缓存报告等大文件应保持在 `.gitignore` 中，不应提交到 Git。

## 环境变量

复制 `.env.example` 为 `.env`，并填写实际配置：

```powershell
Copy-Item .env.example .env
```

关键配置：

```env
API_KEY=sk-your-api-key-here
BASE_URL=https://api.deepseek.com
MODEL_ENDPOINT=deepseek-flash

REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_DB=0

ARBITRATION_URL=http://127.0.0.1:8008/intent-server/v1
CHATNLU_INFER_URL=http://127.0.0.1:8011/chatnlu/v1
GEMMA_MODEL_DIR=train/Gemma-3-1B-Instruct-CARdle-p

REQUEST_TIMEOUT=3.0
CHATNLU_TIMEOUT=120.0
```

## 安装依赖

后端：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

前端：

```powershell
cd client_app
npm install
```

## 启动方式

### 一键启动后端服务

Windows 下可直接运行：

```powershell
.\start_dev.bat
```

该脚本会通过 `tools/runner.py` 拉起：

- Redis `6379`
- Arbitration `8008`
- Gemma NLU `8011`
- Gateway `8000`

### 手动启动核心服务

```powershell
.\redis\redis-server.exe --port 6379 --loglevel warning
.\.venv\Scripts\python.exe client\arbitration.py
.\.venv\Scripts\python.exe function_call\gemma_nlu_server.py
.\.venv\Scripts\uvicorn.exe server:combined_app --host 127.0.0.1 --port 8000 --reload
```

### 启动前端

```powershell
cd client_app
npm run dev
```

默认访问：

```text
http://127.0.0.1:5173
```

## Gemma NLU 接口

Gemma NLU 服务默认运行在 `8011`。

### 完整 NLU

```text
POST /chatnlu/v1
```

一次性输出：

```json
{
  "domain": "A",
  "is_safe": true,
  "reject_reason": "",
  "rewritten_query": "打开空调",
  "candidate_intents": [
    {
      "intent": "Open_Air_Condition",
      "slots": {}
    }
  ],
  "function": "Open_Air_Condition",
  "intent": "Open_Air_Condition",
  "slots": {}
}
```

### 两阶段 NLU

```text
POST /chatnlu/route
POST /chatnlu/intent
POST /chatnlu/v2
```

`/chatnlu/route` 只输出：

```json
{
  "domain": "B",
  "is_safe": true,
  "reject_reason": "",
  "rewritten_query": "胎压报警灯亮了怎么办"
}
```

`/chatnlu/v2` 会先执行 route；只有 `domain=A && is_safe=true` 时才继续执行 intent 抽取。

## 受限解码设计

Gemma NLU 通过以下链路约束模型输出：

```text
dataset/slot_intent.json
  -> 动态 IntentEnum
  -> Pydantic JSON Schema
  -> lm-format-enforcer JsonSchemaParser
  -> HuggingFace prefix_allowed_tokens_fn
  -> model.generate token 级约束
```

当前维护三套 schema：

| Schema | 用途 |
| --- | --- |
| `NLUResponseModel` | `/chatnlu/v1` 完整 NLU 输出 |
| `NLURouteResponseModel` | `/chatnlu/route` 领域、安全、改写 |
| `NLUIntentResponseModel` | `/chatnlu/intent` 候选意图与槽位 |

这样可以避免模型生成不存在的 intent，也能减少 route 阶段不必要的字段生成。

## 数据结构

### NLU 响应核心字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `domain` | `A/B/C/D` | 领域分类 |
| `is_safe` | `bool` | 是否安全 |
| `reject_reason` | `str` | 拒识原因 |
| `rewritten_query` | `str` | 多轮改写后的完整指令 |
| `candidate_intents` | `list` | Top-K 候选意图 |
| `function` | `str` | 兼容旧主链路的 Top-1 函数名 |
| `intent` | `str` | 兼容旧主链路的 Top-1 意图名 |
| `slots` | `dict` | Top-1 槽位 |

### Redis 历史 metadata

assistant 轮会写入结构化 metadata：

```json
{
  "intent": "Set_Air_Condition_Temperature",
  "function": "Set_Air_Condition_Temperature",
  "slots": {
    "Number": "22"
  },
  "domain": "A",
  "is_safe": true,
  "rewritten_query": "把空调调到22度",
  "candidate_intents": [
    {
      "intent": "Set_Air_Condition_Temperature",
      "slots": {
        "Number": "22"
      }
    }
  ]
}
```

该结构用于下一轮继承。

## 测试与评估

### 编译检查

```powershell
.\.venv\Scripts\python.exe -m py_compile function_call\gemma_nlu_server.py tools\eval_gemma_nlu.py tools\eval_multiturn_e2e.py
```

### Gemma NLU smoke 回归

```powershell
.\.venv\Scripts\python.exe tools\eval_gemma_nlu.py --start-server --url http://127.0.0.1:18129/chatnlu/v1 --report scratch\gemma_nlu_eval_smoke_v1.json --timeout 360 --ready-timeout 240
```

### 两阶段 route 测试

```powershell
.\.venv\Scripts\python.exe tools\eval_gemma_nlu.py --start-server --url http://127.0.0.1:18126/chatnlu/route --report scratch\gemma_route_eval_smoke.json --timeout 300 --ready-timeout 240 --ignore-intent
```

### 两阶段 v2 测试

```powershell
.\.venv\Scripts\python.exe tools\eval_gemma_nlu.py --start-server --url http://127.0.0.1:18127/chatnlu/v2 --report scratch\gemma_nlu_eval_smoke_v2.json --timeout 360 --ready-timeout 240
```

### Socket.IO 多轮 E2E 测试

```powershell
.\.venv\Scripts\python.exe tools\eval_multiturn_e2e.py --report scratch\e2e_multiturn_latency_report.json
```

该测试会验证：

- 网关 Socket.IO 请求链路。
- Redis 结构化历史写入。
- 多轮省略句继承。
- intent 与 slots 是否真实可执行。
- `first_frame_ms`、`total_ms`、`history_write_ms` 延迟指标。

## 当前测试基线

截至 `2026-06-08`，CPU 本地 Gemma 环境下的阶段性结果：

| 测试项 | 结果 |
| --- | --- |
| `/chatnlu/route` smoke | 7/7 通过 |
| `/chatnlu/v2` smoke | 7/7 通过，Top-1/Top-5 全中 |
| `/chatnlu/v2` dataset 抽样 | 2/2 通过 |
| `/chatnlu/v1` 兼容 smoke | 7/7 通过 |
| Socket.IO 两轮 E2E | 2/2 通过 |

本地使用CPU运行gemma，延迟较高，若使用GPU或NPU加速可大幅提速

| 链路 | warm 平均延迟 |
| --- | ---: |
| `/chatnlu/route` | 约 `21.8s` |
| `/chatnlu/v2` | 约 `30.9s` |
| `/chatnlu/v1` | 约 `42.5s` |
| `/chatnlu/stream` | 约 `14.3s` |

## 后续计划

1. 将主网关灰度切换到v2并结合stream
2. 接入流式字段级早路由，让 B/C/D 类不等待完整候选意图生成。
3. 优化 route prompt，减少输出 token，继续压低首帧延迟。
4. 收敛云端 Arbitration，只在低置信或复杂多轮场景调用。
5. 接入车辆说明书 RAG，完善 B 类车辆知识问答。
6. 为 Android APK 和云端部署分别制定量化、资源占用和并发隔离方案。
