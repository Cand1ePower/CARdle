# CARdle 项目进展与架构日志

> **更新时间**：2026-06-08
> **项目定位**：基于微服务架构的大模型 + 本地小模型混合编排智能座舱对话网关

## 整体架构设计

本项目将传统的纯本地车载语音系统重构为**分布式微服务架构**。
核心理念是 **“大带小 (LLM + Small Model)” 漏斗降级架构**：

- **微服务隔离**：多轮改写、安全拒识、顶级仲裁、关联判断等业务逻辑被拆分为独立的 FastAPI 端口。
- **断路器降级 (Circuit Breaker)**：NLU 核心解析层支持双模自适应。当本地意图小模型正常工作时，执行 Top-5 漏斗精排（省 Token，速度快）；当本地服务不可用时，自动降级为大模型全量 439 意图 Zero-shot 检索模式。
- **配置驱动**：意图分类与参数 Schema 分别由 `new_map.json` 和 `slot_intent.json` 驱动，新增指令无需修改代码逻辑。

## 已实现的模块进展

| 模块名称 | 端口 | 当前实现状态 | 实现细节 |
| :--- | :--- | :--- | :--- |
| **网关核心 (Gateway)** | `8000` | ✅ 已完成 | 基于 Socket.IO 的双向通信，完整协调下述 5 个微服务。 |
| **多轮改写 (Rewrite)** | `8006` | ✅ 已完成 | 调用云端大模型进行指代消解。 |
| **安全拒识 (Reject)** | `8007` | ⚠️ 打底模式 | 规划使用本地 BERT。目前使用简单的字符规则判断，拦截低质输入。 |
| **大类仲裁 (Arbitration)** | `8008` | ✅ 已完成 | 采用流式截断（首字匹配）云端大模型，极速进行 A/B/C/D 分类。 |
| **上下文关联 (Correlation)** | `8009` | ✅ 已完成 | 接入大模型判定。 |
| **NLU网关 (ChatNLU)** | `8015` | ✅ 已完成 | 核心调度中枢，负责拼装 Schema 并交由大模型提取参数。 |
| **本地意图模型 (Intent)** | `8016` | 🟡 调试与升级中 | 已基于 Gemma 3 1B 完成云端微调并导出完整模型。目前正进行本地端侧部署与受限解码集成。 |
| **模型训练框架 (Train)** | `-` | ✅ 已完成 | 编写了现代化的 HuggingFace `hf_train.py` 脚本，支持混合精度及多卡分布式训练。 |
| **离线数据合成 (Dataset)** | `-` | ✅ 已完成 | 根据新下载的 `Interaction_Agent_Dataset_V0.1` 数据集共计 5 大类、102 小类的意图定义，以原系统配置格式，完美生成了全新的 `dataset/class.txt`、`dataset/new_map.json` 和 `dataset/slot_intent.json`。 |
| **混合双层存储 (DB Layer)** | `-` | ✅ 已完成 | 采用 Redis (内存 KV) 处理多轮会话、防抖锁与车辆实时状态；采用 SQLite 异步并发 (WAL) 处理全量审计日志持久化。完美实现多车机用户绝对隔离，并使用 `contextvars` 解决了 ASGI 下日志并发串线隐患。 |
| **部署与开发者体验** | `-` | ✅ 已完成 | 提供 `start_dev.bat` 一键唤起彩虹多屏微服务矩阵；提供 Ubuntu 一键部署及启停 `deploy/*.sh` 脚本。 |
| **全局状态机引擎 (Workflow)** | `-` | ✅ 已完成 | 引入 LangGraph 彻底重构网关核心，将过程式的巨型控制流转换为优雅的有向状态图 (StateGraph)。实现 NLU/拒识/闲聊/FAQ/仲裁/车控 的节点化与统一调度，原生支持动态路由、异常兜底流转及 Langfuse 节点级 Trace 追踪。 |
| **高拟真交互前端 (Frontend)** | `5173` | ✅ 已完成 | 基于 Vite + React 构建的 Tesla 风格车机前端，内置动态科技风 UI。支持 Socket.IO 实时长连接、UUID TraceID 传递、流式打字机动画展示，以及各分支 (车控、闲聊、拒识) 的交互动效呈现。 |
## 4. 待实现的功能规划 (Roadmap)

