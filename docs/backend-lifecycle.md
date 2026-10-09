# 后端生命周期与后台任务实现

阶段4第一批，2026-10-09。实现依照现有数据模型、HTTP/SSE数据契约和ModelGateway；本批不实现自动发言调度、主持人控制、SSE路由或真实模型服务。

## 小批交付状态

| 小批 | 范围 | 当前状态 |
|---|---|---|
| 4A-1 | 创建、列表、快照、规范化创建幂等、原子初始事件、读写错误 | 17个先失败用例实现通过；真实FastAPI/SQLite |
| 4A-2 | 生命周期规则、后台嘉宾生成/校验/重试、完整阵容及事件原子提交、两讨论隔离 | 27个先失败规则/接口用例实现通过 |
| 4A-3 | 启动幂等/并发、操作查询、任务统一关闭/重启恢复、完整接口运行检查 | 待先编写测试 |

## 已实现的数据与接口边界

POST /api/discussions创建DRAFT、version0、last_event_seq1及SUCCEEDED创建操作；201响应冻结保存以供重复请求重放。请求按已验证模型（含trim和默认4）序列化并SHA-256，same scope/kind/key异参409。SQLite BEGIN IMMEDIATE内同时保存实体/操作/事件，任何写入错误回滚。

GET /api/discussions默认active仅RUNNING/SUMMARIZING，all含所有状态；limit1–100，默认20；按created_at DESC,id DESC，使用base64url编码的时间/UUID游标。GET /api/discussions/{id}在一个读事务中读取当前阵容、current_run下角色/消息/最新观点/总结及last_event_seq；不跨discussion读取。

运行时OpenAPI仅挂载实际可用路由。目标OpenAPI将已实现操作标true，其他保留设计false；错误沿用ErrorResponse，不返回输入、SQL原文、模型输出、凭据或堆栈。

## 4A-2 生成任务与原子阵容

TaskSupervisor归应用lifespan所有；注册表按operation_id去重，全局Semaphore限制ModelGateway调用。受理后立即202，领取任务时ACCEPTED→RUNNING；命令本身的受理响应被冻结，任务后续状态另查。网络等待在事务外；结果通过validate_result再次检查字段、基数、唯一身份/颜色、讨论与revision归属。

admit_generation在BEGIN IMMEDIATE中做状态/容量检查、operation及GENERATING事件。complete_generation以operation状态和当前discussion/revision为守卫，在一事务写完整roster/participants、roster.ready、READY、成功operation，并验证完整Snapshot；任何失败回滚。失败另事务写operation.failed+FAILED(roster)，保留topic；新幂等键可以重试，旧键仅重放原202。

生成错误：MODEL_TIMEOUT、MODEL_RESULT_INVALID、TASK_FAILED、DATABASE_UNAVAILABLE，公开说明固定脱敏。数据库完全不可写时无法再记录失败，日志仅固定恢复标记，后续启动恢复规则将在4A-3实现，不伪造成功。

容量：默认3个工作讨论，统计GENERATING/RUNNING/SUMMARIZING；模型并发4。READY不消耗生成容量，start重新检查容量。服务目前单worker，禁止同时用多个应用实例管理同一本地数据库。
