# HTTP API 与 SSE 契约 v1

更新于2026-10-11，阶段5已接通持久化SSE及默认前端业务客户端，阶段6A增加DeepSeek真实适配，保留确定性替身。基础地址`http://127.0.0.1:8000`，UUID标识、UTC带时区时间、UTF-8 JSON；请求禁止多余字段，密钥只在后端环境。

## 实现状态与机器契约

- **基础接口已挂载**：GET `/api/health/live`、`/api/health/ready`、`/api/system`，以及 `/docs`、`/openapi.json`。运行时 OpenAPI 只描述真实可用端点。
- **当前前端**：默认真实HTTP/SSE；?mode=mock保留独立台本测试，不能证明模型能力。
- **讨论接口已挂载**：POST/GET `/api/discussions`、GET `/{discussion_id}`、POST `/{discussion_id}/roster-generation`、POST `/{discussion_id}/start`、POST `/{discussion_id}/summary-retry`、GET `/{discussion_id}/operations/{operation_id}`（均/api/discussions前缀）。以及GET `/{discussion_id}/events`。
- `docs/contracts/openapi.json` 是完整目标 HTTP 契约，`x-implemented` 区分状态；`docs/contracts/schema.json` 是公开数据、事件与模型边界 JSON Schema。
- `data/samples/contracts.json` 包含可运行检查的完整请求/响应/事件/模型结果示例。文件中的片段展示不同时间点/独立分支，不是一个真实运行记录。通过 `python -m scripts.export_contracts --check` 检测契约与产物漂移。

## 基础接口（已实现）

| 请求 | 成功响应 | 异常 |
|---|---|---|
| GET /api/health/live | 200 `{"status":"ok"}` | 只证明进程响应，不检查数据库/模型 |
| GET /api/health/ready | 200 `{"status":"ready","database":"ready","model_mode":"mock"}` | 503 DATABASE_UNAVAILABLE / MODEL_NOT_CONFIGURED |
| GET /api/system | 200 `{"name":"AI Panel Studio","version":"0.6.0","phase":6,"model_mode":"mock","discussion_engine_available":true}` | true表示当前已配置适配的讨论引擎可用；不代表此请求验证了上游连通或内容质量；未实现provider为unavailable/false |

所有响应携带服务生成的 `X-Request-ID`；不信任或反射用户传来的 ID。ready 不调用真实模型；mock ready 不能证明模型服务接通。ready不进行真实调用；已配置DeepSeek在业务模型任务执行时才调用外部服务。

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

所有命令 Idempotency-Key 格式为 UUID。相同 scope+command+key、相同规范化 body 返回原 HTTP 状态和原响应（即使任务后来失败）；不同 body 为409。显式失败后重试用新键，网络超时重发用原键。规范化 JSON 用已校验模型数据（含默认值、trim文本）、排序字段、UTF-8 进行 SHA-256；创建 scope=global，其余=discussion_id。同议题不同键重复 start、同 revision 已有 run 时返回既有 run，不能再调度。总结重试同键重放原响应，无新任务；处理中不同新键加入该重试的规范操作。COMPLETED后新键409，初次自动总结处理中也409。

异步操作的 HTTP 202 只代表已受理，后续成功/失败通过 Operation、Snapshot 和 SSE 展现，不能将202当作阵容/总结成功。operation.status 与 discussion.state 分开。异步失败写状态和事件；原已返回202不能改成500。

阶段4A/4B：生成操作异步从ACCEPTED→RUNNING→SUCCEEDED/FAILED/INTERRUPTED；查询Operation、Snapshot或SSE事件。start在事务内建立run后即操作SUCCEEDED，202保持既定契约；4B随后由唯一后台任务自动开场/调度、提取、总结直至COMPLETED或明确失败。同revision的新start键返回首个成功start的operation_id和run_id，不重复调度。即使run中断或已进入总结，重放仍返回原RUNNING受理响应，当前状态应以Snapshot为准。