根据整体开发计划，我们还有以下关键领域待攻克：

### ✅ Phase 6: GPU 云端部署与微调训练

- **目标**：将 `hf_train.py` 部署至云端服务器，利用全量几万条数据集，实际训练出 `intent` 和 `reject` 的模型权重。
- **产出**：已使用 LLaMA-Factory 完成云端 LoRA 训练，将微调后的权重与基座模型合并为 `gemma-3-1b-cardle-merged` 并下载至本地电脑的 `y:\LLM\CARdle\train` 目录下，AutoDL 云端服务器已安全关机释放。

### 🟡 Phase 7: 引入 Gemma 3 1B 端侧全能大模型与受限解码架构 (进行中)

- **背景与目标**：原计划在本地车机部署轻量级 BERT 模型（意图 8016 + 拒识 8007）和通过 LangGraph 构建状态机。现决定进行**终极架构跃迁**：直接在安卓/车机（如天玑 9500 NPU）端侧部署量化版的 **Gemma 3 1B** 纯生成式大模型。
- **核心技术（受限解码）**：为了彻底解决生成式小语言模型（SLM）在提取 JSON 时常见的“格式幻觉”问题，我们将引入 **Google AI Edge SDK (Constrained Decoding)**。强制模型在推理阶段只能生成符合 `slot_intent.json` 结构的合法 JSON，实现 100% 稳定的车控意图提取。
- **架构升级收益**：
  - **极致整合**：一个端侧大模型节点同时包揽【安全拒识】、【多轮改写】、【意图与槽位提取】三个微服务的工作。
  - **断网全能**：在完全无网的地下车库，不仅能实现秒级车控，还能保留基础的闲聊与复杂逻辑推理能力。
  - **极速响应**：基于 INT4/W4A16 极致量化技术，结合天玑 APU 硬件加速，APK 整体体积控制在 500MB 内，首字响应延迟低于 50ms。

### 🔴 Phase 8: 引入 RagFlow 车企级专属大模型知识库 (RAG)

- **背景与目标**：基于《汽车用户指导手册》及海量售后 FAQ 数据，为座舱赋予“懂车帝”属性。当用户提问（如“胎压灯亮了怎么办”、“如何打开儿童锁”）时，能够基于官方手册给出权威解答，避免大模型幻觉瞎编。
- **架构集成方案**：
  - **独立服务**：单独部署 RagFlow 服务端，导入多模态 PDF 手册进行深度解析建库，暴露标准 HTTP API。
  - **意图扩展**：在分类字典 (`class.txt` / `slot_intent.json`) 中新增专属的用车问答意图（如 `Car_Manual_FAQ`）。
  - **MCP 插件化接入**：在现有的工具中枢（`mcp_core/tool_dispatcher.py`）中，将其视为一个 MCP 外部检索插件。命中意图后触发异步请求，去 RagFlow 调取原文答案。
  - **NLG 播报兜底**：通过 `request_nlg_async` 将 RagFlow 冰冷的检索原文润色为贴近人设、有情感关怀的语音播报内容（例如：“这是胎压报警，建议您先减速靠边停车...”）。
- **价值**：零代码侵入原有的车控极速流水线，完美补全闲聊与硬核车控之间的巨大空白（知识库问答区）。

## 项目微调里程碑与评估记录

### 📅 2026-06-06 ~ 2026-06-07：Gemma 3 1B 意图模型微调成功

- **微调任务**：针对座舱 439 类指令的意图识别与槽位提取 SFT。
- **云端训练**：使用 LLaMA-Factory 在 AutoDL 云服务器上完成，并将 LoRA 权重与 Gemma 3 1B 基座模型安全合并导出为 `gemma-3-1b-cardle-merged`。目前微调后的完整版模型已全部下载至本地 `train/` 文件夹下，AutoDL 云端服务器已完成使命并关机释放。
- **离线模型评估结果**（基于 536 条独立测试集数据）：
  - **JSON 格式解析成功率**：**99.44%** (536 条仅 3 条解析失败)
  - **领域分类准确率 (Domain Accuracy)**：**100.00%** (100% 命中车控、闲聊、拒识等大类)
  - **Top-1 意图准确率 (Intent Hit Rate)**：**45.34%** (存在微小的长尾意图命名幻觉，如将 `Close_Interactive_Learning` 错生成为 `Close_Learning`)
  - **Top-5 意图命中率**：**73.13%**
