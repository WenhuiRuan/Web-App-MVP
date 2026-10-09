# HTTP API 与 SSE 契约 v1

阶段4第一批实现中，2026-10-09；阶段2契约基线保留。基础地址 `http://127.0.0.1:8000`；前端使用同源 `/api` 代理。UUID 标识、UTC 带时区时间、JSON 字符串为 UTF-8。请求结构禁止多余字段。浏览器不携带供应商密钥，不存在读取完整后端配置的接口。

## 实现状态与机器契约

- **已挂载**：GET `/api/health/live`、`/api/health/ready`、`/api/system`，以及 `/docs`、`/openapi.json`。运行时 OpenAPI 只描述这些真实可用端点。
- **阶段3前端**：通过独立mock客户端消费相同Snapshot/事件类型，未向业务HTTP/SSE路由发送请求；浏览器内的模拟重连不证明真实SSE已实现。
- **4A-1已挂载**：POST/GET `/api/discussions`、GET `/api/discussions/{discussion_id}`；4A-2已挂载嘉宾生成；启动与操作查询待4A-3，SSE与总结重试留后续批次。未挂载路由返回统一404。
- `docs/contracts/openapi.json` 是完整目标 HTTP 契约，`x-implemented` 区分状态；`docs/contracts/schema.json` 是公开数据、事件与模型边界 JSON Schema。
- `data/samples/contracts.json` 包含可运行检查的完整请求/响应/事件/模型结果示例。文件中的片段展示不同时间点/独立分支，不是一个真实运行记录。通过 `python -m scripts.export_contracts --check` 检测契约与产物漂移。

## 基础接口（已实现）

| 请求 | 成功响应 | 异常 |
|---|---|---|
| GET /api/health/live | 200 `{"status":"ok"}` | 只证明进程响应，不检查数据库/模型 |
| GET /api/health/ready | 200 `{"status":"ready","database":"ready","model_mode":"mock"}` | 503 DATABASE_UNAVAILABLE / MODEL_NOT_CONFIGURED |
| GET /api/system | 200 `{"name":"AI Panel Studio","version":"0.2.0","phase":2,"model_mode":"mock","discussion_engine_available":false}` | 非 mock 配置时 model_mode=unavailable；不返回地址、模型名称、密钥或完整 settings |

所有响应携带服务生成的 `X-Request-ID`；不信任或反射用户传来的 ID。ready 不调用真实模型；mock ready 不能证明模型服务接通。当前未实现的真实适配即使提供 Key 也不会触发外部调用。

## 讨论接口（契约冻结，逐批挂载；状态见上节及x-implemented）

| 方法与路径 | 请求 | 成功 | 典型错误 |
|---|---|---|---|
| POST /api/discussions | CreateDiscussion + Idempotency-Key | 201 Snapshot，DRAFT，last_event_seq=1 | 422 参数/缺少幂等键，409 幂等冲突 |
| GET /api/discussions | status=active/all（默认active）；limit1–100（默认20）；cursor? | 200 DiscussionList | 422 无效过滤/游标 |
| GET /api/discussions/{discussion_id} | 无 | 200 Snapshot | 404 DISCUSSION_NOT_FOUND |
| POST /api/discussions/{discussion_id}/roster-generation | 无 body 或 `{}` + Idempotency-Key | 202 OperationAccepted，GENERATING | 409 INVALID_STATE，503 CAPACITY_EXCEEDED/MODEL_NOT_CONFIGURED |
| POST /api/discussions/{discussion_id}/start | `{"roster_revision":1}` + Idempotency-Key | 202 OperationAccepted，RUNNING | 409 ROSTER_VERSION_CONFLICT/INVALID_STATE，503 CAPACITY_EXCEEDED |
| POST /api/discussions/{discussion_id}/summary-retry | 无 body 或 `{}` + Idempotency-Key | 202 OperationAccepted，SUMMARIZING | 409 INVALID_STATE |
| GET /api/discussions/{discussion_id}/operations/{operation_id} | 无 | 200 Operation | 404 OPERATION_NOT_FOUND（包括归属不匹配） |
| GET /api/discussions/{discussion_id}/events | after≥0（默认0），Last-Event-ID? | 200 text/event-stream | 404 议题不存在，409 游标不匹配/越界，422 参数格式错误 |