服务关闭/重启：生成为INTERRUPTED/roster，讨论推进为INTERRUPTED/discussion，总结为INTERRUPTED/summary，failure_code=SERVICE_INTERRUPTED。保留已提交内容，不自动重放；roster与summary可用新命令键重试，discussion中断不恢复。原start保持SUCCEEDED；处理中手动总结操作为INTERRUPTED。容量GENERATING/RUNNING/SUMMARIZING默认合计3，READY不占容量；active列表只RUNNING/SUMMARIZING。

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
  "insight_status": {"state":"IDLE","version":0,"through_turn":0,"error_code":null},
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
| 503 DATABASE_UNAVAILABLE / CAPACITY_EXCEEDED / SERVICE_SHUTTING_DOWN | retryable=true；容量忙已实现Retry-After:2 |
| 503 MODEL_NOT_CONFIGURED | retryable=false；完成后端服务配置/适配 |
| 500 INTERNAL_ERROR | 只给通用说明及 request_id；不回传堆栈 |

本批任务错误码：MODEL_TIMEOUT、MODEL_RESULT_INVALID、TASK_FAILED、DATABASE_UNAVAILABLE、SERVICE_INTERRUPTED，出现在operation.failed及operation.error_code；真实适配未来另有MODEL_RATE_LIMITED、MODEL_AUTH_FAILED，不透传供应商HTTP body。错误是否可重试由阶段决定；不会暴露Key、模型原始输出或隐藏推理。

## SSE 事件契约

共同字段：schema_version=1；discussion_id UUID；run_id UUID/null（阵容阶段允许null）；seq≥1；type；occurred_at 带时区时间；payload 严格按 type 区分。客户端以 `(discussion_id, seq)` 去重、以 run_id 防旧运行状态覆盖。

| type | payload | 公开投影处理 |
|---|---|---|
| discussion.state_changed | state、version、failure_stage?、failure_code? | 更新生命周期；READY/GENERATING不属于最终完成 |
| roster.ready | roster_revision、participants[] | 用整套阵容替换；run_id必须null |
| participant.status_changed | participant_id、state、public_focus、version | 更新一个小窗，不追加 transcript |
| turn.committed | id、discussion_id、run_id、participant_id、turn_no、kind、content、created_at | 确认归属后追加正式消息；身份/颜色从已冻结阵容关联 |
| insights.updated | version、through_turn、items[{id,kind,content,source_message_ids}] | 用新批次替换面板；忽略旧版本，引用必须来自已知正式消息 |
| insights.status_changed | state、version、through_turn、error_code | 更新最新提取任务状态，失败保留成功观点批次 |
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
2. 服务端校验游标；Last-Event-ID（原生EventSource或外部客户端）优先于 after，必须属于 URL 的 discussion_id，且不超过现有高水位。初始无游标按0补全部事件。
3. 只从持久化表按 seq 升序分批读取（100条/批；空闲250ms轮询），不在补传后切换到可能漏消息的内存流。
4. 客户端 ≤k 丢弃、k+1 应用并推进游标，>k+1 或未知版本重取快照。议题切换关闭旧订阅，重新建投影。
5. 每15秒心跳不占序号；浏览器断线不停止后端讨论；COMPLETED/FAILED/INTERRUPTED的状态事件应用后关闭连接，用户重试后重新取快照订阅。
6. 当前前端fetch流断开后重新取Snapshot，再用after续订；没有假称fetch自动携带Last-Event-ID。离线事件取消reader，在线立即恢复，其他流异常按1/2/4/8/10秒退避；活性监测40秒。
7. HTTP响应头发送前可返回结构化错误；连接已经建立后不能再改HTTP状态，意外流错误直接断开并由客户端恢复。业务操作失败用持久化事件表达。

## 模型调用边界（已实现接口与模拟，无真实网络）

`ModelGateway.generate(ModelRequest) -> ModelResult` 是异步协议。task 为 roster/intent/utterance/host_control/insights/summary；请求始终携带 discussion_id、topic、人数、阵容版本，运行中另含 run_id、participants、messages 和需要的 actor_id。上下文跨讨论引用被拒绝。

4B模型请求补充cycle（intent/utterance/host_control必须≥1）、participation_kind、target_message_id、host_task及public_focus。主持utterance必须host_task=opening/followup/linking，不能携带专家参与类型；专家utterance必须REQUEST/INTERRUPT/SUPPLEMENT/REBUT，不可PASS或host_task。SUPPLEMENT/REBUT需target，所有target来自当前消息且不得自回应。只有utterance携带这些发言任务字段，intent/host_control结果才返回公开关注点。完整可校验请求见contracts.json新增model_requests（含专家反驳与主持串联）。模型输出的额外reasoning字段被拒绝。