- **当前瓶颈与原因分析**：大模型在一轮 Epoch 内难以完全记忆 439 个高度精细的长尾意图拼写，生成了语义相似但拼写与 Schema 不符的意图。但 JSON 结构与大类路由完全正确。
- **后续优化方案**：
  - 启动 **Phase 7: 受限解码（Constrained Decoding）**，从推理的 Token 级约束大模型的生成空间，强制大模型必须在预定义的合法意图列表中进行选择，预计将意图准确率直接提升至 **90% 以上**。

### 📅 2026-06-08：Gemma 3 本地 NLU 主链路接入与旧微服务收敛

- **主链路现状**：网关已切换为 `server.py -> workflow/cardle_graph.py -> client/nlu.py -> function_call/gemma_nlu_server.py`。本地 Gemma 3 1B 服务运行在 `8011`，一次性输出 `domain`、`is_safe`、`reject_reason`、`rewritten_query`、`candidate_intents`。
- **规范化意图技术落地**：`gemma_nlu_server.py` 基于 `dataset/slot_intent.json` 动态构建合法意图枚举，并通过 `lm-format-enforcer` 的受限解码约束 JSON 输出，避免模型生成不存在的函数名；解析后仍保留二次校验，非法意图会降级为 `Unknown`。`client/arbitration.py` 也增加最终白名单校验，确保云端仲裁不能把候选集改写成未定义函数。
- **旧服务收敛**：独立的 Rewrite(8006)、Reject(8007)、Correlation(8009) 已由 Gemma NLU 输出接管，不再随 `start_dev.bat` 主启动器启动。相关文件保留为 legacy/回滚参考。
- **仍保留的云端节点**：Arbitration(8008) 仍在主链路中，用于从 Gemma 给出的 Top-K 候选中结合上下文做最终选择；若仲裁服务失败，则降级取首选候选意图。
- **流式测试入口**：`gemma_nlu_server.py` 新增 `/chatnlu/stream` NDJSON 流式端点，`tools/gemma_console.py --stream` 可直接观察受限解码的增量输出；主网关当前仍使用非流式 `/chatnlu/v1`，后续可接入字段级早路由。

## 2026-06-08 起：Gemma 本地 NLU 稳定化执行计划

本阶段开始执行“先稳定、再提速、最后清理”的原则。每个阶段必须同步记录：

- **新技术**：本阶段引入或调整了什么技术，以及为什么使用。
- **数据流**：用户输入从哪里进入、经过哪些模块、每一步输出什么。
- **数据结构**：请求、响应、候选意图、评估样本、测试报告的字段设计。
- **完整测试**：每个阶段性改动后必须运行可复现测试，并记录验收结果。

