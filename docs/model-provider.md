# DeepSeek 模型适配（阶段6A）

采用已锁定 httpx 0.28.1 调用 Chat Completions，不增加 SDK。应用模型由后端独立配置，与 Codex 开发模型无关。mock 保留确定性替身；deepseek 配置齐全才建立真实网关。六任务沿用原引擎逐任务调用，不预生成整场台本。

## 官方接口依据（2026-10-10核对）

- [Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)：POST {MODEL_BASE_URL}/chat/completions，OpenAI兼容消息。
- [非思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)：顶层 thinking.type=disabled，只读取 message.content，不读取、持久化、展示或记录 reasoning_content。
- [JSON输出](https://api-docs.deepseek.com/guides/json_mode/)：response_format.type=json_object；Prompt 要求 JSON 并给出示例。空内容、截断及非法结构不能提交。
- [模型说明](https://api-docs.deepseek.com/quick_start/pricing/)：用户选择的 deepseek-flash 当前对应 DeepSeek-V4.1-Flash；实际响应只报告别名，不宣称精确权重版本已验证。
- [错误码](https://api-docs.deepseek.com/quick_start/error_codes/)：区分认证/余额/参数与限流/服务暂时失败。

## 配置与就绪

Settings 读取项目 .env，进程环境优先。MODEL_API_KEY=${PANEL_API_KEY} 使用 dotenv 展开；PANEL_API_KEY 必须被后端进程继承。机器级设置后已打开的终端可能尚未继承；重新打开终端，或仅将这个已授权变量导入后端启动进程。不打印、不改写用户 .env、不读取 Codex 凭据。

必填 MODEL_BASE_URL、MODEL_NAME、MODEL_API_KEY；缺失/未展开时 ready=503，只列变量名。地址只允许 HTTPS，测试可 loopback HTTP；拒绝 URL 用户信息/query/fragment，关闭重定向。未知 provider 报 MODEL_PROVIDER。ready 只证明配置和数据库就绪，不检查认证、余额或网络，不发起付费调用。

system 返回 phase=6/version=0.6.0、model_mode=mock/real/unavailable、model_provider、model_name、discussion_engine_available；无密钥或地址。顶部真实模式为“DeepSeek · deepseek-flash（真实服务）”。mode=mock 页面仍是前端台本，后端 mock 是工程替身。

## Prompt与上下文

[通用规则](../backend/prompts/common.md)及六个任务文件位于 backend/prompts/，按任务加载和版本审查；每次仅包含本场公开资料，没有共享聊天历史。

| 任务 | 模型提供 | 后端绑定/校验 |
|---|---|---|
| roster | kind/name/title/stance | 主持人优先、UUID5(讨论,revision:slot)、归属与颜色；主持人唯一、专家数量、字段及姓名唯一 |
| intent | kind/target_turn/relevance/public_focus | turn映射本场message_id；禁止跨场、不存在、自回应、PASS带目标 |
| utterance | sentences | 携带参与类型/target_turn或host_task；1–2句，每句≤200字，总≤400字 |
| host_control | action/public_focus | 开场/追问/串联仍通过独立发言任务，end冻结边界 |
| insights | kind/content/source_turns | 同run及边界映射；每项至少两位专家直接来源；后端生成版本化ID |
| summary | content | 解开JSON包装后提交自然语言；捕获同run冻结前缀和观点，拒绝JSON正文 |

供应商结构禁止额外字段（含identity/reasoning），结果再经原ModelResult契约。结构来源有效不等于语义忠实，真实内容单独人工核对。SQLite事务守卫、正式消息及SSE机制不变。

## 重试与观测

全部任务由 DiscussionEngine.call_model 唯一重试，HTTP网关每次只发一个请求。MODEL_MAX_ATTEMPTS 含首次，默认2。401/403→MODEL_AUTH_FAILED、402→MODEL_BALANCE_EXHAUSTED、400/422→MODEL_REQUEST_INVALID、404→MODEL_NOT_FOUND，不自动重试；429→MODEL_RATE_LIMITED、5xx→MODEL_SERVICE_UNAVAILABLE、网络→MODEL_CONNECTION_FAILED、超时→MODEL_TIMEOUT，可在剩余预算内重试。Retry-After数值最多5秒，缺省0.5秒；HTTP-date不解析，回退0.5秒。非法输出依原策略最多2次。

阵容总预算=单次超时×次数+5秒×重试间隔数，默认65秒。讨论300秒、单次IO30秒、提取10秒、总结60秒（独立），并发4；排队和退避计入预算。取消向下传播，监督器关闭后拒绝迟到结果，收集任务后关闭client。

网关最多2000条安全内存指标：任务、讨论/run、HTTP状态、安全码、耗时、返回model别名、用量数字（prompt/completion/total/cache hit/miss）。不含Prompt、回答、reasoning、请求头或原始错误。无返回usage时为null，不能估算0。生产不公开指标接口、不写业务库；验证入口可导出到ignored work/。

## 验证入口

test_deepseek.py 使用HTTP MockTransport检查请求/解析/错误/有限重试/取消；test_deepseek_http.py 使用实际loopback HTTP上游、FastAPI任务及临时SQLite验证六任务闭环，与真实供应商结果分开。

主动真实验证：项目根启动 `.venv/Scripts/python.exe -m scripts.real_validation_server`；前端目录设置 PANEL_REAL_VALIDATION=1、PLAYWRIGHT_CHANNEL=msedge，执行 `npm exec playwright -- test --config=playwright.real.config.ts`。该入口会付费调用，不属于普通自动测试；前端不传入密钥。保持单进程、单worker、单数据库所有者。