active 仅 RUNNING/SUMMARIZING；all 包含草稿、生成、失败、完成等。列表按 created_at DESC, id DESC，cursor 是相应二元组的 base64url 不透明游标，不使用 offset；到末尾 next_cursor=null。列表不携带 transcript。快照包含完整 transcript；本 MVP 最多20条正式消息，不需要历史消息分页。

所有命令 Idempotency-Key 格式为 UUID。相同 scope+command+key、相同规范化 body 返回原 HTTP 状态和原响应（即使任务后来失败）；不同 body 为409。显式失败后重试用新键，网络超时重发用原键。规范化 JSON 用已校验模型数据（含默认值、trim文本）、排序字段、UTF-8 进行 SHA-256；创建 scope=global，其余=discussion_id。同议题不同键重复 start、同 revision 已有 run 时返回既有 run，不能再调度。摘要重试已成功时返回原完成操作的响应，无新任务；尚在处理中也仅返回当前操作。

异步操作的 HTTP 202 只代表已受理，后续成功/失败通过 Operation、Snapshot 和 SSE 展现，不能将202当作阵容/总结成功。operation.status 与 discussion.state 分开。异步失败写状态和事件；原已返回202不能改成500。

### 创建请求与响应

```http
POST /api/discussions
Content-Type: application/json
Idempotency-Key: 33333333-3333-4333-8333-333333333333

{"topic":"是否推行四天工作制？","expert_count":4}
```

```json
{
  "discussion": {
    "id": "11111111-1111-4111-8111-111111111111",
    "topic": "是否推行四天工作制？", "expert_count": 4,
    "state": "DRAFT", "version": 0, "roster_revision": 0,
    "run_id": null, "failure_stage": null,
    "created_at": "2026-10-09T00:00:00Z", "updated_at": "2026-10-09T00:00:00Z"
  },
  "participants": [], "role_states": [], "messages": [],
  "insights": {"version":0,"through_turn":0,"items":[]},
  "summary": null, "last_event_seq": 1
}
```

### 生成与确认阵容

调用 roster-generation 仅允许 DRAFT 或 roster 阶段 FAILED/INTERRUPTED。成功生成后 roster.ready 携带全部嘉宾，再发送 state=READY；用户读 Snapshot 审阅阵容。禁止 READY 下主动重生成（MVP范围外）。

```http
POST /api/discussions/11111111-1111-4111-8111-111111111111/start
Content-Type: application/json
Idempotency-Key: 55555555-5555-4555-8555-555555555555

{"roster_revision":1}
```

```json
{"operation_id":"33333333-3333-4333-8333-333333333333","discussion_id":"11111111-1111-4111-8111-111111111111","state":"RUNNING","run_id":"22222222-2222-4222-8222-222222222222"}
```

进入演播厅后获取 Snapshot：participants 含姓名、title、stance、color；messages 仅正式发言，按 turn_no 升序；role_states 包含公开关注点；insights 是最新整批洞察；summary 成功后有自然语言内容。字段完整可校验例见 contracts.json 的 snapshot；机器结构明确所有字段，不返回数据库行的内部字段。

## 统一错误

```json
{"error":{"code":"ROSTER_VERSION_CONFLICT","message":"阵容版本已变更，请刷新后确认。","retryable":false,"request_id":"33333333-3333-4333-8333-333333333333","details":[]}}
```

| HTTP / code | 用户处理 |
|---|---|
| 422 VALIDATION_ERROR | 修改参数；details 当前为空，不回显输入/验证器上下文 |
| 404 NOT_FOUND / DISCUSSION_NOT_FOUND / OPERATION_NOT_FOUND | 返回列表；跨讨论操作 ID 也视为不存在 |
| 405 METHOD_NOT_ALLOWED | 修正方法 |
| 409 INVALID_STATE / ROSTER_VERSION_CONFLICT | 重取快照后决定，不盲目重试 |
| 409 IDEMPOTENCY_CONFLICT | 同键异参；明确新动作才生成新键 |
| 409 CURSOR_INVALID / SNAPSHOT_REQUIRED | 关闭 SSE、刷新快照与游标 |
| 503 DATABASE_UNAVAILABLE / CAPACITY_EXCEEDED | retryable=true，有界退避；容量忙建议 Retry-After:2（后续实现） |
| 503 MODEL_NOT_CONFIGURED | retryable=false；完成后端服务配置/适配 |
| 500 INTERNAL_ERROR | 只给通用说明及 request_id；不回传堆栈 |