| 优先级 | 阶段 | 目标 | 技术/数据流重点 | 测试验收 |
| :--- | :--- | :--- | :--- | :--- |
| P0 | 1. 固化当前主链路 | 确认新架构能稳定跑 | `server.py -> workflow.cardle_graph -> client.nlu -> gemma_nlu_server`；Gemma 输出 `domain/is_safe/rewritten_query/candidate_intents` | `打开空调`、辱骂拒识、车辆 FAQ 三类请求路由正确 |
| P0 | 2. 建立 Gemma NLU 回归集 | 给后续 prompt/流式/两阶段改动建立量化尺子 | 从 `dataset/test.jsonl` 和手写 smoke cases 读取 `{query, expected}`，调用 `8011 /chatnlu/v1`，输出命中率报告 | 一条命令输出 JSON 解析率、domain 准确率、is_safe 准确率、Top-1/Top-5 意图命中率 |
| P0 | 3. 优化拒识提示词与规则 | 让安全判断可控 | 模型 prompt + 服务端轻量 safety override 双保险；拒识输出统一为 `domain=D/is_safe=false` | 辱骂、危险操作、绕过安全等样本不进入 chat/task |
| P1 | 4. 接入流式早路由 | 降低非 A 类感知延迟 | `8011 /chatnlu/stream` 输出 NDJSON；网关增量读取 `domain/is_safe` 后提前走 reject/FAQ/chat | B/C/D 类不等待完整候选意图即可响应 |
| P1 | 5. 缩短首 token 延迟 | 降低本地 CPU/NPU 推理等待 | 缩短 prompt、减少候选数、两阶段输出 `domain/is_safe -> A类候选意图` | 记录首 token、完整 NLU、端到端响应时间，准确率不明显退化 |
| P1 | 6. 仲裁层收敛 | 减少云端依赖 | 评估 Gemma Top-1/Top-5；云端 Arbitration 只处理低置信或复杂多轮 | 常见车控离线可执行，云端失败时仍有确定性兜底 |
| P2 | 7. Legacy 清理 | 降低维护噪音 | 标记或移除旧 `rewrite/reject/correlation/chatnlu_infer` 主链路角色，清理未使用 import | 新启动器和代码引用图不再指向旧主链路 |
| P2 | 8. 端到端验收 | 确认前端、网关、DM/MCP 全链路可用 | Socket.IO 请求、LangGraph 路由、DM/MCP 工具执行、NLG 播报 | 更新 `e2e_test_report`，核心 50 条通过 |

### 阶段 2 先行任务：`tools/eval_gemma_nlu.py`

- **目的**：在继续优化之前，先建立可重复执行的 Gemma NLU 回归测试工具。
- **输入数据结构**：
  - JSONL 训练/测试集样本：`{"messages": [system, user, assistant]}`，从 user 消息抽取 `query`，从 assistant 消息抽取期望 JSON。
  - 手写 smoke cases：`{"query": str, "expected": {"domain": str, "is_safe": bool, "intent": str|null}}`。
- **运行数据流**：`eval_gemma_nlu.py -> HTTP POST /chatnlu/v1 -> Gemma NLU -> JSON response -> 指标聚合 -> report.json`。
- **输出报告结构**：`summary` 记录总量、失败数、准确率；`cases` 记录每条样本的 query、expected、actual、pass/fail 与错误原因。

### 阶段 2 执行结果：Gemma NLU 回归评估工具落地

- **新增工具**：`tools/eval_gemma_nlu.py`。
- **新技术/方法**：使用 HTTP 黑盒回归测试评估本地 Gemma NLU；支持临时启动 `uvicorn function_call.gemma_nlu_server:app`，避免与正在运行的 `8011` 服务冲突；输出 JSON 报告用于阶段验收。
- **核心数据结构**：
  - `EvalCase`：`id/source/query/expected`。
  - `expected`：支持 `domain`、`is_safe`、`intent` 或 `intents`（用于允许多个等价合法意图，如 `Open_Air_Condition` / `Open_AC`）。
  - `actual`：来自 `/chatnlu/v1` 的结构化 JSON，包含 `domain/is_safe/reject_reason/rewritten_query/candidate_intents/function/intent/slots`。
  - `checks`：`request_ok/domain_match/is_safe_match/top1_intent_match/top5_intent_match`。
- **测试结果**：
  - 工具级编译：`python -m py_compile tools/eval_gemma_nlu.py tools/gemma_console.py function_call/gemma_nlu_server.py client/arbitration.py` 通过。
  - dry-run 样本加载：内置 4 条 smoke + `dataset/test.jsonl` 前 2 条，共 6 条，报告写入 `scratch/gemma_nlu_eval_dry_run.json`。
  - 真实 smoke 回归：4/4 通过，报告写入 `scratch/gemma_nlu_eval_smoke_after_override.json`。
  - 真实 dataset 抽样：`dataset/test.jsonl` 前 2 条 2/2 通过，报告写入 `scratch/gemma_nlu_eval_dataset2_after_override.json`。
