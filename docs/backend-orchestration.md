# 阶段4B：自主调度与主持控制

2026-10-09。自动讨论推进至SUMMARIZING，观点提取、最终总结、SSE与前端业务适配留后续。后端使用独立ModelGateway，前端仍播放阶段3模拟台本。

## 模块与运行任务

discussion_api→TaskSupervisor.start→原start事务→唯一run任务。注册表run_tasks和scheduled_runs按run_id去重；重复命令只重放，终态不重新调度。应用关闭统一取消/收集受理、嘉宾与讨论任务，等待SQLite线程，再恢复残余工作。

DiscussionEngine只编排模型调用和领域决策；scheduling为纯函数；RunRepository复用DiscussionRepository的事务/快照/事件设施。SQLite事务内不执行模型IO。单应用所有者/单worker约束沿用4A；重启不自动续跑旧run。

## 一个运行的流程

1. begin_cycle检查RUNNING/ACTIVE、额度、当前run，递增cycle并读取同事务Snapshot。首次为主持开场，不收集专家意图。
2. 已有发言后，专家变PREPARING（公开关注点“正在评估是否参与”）；主持控制以完整公开Transcript决定followup/linking/end。
3. end立即取消领取、回IDLE、冻结消息边界并进入SUMMARIZING。其他决策下并发获取专家意图，所有调用受全局Semaphore和剩余运行预算约束。
4. 意图结果校验参与者、角色、target、scope与cycle；仅保存结构化意图及public_focus，专家回IDLE。部分专家评估失败会跳过，并公开固定不可参与状态；全部评估失败则本场FAILED/discussion。
5. 纯调度选人；无合格候选由主持followup。主持linking在上一条为专家发言时插入，避免连续串联挤掉所有专家。每次发言后重新评估，不按阵容固定轮流。
6. prepare_turn建立本轮唯一领取记录与PREPARING事件；mark_speaking单独事务标SPEAKING；模型生成完整短发言后，commit_turn同事务写message、turn.committed、IDLE与领取COMMITTED。
7. 次数/时长在开始、领取、提交处再检查；最后一条达到次数额度时，同提交事务冻结summary_through_turn并进入SUMMARIZING。处于SUMMARIZING后不会调用模型生成新发言。

## 仲裁规则与默认值

分数=模型relevance + 类型加权（REBUT20/SUPPLEMENT12/INTERRUPT8/REQUEST0）+回应新近性（最多5）−最近3条消息中每次占用25。立即上一发言者不得连续发言；其余同分用UUID稳定裁决。无候选返回主持追问。它是可解释的实现默认值，不是附件规定的唯一算法；相关性及输入变化会改变选择，近期发言会降低优先级。

PASS不发言且不可带target；SUPPLEMENT/REBUT必须引用本场当前run的既有消息；所有target不得自回应。REQUEST/INTERRUPT可无target。参与意图不是Transcript，不公开内部申请队列或隐藏推理。

默认MODEL_MAX_ATTEMPTS=2（含首次，允许1–3）；timeout30秒/concurrency4；run固定20条/300秒。重试复用同一请求和领取记录，成功只提交一次；无自动SQLite写入重试。模型/队列等待都计入run预算，区分模型调用超时与运行预算到期；后者进入SUMMARIZING，不记为模型失败。真实适配须响应取消；无法保证无期限吞掉取消的第三方代码能及时停止。

## 事务、回调及错误

002迁移新增run.cycle/stop_reason/error_code、discussion.failure_code、turn_claims；001保持不变。turn_claims复合FK限定run/阵容/角色/目标，部分唯一索引禁止同run多个待提交领取。message_id使用claim_id；消息turn_no连续且唯一。

每个写入验证当前RUNNING、ACTIVE、discussion/run/revision/cycle和base message count；迟到、旧轮次、已提交或中断run返回不接受。重复mark_speaking/commit不新增事件。非法输出不写消息；写入失败回滚整条消息及状态/事件，已提交内容不变。异常后另事务取消待领取、回IDLE、run FAILED、discussion FAILED/discussion，写固定错误事件与failure_code。

错误码MODEL_TIMEOUT/MODEL_RESULT_INVALID/TASK_FAILED/DATABASE_UNAVAILABLE；不写原模型输出、供应商异常或隐藏推理。失败事件关联最初start操作以定位run，start操作仍SUCCEEDED（命令已经建立run），实时失败读discussion.failure_code。数据库持续不可写时只记录固定恢复标记，下一次可写启动标INTERRUPTED。

## 测试与限制

test_scheduling：模型任务身份、参与类型/target、仲裁、占用和额度纯规则。test_turn_transactions：真实SQLite领取/意图/消息、角色事件、重复/迟到、原子回滚及冻结。test_discussion_engine：真实FastAPI/SQLite与可控Gateway，自动开场、参与类型传递、追问/串联/结束、有限重试、单发言者、双场重叠、错误隔离、真实10秒运行预算与关闭。

scripts.smoke_lifecycle以独立Uvicorn进程和真实HTTP跑两场后端确定性讨论，各8条正式消息进入SUMMARIZING；强制重启仍保留16条消息及阵容，待总结阶段标INTERRUPTED/summary。这证明自动任务、存储和接口可运行，不证明真实模型的专家质量或前端业务联调。最终命令结果见progress。