模型阶段错误码另有 MODEL_TIMEOUT、MODEL_RATE_LIMITED、MODEL_AUTH_FAILED、MODEL_RESULT_INVALID。它们出现在 operation.failed 和 operation.error_code，不透传供应商 HTTP body。错误是否可重试由阶段决定；不会直接暴露 Key、模型原始输出或隐藏推理。

## SSE 事件契约

共同字段：schema_version=1；discussion_id UUID；run_id UUID/null（阵容阶段允许null）；seq≥1；type；occurred_at 带时区时间；payload 严格按 type 区分。客户端以 `(discussion_id, seq)` 去重、以 run_id 防旧运行状态覆盖。

| type | payload | 公开投影处理 |
|---|---|---|
| discussion.state_changed | state、version、failure_stage? | 更新生命周期；READY/GENERATING不属于最终完成 |
| roster.ready | roster_revision、participants[] | 用整套阵容替换；run_id必须null |
| participant.status_changed | participant_id、state、public_focus、version | 更新一个小窗，不追加 transcript |
| turn.committed | id、discussion_id、run_id、participant_id、turn_no、kind、content、created_at | 确认归属后追加正式消息；身份/颜色从已冻结阵容关联 |
| insights.updated | version、through_turn、items[{id,kind,content,source_message_ids}] | 用新批次替换面板；忽略旧版本，引用必须来自已知正式消息 |
| summary.ready | content、through_turn、created_at | 展示自然语言；必须在 COMPLETED 状态事件前 |
| operation.failed | operation_id、stage、code、message、retryable | 展示脱敏错误；配套 FAILED/INTERRUPTED 状态事件后关闭 |

```text
retry: 2000

id: 11111111-1111-4111-8111-111111111111:5
event: turn.committed
data: {"schema_version":1,"discussion_id":"11111111-1111-4111-8111-111111111111","run_id":"22222222-2222-4222-8222-222222222222","seq":5,"type":"turn.committed","occurred_at":"2026-10-09T00:00:00Z","payload":{"id":"66666666-6666-4666-8666-666666666666","discussion_id":"11111111-1111-4111-8111-111111111111","run_id":"22222222-2222-4222-8222-222222222222","participant_id":"77777777-7777-4777-8777-777777777777","turn_no":1,"kind":"opening","content":"我们先讨论效率与成本。","created_at":"2026-10-09T00:00:00Z"}}

: heartbeat

```

上例是线格式示例，participant_id 需在实际快照中存在。各类型均在 contracts.json 提供完整、可校验 payload。不发送 SpeakingIntent 内部事件，不输出 token 原始包，不展示 chain-of-thought。

### 连接、排序和恢复

1. 同一读事务获取快照与 k，客户端先应用快照，再 GET events?after=k。
2. 服务端校验游标；自动重连的 Last-Event-ID 优先于 after，必须属于 URL 的 discussion_id，且不超过现有高水位。初始无游标按0补全部事件。
3. 只从持久化表按 seq 升序分批读取（100条/批；空闲250ms轮询），不在补传后切换到可能漏消息的内存流。
4. 客户端 ≤k 丢弃、k+1 应用并推进游标，>k+1 或未知版本重取快照。议题切换关闭旧订阅，重新建投影。
5. 每15秒心跳不占序号；浏览器断线不停止后端讨论；COMPLETED/FAILED/INTERRUPTED的状态事件应用后关闭连接，用户重试后重新取快照订阅。
6. HTTP响应头发送前可返回结构化错误；连接已经建立后不能再改HTTP状态，意外流错误直接断开并由客户端恢复。业务操作失败用持久化事件表达。

## 模型调用边界（已实现接口与模拟，无真实网络）

`ModelGateway.generate(ModelRequest) -> ModelResult` 是异步协议。task 为 roster/intent/utterance/host_control/insights/summary；请求始终携带 discussion_id、topic、人数、阵容版本，运行中另含 run_id、participants、messages 和需要的 actor_id。上下文跨讨论引用被拒绝。

结果通过 task 判别联合类型解析，结构错误抛出固定 `InvalidModelResult('MODEL_RESULT_INVALID')`，不携带原文。roster 检查人数、唯一姓名/颜色/ID、归属；intent 检查回应目标；utterance 要求1–2句结构；insights 检查来源；summary 为普通自然语言。确定性模拟同请求同结果、无网络/时钟/共享历史，不代表真实 AI 质量，也不会自动循环讨论。有限修复、真实重试和终止预算由后续调用编排负责。