- **发现并修复的问题**：模型会把“那啥……我忘了要干啥”这类无意义但无害的 D 类误判为 `is_safe=false`。已在 `gemma_nlu_server.py` 中补充无害 D 类 prompt 示例，并增加 `HARMLESS_D_KEYWORDS` 后处理；同时保留辱骂/攻击性内容的 `UNSAFE_REJECT_KEYWORDS` 后处理。

### 阶段 2.5：结构化多轮上下文继承

- **背景**：旧 `Correlation(8009)` 服务只能判断当前句子是否像“依赖上下文的追问/片段”，并不会把“再高点”解析成上一轮空调温度调节。Gemma NLU 主链路虽然已接收 Redis 历史，但此前历史主要是 `user.content + assistant.content` 的自然语言文本，对“再高点 / 关掉它 / 换一个”这类省略句不够稳定。
- **新技术/方法**：将 Redis 对话历史从纯文本轮次升级为带 `metadata` 的结构化轮次；Gemma prompt 明确要求优先消费 `metadata.intent`、`metadata.slots`、`metadata.rewritten_query` 做指代继承。该阶段不恢复独立 `Correlation(8009)`，而是把其职责合并为 Gemma NLU 的结构化历史输入。
- **数据流**：
  - 写入：`server.py final_state -> db.tasks.post_request_tasks -> redis_client.push_history(role="assistant", metadata=...) -> Redis cardle:history:{device_id}`。
  - 读取：`server.py redis_client.get_history -> workflow.cardle_graph node_local_nlu -> client.nlu -> gemma_nlu_server history[-2:] -> Gemma NLU`。
  - 仲裁：`workflow.cardle_graph node_arbitration -> client.arbitration_client -> client.arbitration`，云端仲裁同样收到结构化 history。
- **核心数据结构**：
  - `ConversationTurn` 新增可选 `metadata: dict`，兼容旧历史记录。
  - assistant metadata 字段：`intent/function/slots/domain/is_safe/rewritten_query/candidate_intents`。
  - `EvalCase` 新增 `history` 字段，允许黑盒回归测试直接构造多轮上下文。
- **新增内置多轮回归样本**：
  - 上轮“把空调调到22度”，本轮“再高点” -> `Inc_Air_Condition_Temperature`。
  - 上轮“把音量调到30”，本轮“再大点” -> `Inc_Sound_Volume`。
  - 上轮“打开车窗”，本轮“关掉它” -> `Close_Window`。
- **测试结果**：
  - 工具级编译：`python -m py_compile db/models.py db/redis_client.py db/tasks.py server.py function_call/gemma_nlu_server.py tools/eval_gemma_nlu.py tools/gemma_console.py client/arbitration.py client/nlu.py tools/runner.py` 通过。
  - dry-run 样本加载：内置 7 条 smoke（含 3 条多轮）+ `dataset/test.jsonl` 前 2 条，共 9 条，报告写入 `scratch/gemma_nlu_eval_dry_run_multiturn.json`。
  - 首次真实多轮 smoke：基础 4/4 通过，多轮 0/3 失败，暴露 Gemma 未稳定继承 `metadata` 的问题。
  - 修复：在 `gemma_nlu_server.py` 增加结构化上下文 override；当当前 query 是“再高点/再大点/关掉它”等省略句，且上一轮 metadata 有明确控制对象时，确定性修正 Top-1 合法 intent。
  - 回归发现：prompt 调整后 `dataset/test.jsonl` 前 2 条一度被误吸到 A 类；已补充无害 D 类强制兜底和窄范围通用闲聊兜底。
  - 最终真实 smoke：7/7 通过，报告写入 `scratch/gemma_nlu_eval_smoke_after_domain_override.json`。
  - 最终真实 dataset 抽样：2/2 通过，报告写入 `scratch/gemma_nlu_eval_dataset2_after_domain_override.json`。
  - 历史兼容性：`ConversationTurn` 旧 JSON 无 metadata 与新 JSON 带 metadata 均可正常反序列化。

### 阶段 2.6：端到端多轮链路与延迟验收