专家发言请求示意（participants/messages使用同run完整上下文，不省略给供应商）：

```json
{"task":"utterance","cycle":2,"participation_kind":"REBUT","target_message_id":"66666666-6666-4666-8666-666666666666","host_task":null,"public_focus":"核对实施成本"}
```

上述只是新增字段片段；可执行完整实例以机器样例为准。主持发言片段为`{"task":"utterance","cycle":3,"host_task":"linking","participation_kind":null,"target_message_id":null}`。每个专家intent请求携带本轮公开Transcript，返回kind/target/relevance/public_focus，内部意图不出现在正式messages或turn.committed。

运行错误：Snapshot.discussion新增可空failure_code（固定安全码），FAILED/discussion表示推进失败且已提交messages保留。operation.failed关联该run最初start操作，但start.status仍SUCCEEDED；其完成的是建立run的命令。运行额度或host_control end后冻结数据库runs.summary_through_turn；SUMMARIZING期间summary=null，4C随后提取最后边界并生成总结至COMPLETED；失败可以重试总结。角色与turn事件已经持久化，仅能通过快照观察，真实SSE发送仍待后续。

结果通过task判别联合类型解析，结构错误固定InvalidModelResult，不携带原文。roster/intent/utterance沿用既有归属/短句检查；insights增加多人来源和完整消息边界，summary增加主持身份/冻结边界/观点来源及自然语言正文。确定性Gateway不访问网络、不保存共享聊天历史；DiscussionEngine/SynthesisEngine负责调用与有限重试，真实模型质量待后续。


## 4C-1实时观点契约

已实现每2条正式发言后提取、结束补最后边界。ModelRequest(task=insights)必须给出through_turn与正insight_version，messages必须是从turn1开始的完整前缀；participants属于当前讨论/run阵容。结果items可为空，每项至少引用两位不同专家的正式消息，归属与边界在模型校验、提交重建上下文和数据库复合FK/触发器中检查。

Snapshot新增insight_status={state,version,through_turn,error_code}，默认IDLE/0/0/null；state为PENDING/SUCCEEDED/FAILED/INTERRUPTED。insights仍表示最新成功批次，失败不清空已有观点；失败状态由快照轮询可见，尚无真实SSE。insights.updated只在完整批次事务成功后出现，version是领取序号，失败可能使成功版本跳号，客户端用较大版本整批替换。同边界不重复领取，旧领取不得提交。默认INSIGHT_MAX_SECONDS=10，MODEL_MAX_ATTEMPTS=2；失败后下一新消息边界继续，结束补提取失败仍允许后续总结使用旧成功观点。


## 4C-2总结完成契约

SUMMARIZING后先补最后观点边界，随后自动调用ModelRequest(task=summary,actor_id=主持人,through_turn=冻结边界,insights=最新成功批次)。messages为1..through_turn完整前缀；insights.through_turn不超过冻结边界，来源继续验证。结果content必须是1..4000字符自然语言，拒绝原始JSON和代码块；含主要观点、共识不足/已有共识、未解决分歧，语义内容质量留真实模型验收。

summary.ready与run完成/COMPLETED同事务。普通turn停止后不再新增消息。SUMMARY_MAX_SECONDS=60总预算从总结任务开始计，包括Semaphore等待；每次调用还受MODEL_TIMEOUT_SECONDS限制，最多MODEL_MAX_ATTEMPTS次。自动总结失败发布operation.failed(stage=summary,retryable=true)，引用最初start操作，该操作仍SUCCEEDED；Snapshot为FAILED/summary及安全failure_code，消息/观点/边界保留。HTTP summary-retry已实现，行为见下一节。

## 4C-3总结重试与错误示例

`POST /api/discussions/{id}/summary-retry`只在FAILED/INTERRUPTED且failure_stage=summary时新建重试；SUMMARIZING中的手动重试允许其他键加入，初次自动总结处理中或COMPLETED后新键返回409 INVALID_STATE。相同键始终返回原202，不因服务重启而恢复旧任务。未配置模型503 MODEL_NOT_CONFIGURED、容量已满503 CAPACITY_EXCEEDED、写事务失败503 DATABASE_UNAVAILABLE；非法body/键422，未知讨论404。上述均沿用ErrorResponse，不返回原始模型结果。

