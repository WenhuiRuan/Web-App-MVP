# 后端生命周期与后台任务实现

阶段4第一批历史记录，2026-10-09。4A实现生命周期、阵容与持久化；4B现已增加自动发言/主持控制，见[自动调度说明](backend-orchestration.md)。以下“本批”指4A，SSE与真实模型服务仍待后续。

## 小批交付状态

| 小批 | 范围 | 当前状态 |
|---|---|---|
| 4A-1 | 创建、列表、快照、规范化创建幂等、原子初始事件、读写错误 | 17个先失败用例实现通过；真实FastAPI/SQLite |
| 4A-2 | 生命周期规则、后台嘉宾生成/校验/重试、完整阵容及事件原子提交、两讨论隔离 | 27个先失败规则/接口用例实现通过 |
| 4A-3 | 启动幂等/并发、操作查询、任务统一关闭/重启恢复、完整接口运行检查 | 新增30个场景（与10个旧规则共40）：先28失败/12通过，实现后40通过；全量105通过 |

## 已实现的数据与接口边界

POST /api/discussions创建DRAFT、version0、last_event_seq1及SUCCEEDED创建操作；201响应冻结保存以供重复请求重放。请求按已验证模型（含trim和默认4）序列化并SHA-256，same scope/kind/key异参409。SQLite BEGIN IMMEDIATE内同时保存实体/操作/事件，任何写入错误回滚。

GET /api/discussions默认active仅RUNNING/SUMMARIZING，all含所有状态；limit1–100，默认20；按created_at DESC,id DESC，使用base64url编码的时间/UUID游标。GET /api/discussions/{id}在一个读事务中读取当前阵容、current_run下角色/消息/最新观点/总结及last_event_seq；不跨discussion读取。

运行时OpenAPI仅挂载实际可用路由。目标OpenAPI将已实现操作标true，其他保留设计false；错误沿用ErrorResponse，不返回输入、SQL原文、模型输出、凭据或堆栈。

## 4A-2 生成任务与原子阵容

TaskSupervisor归应用lifespan所有；注册表按operation_id去重，全局Semaphore限制ModelGateway调用。受理后立即202，领取任务时ACCEPTED→RUNNING；命令本身的受理响应被冻结，任务后续状态另查。网络等待在事务外；结果通过validate_result再次检查字段、基数、唯一身份/颜色、讨论与revision归属。

admit_generation在BEGIN IMMEDIATE中做状态/容量检查、operation及GENERATING事件。complete_generation以operation状态和当前discussion/revision为守卫，在一事务写完整roster/participants、roster.ready、READY、成功operation，并验证完整Snapshot；任何失败回滚。失败另事务写operation.failed+FAILED(roster)，保留topic；新幂等键可以重试，旧键仅重放原202。

生成错误：MODEL_TIMEOUT、MODEL_RESULT_INVALID、TASK_FAILED、DATABASE_UNAVAILABLE，公开说明固定脱敏。数据库完全不可写时无法再记录失败，日志仅固定恢复标记，下次数据库可写且启动恢复成功后标INTERRUPTED，不伪造成功。

容量：默认3个工作讨论，统计GENERATING/RUNNING/SUMMARIZING；模型并发4。READY不消耗生成容量，start重新检查容量。服务目前单worker，禁止同时用多个应用实例管理同一本地数据库。

## 4A-3 确认、操作查询与恢复

start命令走应用监督器，短BEGIN IMMEDIATE内检查幂等、纯规则should_create_run、revision/READY、容量和完整Snapshot；同时写唯一ACTIVE run、confirmed_at、所有角色IDLE、current_run_id、RUNNING事件、SUCCEEDED操作。run冻结max_turns/max_seconds（20/300），本批只保存额度，不执行调度或终止计时。任何失败整体回滚，已READY阵容保留。

相同key返回原202；同revision不同key返回首个成功start的完整202（相同operation_id/run_id），另保存新key的SUCCEEDED操作记录用于异参冲突检测。不同key不会产生额外run、角色或RUNNING事件。已有run即使已中断也只重放受理响应；实时状态从Snapshot读取，start不是续跑命令。不存在/归属错误的operation均404，查询只公开id/discussion_id/kind/status/error_code。

后台任务注册表以operation_id去重，受理任务单独登记并shield，HTTP请求取消不丢失已受理工作。模型调用受超时/全局Semaphore约束；结果提交校验operation状态、discussion与revision，旧结果不能覆盖新重试或其他讨论。模型异常与写入异常均通过固定安全错误持久化。

lifespan启动时先执行recover_unfinished，再接受请求。关闭时先closing拒绝新受理，取消/收集受理和模型任务，shield并等待在途to_thread数据库调用（线程取消不能取消SQLite），最后恢复残余工作。若提交已开始，允许完整提交为READY；尚未完成的GENERATING变INTERRUPTED/roster，对应operation标INTERRUPTED/SERVICE_INTERRUPTED并写operation.failed。RUNNING变INTERRUPTED/discussion，ACTIVE run结束，角色回IDLE；start操作仍SUCCEEDED，因为建立run的命令已完成。SUMMARIZING遗留也按summary标中断，但总结生成/重试尚未实现。

恢复更新数据/操作/事件在同一事务，重复执行不新增中断事件，DRAFT/READY/终态保留，无自动模型调用。数据库关闭时不可写只记固定标记；下次启动数据库必须可写并完成恢复才能就绪。任意不响应取消的真实适配或无限阻塞磁盘不在当前验证范围；后续适配须遵守取消/超时。

## 复现与证据

- backend/tests/test_lifecycle_api.py：17个创建/查询/初始事务场景。
- backend/tests/test_roster_tasks.py：17个任务/故障/两讨论/原子阵容场景；test_lifecycle_rules.py共17个纯规则场景。
- backend/tests/test_start_recovery.py：23个确认/并发/容量/操作归属/回滚/关闭与恢复场景。
- scripts/smoke_lifecycle.py：独立进程、随机空闲loopback端口、临时SQLite，真实HTTP创建→两场生成→不同key并发确认→强制终止自有进程→重启检查。不会关闭其他服务，临时证据保留work/lifecycle-smoke-*。
- 全量pytest105通过；原前端浏览器16通过，仍是前端模拟/基础代理验证，不是完整业务E2E。实际结果和边界见progress。