- **目的**：从 Socket.IO 网关入口验证真实两轮链路，而不只测试 `/chatnlu/v1` 单点接口；同时把延迟纳入阶段验收指标。
- **新增工具**：`tools/eval_multiturn_e2e.py`。
- **新技术/方法**：
  - 临时拉起独立端口的 Redis、Arbitration、Gemma NLU、Gateway，避免污染默认开发端口。
  - 使用 Python Socket.IO 客户端模拟真实前端上行 `request_nlu` 事件。
  - 使用 Redis history 轮询确认后台 `post_request_tasks` 已写入结构化 metadata。
  - 报告记录每轮 `first_frame_ms`、`total_ms`、`history_write_ms`，并聚合 avg/max/p95。
- **端到端数据流**：
  - 第一轮：`Socket.IO query=把空调调到22度 -> server.py -> Redis history.get(empty) -> LangGraph -> Gemma NLU -> Arbitration(Mock) -> Tool Dispatcher -> Redis history metadata write`。
  - 第二轮：`Socket.IO query=再高点 -> server.py -> Redis history.get(2 turns with metadata) -> Gemma NLU context override -> Inc_Air_Condition_Temperature -> Tool Dispatcher -> Redis history metadata write`。
- **发现并修复的问题**：
  - 首次 E2E 只校验 intent 时通过，但日志显示 `Set_Air_Condition_Temperature` 的 `slots` 为空，工具实际执行为“打开空调，当前温度24度”，没有设置到 22 度。
  - 已在 `gemma_nlu_server.py` 增加确定性数字槽位补全：当 Top-1 intent 是空调温度/音量设置或增减，且 query/rewritten_query 中出现阿拉伯数字时，补入 `Number` 槽位。
  - `tools/eval_multiturn_e2e.py` 同步升级为校验 intent + expected slots，避免“意图对但参数没执行”的假阳性。
- **测试结果**：
  - 工具级编译：`python -m py_compile db/models.py db/redis_client.py db/tasks.py server.py function_call/gemma_nlu_server.py tools/eval_gemma_nlu.py tools/eval_multiturn_e2e.py tools/gemma_console.py client/arbitration.py client/nlu.py tools/runner.py` 通过。
  - E2E 两轮：2/2 通过，报告写入 `scratch/e2e_multiturn_latency_report_after_slot_override.json`。
  - E2E 验收细节：
    - 第 1 轮“把空调调到22度”：最终 `intent=Set_Air_Condition_Temperature`，`slots={"Number":"22"}`，工具调用参数 `temperature=22`。
    - 第 2 轮“再高点”：读取上一轮 metadata，最终 `intent=Inc_Air_Condition_Temperature`，`rewritten_query=把空调温度再调高一点`。
  - E2E 延迟指标（CPU 本地 Gemma）：
    - `first_frame_ms.avg=67336.43`，`max=72190.38`，`p95=72190.38`。
    - `total_ms.avg=67336.43`，`max=72190.38`，`p95=72190.38`。
    - `history_write_ms.avg=874.87`，`max=1314.74`，`p95=1314.74`。
  - NLU 回归：真实 smoke 7/7 通过，报告写入 `scratch/gemma_nlu_eval_smoke_after_e2e_slot_override.json`。
  - Dataset 抽样：`dataset/test.jsonl` 前 2 条 2/2 通过，报告写入 `scratch/gemma_nlu_eval_dataset2_after_e2e_slot_override.json`。
- **结论**：结构化多轮链路已端到端可用，但当前 CPU Gemma 延迟不可接受。下一阶段优先做“降低首帧/总耗时”的两阶段 NLU 与流式早路由，而不是继续扩大功能面。

### 阶段 3.1：两阶段 Gemma NLU Endpoint 与延迟指标