```http
POST /api/discussions/11111111-1111-4111-8111-111111111111/summary-retry
Content-Type: application/json
Idempotency-Key: 55555555-5555-4555-8555-555555555555

{}
```

```json
{"operation_id":"33333333-3333-4333-8333-333333333333","discussion_id":"11111111-1111-4111-8111-111111111111","state":"SUMMARIZING","run_id":"22222222-2222-4222-8222-222222222222"}
```

操作查询在受理后为`kind=summary-retry,status=RUNNING,error_code=null`；成功SUCCEEDED，失败FAILED加安全code，中断INTERRUPTED/SERVICE_INTERRUPTED。同run并发新键记录别名操作但返回首个规范operation_id，别名状态与规范任务结果同步。新尝试只增加summary_jobs.attempt，不重置summary_through_turn、生成阵容或重放讨论；捕获的insight_version保持不变，重试不重新提取观点。

```json
{"schema_version":1,"discussion_id":"11111111-1111-4111-8111-111111111111","run_id":"22222222-2222-4222-8222-222222222222","seq":20,"type":"operation.failed","occurred_at":"2026-10-09T00:00:00Z","payload":{"operation_id":"33333333-3333-4333-8333-333333333333","stage":"summary","code":"MODEL_TIMEOUT","message":"总结生成失败，消息和观点已保留，可以重试总结。","retryable":true}}
```

该事件是失败分支的字段示例，seq依实际持久化高水位分配；当前已通过真实SSE发送。insights.updated与summary.ready完整来源/正文/封装样例见contracts.json（两位专家来源）；ModelRequest完整提取/总结上下文同文件model_requests。

## 阶段5已挂载SSE

GET `/api/discussions/{discussion_id}/events?after=0` 为实际接口；游标表示最后已接收的seq（不再次发送）。Last-Event-ID存在时优先，必须是本讨论UUID:非负整数；格式/跨场/超过持久化高水位返回409 CURSOR_INVALID，after格式/负数422，不存在讨论404。UUID规范化比较，无鉴权账号，本地单用户讨论归属指路径中的讨论。

先GET快照，取同一读取事务的last_event_seq，再订阅after；订阅建立前后的新提交从数据库补发。每页100，250ms轮询，每次只在短只读事务内读取，yield/等待前释放连接。UTF-8，Cache-Control:no-cache,no-transform，X-Accel-Buffering:no。初始retry:2000，15秒注释心跳不增加seq。终态COMPLETED/FAILED/INTERRUPTED在该次高水位全部发送后关闭；重试总结前端重新快照与新订阅。DRAFT/GENERATING/READY保持连接。

```text
id: 11111111-1111-4111-8111-111111111111:12
event: insights.status_changed
data: {"schema_version":1,"discussion_id":"11111111-1111-4111-8111-111111111111","run_id":"22222222-2222-4222-8222-222222222222","seq":12,"type":"insights.status_changed","occurred_at":"2026-10-10T00:00:00Z","payload":{"state":"FAILED","version":2,"through_turn":4,"error_code":"MODEL_TIMEOUT"}}

: heartbeat

```

新增insights.status_changed：InsightStatus作为payload，PENDING/SUCCEEDED/FAILED/INTERRUPTED随任务事务提交，版本表示提取任务版本，独立于最后成功InsightBatch；失败保留已成功批次。SUCCEEDED紧随insights.updated。discussion.state_changed增加可空failure_code（旧事件缺省null），重试清空错误。旧存量消息和事件不重写，schema_version仍1，此为兼容字段/类型扩展；旧客户端收到未知类型需刷新快照，部署时前后端共同升级。

流开始后的数据库/传输异常通过关闭连接表示，不能在SSE中返回JSON错误；客户端恢复快照。观察者取消只取消本订阅，运行任务归TaskSupervisor管理。

## 阶段6A：安全模型状态与上游边界

GET /api/system 示例（只列安全信息）：

```json
{"name":"AI Panel Studio","version":"0.6.0","phase":6,"model_mode":"real","model_provider":"deepseek","model_name":"deepseek-flash","discussion_engine_available":true}
```