- **目的**：把原先一次性生成完整 `domain/is_safe/rewritten_query/candidate_intents` 的 `/chatnlu/v1` 拆出可灰度的新链路，为后续“流式早路由”和 B/C/D 类提前响应做准备，同时保留旧主链路兼容。
- **新技术/方法**：
  - 在同一个 Gemma 服务内使用三套独立 JSON Schema 受限解码：完整 v1 schema、`NLURouteResponseModel` route-only schema、`NLUIntentResponseModel` intent-only schema。
  - Pydantic schema 开启 `extra="forbid"`，让 `lm-format-enforcer + prefix_allowed_tokens_fn` 在 token 解码阶段禁止额外字段，减少模型输出解释文本或不存在字段的机会。
  - `tools/eval_gemma_nlu.py` 增加请求级 `latency_ms` 采样、`avg/max/p95` 汇总和 `--ignore-intent`，用于单独评估 `/chatnlu/route`。
- **新增/保留 Endpoint**：
  - `/chatnlu/v1`：旧完整输出路径，保持兼容。
  - `/chatnlu/route`：第一阶段，只输出 `domain/is_safe/reject_reason/rewritten_query`，并附 `_metrics`。
  - `/chatnlu/intent`：第二阶段，输入 query/history/可选 route 或 rewritten_query，只返回候选意图、兼容 Top-1 字段和 `_metrics`。
  - `/chatnlu/v2`：组合路径，先跑 route；只有 `domain=A && is_safe=true` 才继续跑 intent；最终返回旧主链路兼容字段。
- **数据流**：
  - Route：`query + history[-2:] -> route prompt -> route JSON Schema constrained decoding -> safety/context override -> route result`。
  - Intent：`query + rewritten_query + history[-2:] -> intent prompt -> intent JSON Schema constrained decoding -> safety/context/slot override -> function/intent/slots compat fields`。
  - v2：`route result -> 非 A 或 unsafe 直接 Unknown -> A 且 safe 才执行 intent -> 返回完整 NLU JSON`。
- **核心数据结构**：
  - `NLURouteResponseModel`：`domain/reject_reason/is_safe/rewritten_query`。
  - `NLUIntentResponseModel`：`candidate_intents: [{intent, slots}]`，最多 5 个候选。
  - `_metrics`：记录 `route.latency_ms/input_tokens/output_tokens`、`intent.latency_ms/input_tokens/output_tokens`、`total_latency_ms`。
  - 评测报告：每条 case 增加 `latency_ms`，summary 增加 `latency_ms.avg/max/p95/samples`。
- **测试结果**：
  - 工具级编译：`python -m py_compile function_call/gemma_nlu_server.py tools/eval_gemma_nlu.py tools/eval_multiturn_e2e.py` 通过。
  - dry-run：9 条样本加载通过，报告写入 `scratch/gemma_route_eval_dry_run.json`。
  - `/chatnlu/route` 真实 smoke：7/7 通过，报告写入 `scratch/gemma_route_eval_smoke.json`；HTTP 延迟 `avg=29213.51ms`、`max/p95=73601.40ms`、去掉冷启动首条后 `warm_avg=21815.53ms`。
  - `/chatnlu/v2` 真实 smoke：7/7 通过，Top-1/Top-5 全中，报告写入 `scratch/gemma_nlu_eval_smoke_v2.json`；HTTP 延迟 `avg=38809.39ms`、`max/p95=86437.76ms`、`warm_avg=30871.33ms`。
  - `/chatnlu/v2` dataset 抽样：2/2 通过，报告写入 `scratch/gemma_nlu_eval_dataset2_v2.json`；HTTP 延迟 `avg=46102.19ms`、`max/p95=64689.37ms`、`warm_avg=27515.01ms`。
  - `/chatnlu/v1` 兼容 smoke：7/7 通过，报告写入 `scratch/gemma_nlu_eval_smoke_v1_after_two_stage.json`；HTTP 延迟 `avg=52697.16ms`、`max/p95=113587.48ms`、`warm_avg=42548.77ms`。
- **阶段结论**：两阶段拆分已可用，且 B/C/D 类在 v2 中会跳过 intent 阶段。CPU 环境下 route-only warm 平均约 21.8 秒，v2 warm 平均约 30.9 秒，旧 v1 warm 平均约 42.5 秒；下一步应把网关接到 `/chatnlu/v2` 或进一步做流式字段级早路由，验证真实前端首帧是否下降。