GET /api/health/ready 返回 {"status":"ready","database":"ready","model_mode":"real"}；仅配置/数据库检查，不是网络或认证验证。缺少配置时503/MODEL_NOT_CONFIGURED，message仅列缺失的MODEL变量名。上游JSON格式与内部ModelResult不同：角色内容无identity，target_turn/source_turns映射到本run已有消息；原HTTP讨论与SSE契约保持不变。

模型失败持久化到operation/failure_code/insight_status.error_code：认证MODEL_AUTH_FAILED、余额MODEL_BALANCE_EXHAUSTED、参数MODEL_REQUEST_INVALID、模型MODEL_NOT_FOUND，均不自动重试；限流MODEL_RATE_LIMITED、服务MODEL_SERVICE_UNAVAILABLE、网络MODEL_CONNECTION_FAILED、超时MODEL_TIMEOUT可有限重试，非法输出MODEL_RESULT_INVALID亦受原有限策略约束。响应不包含上游原始正文或密钥；配置修复后的显式重试仍使用新幂等键，讨论失败不自动续跑，总结失败只重试冻结边界。

完整配置、六任务传输示例与官方依据见[模型适配](model-provider.md)。

阶段6A定向修正：上游insights每项增加公开evidence数组（turn/quote），与source_turns一一对应，后端校验原文片段与专家归属；这些字段不进入业务HTTP或SSE。公开上下文每条消息附带speaker_name/title/kind。详情、实际引用及未全面通过的语义限制见[首轮质量记录](quality-first-round.md)。

阶段6A续批：业务HTTP/SSE/ModelResult及SQLite不变。DeepSeek任务内新增公开来源review协议，观点只保留有证据的候选（源集合不能扩大），总结以现有观点index选择并绑定实际发言作者，后端组装自然语言content。客户端仍接收原insights.updated/summary.ready，不接收草稿、checks或模型review JSON。失败沿用insight_status/summary failure_code与原重试规则；详细上游字段见[模型边界](model-provider.md)。

续批最终摘要约束：positions按speaker_slot和source_turns绑定实际作者，content必须是该作者来源消息的连续原文；pending按turn/quote及有限issue标签绑定待核对片段。共识/分歧仍选已捕获批次index，正文为自然语言而非原JSON。该约束不认证原发言的事实，也不保证概述/选择/标签语义；真实检查与整场未重跑的边界见[质量修正验收](quality-revision.md)。

本次验收收尾仅扩展内部ModelRequest：insights任务可带上一成功InsightBatch，要求较旧版本、同讨论/运行且来源在前批边界内，供全前缀重新审核。HTTP/SSE仍发布最新完整批次（非追加差量），不向浏览器暴露candidate/checks/草稿。旧观点经过本次复核才保留，撤回/条件变化更新或删除；个别非法来源或数量候选不连带丢失其他有效观点。上游协议详见model-provider，现有客户端投影和SQLite结构不变。


阶段6A收尾：模型模式由后端MODEL_THINKING_MODE/REASONING_EFFORT/THINKING_MAX_TOKENS控制，六任务保持原结构化结果契约。上游reasoning_content不消费、不保存、不下发；公开HTTP/SSE字段不增加隐藏推理。真实服务徽标仍区分DeepSeek与模拟模式；模式就绪不证明内容正确。

验收收尾补丁：迁移006允许观点/总结任务表保存全部安全供应商错误码，修复402等失败写入回滚后页面滞留PENDING的问题。观点失败发布insights.status_changed并保留最新成功批次；总结失败发布原失败事件与FAILED/failure_stage=summary/failure_code，用户使用原summary-retry接口和新幂等键重试同run及冻结边界。不可重试指统一调用层不自动重试，余额/配置修复后的用户显式重试仍允许；并发领取及迟到结果守卫不变。

HTTP/SSE字段与导出schema不变。多步观点/总结按每HTTP超时和统一有限总预算分别限制，普通任务规则不变；具体参数见model-provider.md。ready仍不检查余额，不能由ready成功推断真实调用可用。

最终0465f68真实浏览器走原创建/生成/确认/SSE/快照/总结接口成功，8消息/4观点批次（RUNNING时两次非空）/113连续事件；内容逐条内容复核与空分歧依据见quality-acceptance.md。终态为COMPLETED且冻结8，实际turn_limit。未新增接口字段或重写旧场数据；本场无总结重试，重试行为由已有E2E及新增供应商错误持久化测试证明。

## 最终运行参数与样例入口

API v1和事件格式未因交付改变，系统版本0.6.0/phase6。默认日常run显式20条/600秒；验证8条不是产品要求。DeepSeek enabled/low/16384；HTTP120秒、观点240秒、总结180秒。公开端点不返回密钥/完整配置；离线样例导入不是新HTTP接口，见根README。


## 互动修正后的模型内部契约（HTTP/SSE v1不变）

HostControlResult.action允许continue/followup/linking/end。continue仅继续专家；followup/linking实际调用主持utterance。可选addressed_actor_id及target_message_id必须属于当前专家阵容/已提交消息，continue/end禁止带目标。DeepSeek仅返回addressed_slot/target_turn，后端绑定UUID。示例：`{"action":"followup","public_focus":"请说明刚提出的比例依据","addressed_slot":2,"target_turn":7}`，引用为实际上下文编号，非固定答案。

主持utterance请求增加可选addressed_actor_id、host_reference_message_id，与host_task绑定；专家仍使用participation_kind/target_message_id。专家响应机会在主持追问后先执行，内部参与意图不进入Transcript。

模型复核PointsReview每个index一次，增加merge_with（默认[]）。明确语义重复的leader可引用合并组来源并集，其他项explicit_positions=false，不再按引用相同自动合并。SummaryPending新增UNRESOLVED_CONDITION/UNSUPPORTED_THRESHOLD，引用仍逐字对应原消息。自然正文不再从空disagreement自动宣称没有争议。

insights.updated仍是完整批次替换，每批version递增且through_turn为冻结前缀；后台合并待处理边界，因此不保证每两条发言都产生一个版本。insights.status_changed展示正在提取的前缀与失败，旧观点保留；正式发言可与提取同时推进。SUMMARIZING先收敛最终边界，再独立总结预算；失败保留旧批次并携带其旧边界，原发言仍为总结核对依据。

补验内部上下文显式区分through_turn（冻结消息边界）、insights_through_turn及insights_version（输入成功观点边界/版本）。只传公开最终回答，HTTP/SSE不新增字段。共识候选整批合并按同一对象、动作、条件，不以相同来源或支持者更多制造重复项。仅在可靠但夹带单方条件的最多两项候选上进行一次合并收窄repair；共用240秒总预算，没有逐候选无限复核。

总结positions逐字个人摘录仅允许该作者最后一条正式消息，source_turns恰好一条；内部summary_position_turns给出可选消息编号，程序拒绝早期个人摘录（summary_position_not_latest），统一有限重试不另增层。此保守选择不意味着旧观点撤回，早期仍成立的共识/分歧保留在独立复核的insights中；可能省略此前独立但未撤回的个人建议，列为召回限制。

## 安全模型诊断查询

新增只读`GET /api/discussions/{discussion_id}/diagnostics?run_id={run_id}&limit=100&before={id}`。run_id可省略（含本讨论阵容尝试），limit默认100且1–100，before可省略且为正整数；id倒序，next_before存在时续取旧页。不存在讨论或跨场运行404/RUN_NOT_FOUND（不存在讨论沿用DISCUSSION_NOT_FOUND），格式/范围422。业务消息/快照/SSE v1不变；诊断不进入Transcript。

完整格式示例，**并非旧失败场的已知原因或补造记录**：

```json
{
  "items": [{
    "id": 73,
    "discussion_id": "11111111-1111-4111-8111-111111111111",
    "run_id": "22222222-2222-4222-8222-222222222222",
    "roster_revision": 1,
    "actor_id": "33333333-3333-4333-8333-333333333333",
    "actor_name": "陈序", "actor_title": "圆桌主持人", "actor_kind": "HOST",
    "turn_claim_id": "44444444-4444-4444-8444-444444444444",
    "call_id": "55555555-5555-4555-8555-555555555555",
    "task": "utterance", "host_task": "linking", "cycle": 15,
    "message_position": 15, "attempt": 1, "stage": "single",
    "outcome": "FAILED", "error_code": "MODEL_RESULT_INVALID",
    "failure_type": "SENTENCE_BOUNDARY", "duration_ms": 1250,
    "occurred_at": "2026-10-11T06:00:00Z"
  }],
  "next_before": null
}
```

outcome=SUCCEEDED/FAILED/CANCELLED/DEADLINE/HOST_SKIPPED，安全failure_type详见[诊断报告](model-recovery.md#普通启动下的安全诊断)。actor资料来自同场阵容；阵容任务无actor/run/claim，message_position=0。utterance的position为计划下一条，其余任务为上下文边界。attempt是一次generate尝试序号（可能多段HTTP），并非HTTP调用数。stage只在可定位的失败保存，其他null；SUCCEEDED不是业务提交凭证。表中不保存完整响应、输入异常、密钥、认证头或reasoning_content。

内部ModelRequest新增attempt=1、validation_feedback=null；纠正重试例如attempt=2 / validation_feedback=SENTENCE_BOUNDARY。上游context提供output_correction的固定安全约束，不携带上次坏正文。发言契约保持sentences 1–2项、每项一句/≤200字、总正文≤400；共享分句规则识别闭引号、嵌入问句、小数和常用缩写。严格校验不因恢复而绕过。

非开场主持非法输出重试耗尽可最多累计2次HOST_SKIPPED，原领取取消并同事务角色IDLE事件，下一周期专家自主决定；不发布turn.committed或虚假提问，不增加message_position。认证/取消/数据库错误不恢复；超限继续原FAILED和failure_code。旧失败场未保存诊断，007不能补出原响应原因。重启后端才启用；本轮只有可控验收，用户真实复测待完成。

意图上游context新增participation_rules：host_question_is_invitation=true、may_pass=true、may_challenge_question=true、must_follow_host_conclusion=false，public_focus不继承主持任务。职业、stance及真实messages保留，PASS仍须target_turn=null，实际补充/反驳仍绑定当前已提交消息；主持点名不给出强制发言命令或预设结论。

opening上游context使用独立opening.md（仍属于utterance任务），opening_rules为：

```json
{"original_question":"公共图书馆是否应该延长夜间开放时间？","preserve_topic_meaning":true,"invite_views":true,"allow_analysis_framework":false,"assign_guest_directions":false}
```

original_question直接来自request.topic；开场自然提出原题并向全场邀请看法，1–2句，不改成条件/应对子问题、不添加分析框架或逐人任务。开场context仅含task/topic/host_task/actor_slot、主持身份participants及attempt/output_correction，不携带专家职业/stance、public_focus、messages或观点，避免提前安排切入角度。slot仍使用本场原始位置，结果身份仍由后端校验绑定。讨论中的followup/linking仍使用原公开Transcript、实际回应对象和具体疑问；专家参与context及仲裁不变。HTTP/SSE和内部ModelRequest契约不变；不硬拼正文、不新增逐字匹配或语义保证。受控检查与真实待验范围见model-recovery。

## 当前分歧证据与过程发布（PL-022，覆盖早期结束取消说明）

业务HTTP/SSE/ModelRequest及SQLite版本仍007，不新增事件类型。insights.updated仍为带version/through_turn的完整批次；新REBUT触发不是公开分歧消息，正式Transcript仅发言。普通更新合并，首次待处理的直接专家回应边界被保护到消费。正常SUMMARIZING后可继续发布尚在预算内的过程批次，再发布最终完整边界；因此SUMMARIZING不意味着insights已覆盖全部消息。FAILED/INTERRUPTED关闭仍按原规则取消，迟到/旧版不能提交。

Snapshot.insights指最后成功结果，insight_status指最新任务。页面同时展示已发布范围、在途范围和现场消息数，较旧零项只描述已提取前缀。最终提取成功且through_turn==冻结边界时总结使用该批次；失败时旧批次保留在面板，总结insights为空并回读完整冻结messages，不强制纳入可能已化解的旧分歧。

上游EvidenceChecks增加可空opposing_judgments_supported。共同守卫authors_correct/same_object/compatible_scope/explicit_positions/proposal_preserved/not_superseded均须true；consensus另要求every_condition_supported=true，disagreement另要求opposing_judgments_supported=true（缺失不接受），不以every_condition_supported=false否定各方真实的相反判断。该标记是模型判断，不是程序语义证明。来源/专家归属/消息边界/连续引文及旧结果守卫不变；内部候选、checks与草稿仍不发送给页面。
