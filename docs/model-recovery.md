# 模型输出失败：诊断、纠正与主持有限恢复

更新：2026-10-11。此轮只做代码修正与可控 HTTP / FastAPI / SQLite 验证，付费调用 **0**。最新代码的真实页面复测由用户执行；此前真实质量记录保留，不代替此版本的真实验收。

## 原场核对与证据

议题：你认为AI的飞速发展，在未来几年是否会造成大规模失业？讨论 `1a44dc34-3cae-480f-9d65-700b8b23c98c`，运行 `dcc4efeb-e324-44ac-9256-6113f1f040d7`。原库只读导出见 [database.json](../data/quality/model-recovery/original/database.json)，收尾逐行不变检查见 [immutability.json](../data/quality/model-recovery/original/immutability.json)。

| 已确认事实 | 依据 |
|---|---|
| 14条正式消息，200个持久化事件，最终FAILED / MODEL_RESULT_INVALID | messages / runs / discussions / events |
| 第15次领取为主持linking，based_on_turn=14，最终CANCELLED，没有第15条消息 | turn_claims，角色597f36b0-3bae-5424-94ea-ba25da1e533a |
| 开始05:03:29.971203Z，失败05:08:26.178720Z，296.208秒 | runs时间差；冻结上限20条/600秒，stop_reason为空 |
| v5、边界12的提取FAILED，与整场失败同时间、同错误码 | 事件198观点失败、199操作失败、200讨论失败；v1–v4已成功 |
| fail_run连带将残留PENDING提取标FAILED，不能认定独立提取故障 | 任务监督器先取消提取，再执行失败事务 |

**无法确认**：原始非法响应、finish_reason、具体校验类别及实际尝试次数没有持久化，无法事后还原。现有代码默认两次不证明原场实际完成了两次。不得将句数、截断、JSON错误等猜测写为原场根因。

代码确认的通用缺口：原句子分隔把句末引号尾巴计成另一句，嵌入的单个引述问句也可能误分；旧重试不携带纠正反馈，非开场主持非法结果耗尽后直接失败。这些是可复现的实现问题，不证明原场恰好命中了句子误判。

## 普通启动下的安全诊断

新增前向迁移007，不改001–006。每次统一调用层尝试在独立短事务保存model_diagnostics，网络等待不持有事务。保存六类task、讨论/run/revision、actor及领取、cycle、message_position、call_id、attempt、可选失败stage、outcome、error_code、failure_type、duration_ms、occurred_at。

utterance的message_position为计划发言位置（已提交前缀+1）；其他任务为输入消息边界。演员姓名、Title、kind由同讨论阵容查询，不由模型提供。尝试序号从1开始，含首次，当前默认最多2次；多步提取/总结的一次尝试可能包含多个HTTP，诊断条数不是计费调用数。duration包含排队与校验，不是纯HTTP耗时。

| failure_type | 可确定分类 |
|---|---|
| EMPTY_CONTENT | 空最终content、空发言项 |
| OUTPUT_TRUNCATED / OUTPUT_REJECTED | 上游finish_reason=length / 非stop正常结束 |
| JSON_PARSE | 信封或最终content无法解析为JSON |
| FIELD_STRUCTURE | 字段、类型、枚举或信封结构不符合契约 |
| SENTENCE_COUNT / SENTENCE_BOUNDARY | 数组不为1–2项 / 单项包含多个独立句子 |
| SENTENCE_LENGTH / UTTERANCE_LENGTH | 单项超过200字 / 组装后超过400字 |
| RESULT_CONSTRAINT | 身份、归属、回应或来源等其余约束 |
| MODEL_ERROR / INTERNAL_ERROR | 安全服务错误码 / 未分类任务异常 |
| CANCELLED / BUDGET_EXHAUSTED | 取消 / 总任务或讨论预算用尽 |

outcome为SUCCEEDED、FAILED、CANCELLED、DEADLINE或HOST_SKIPPED。SUCCEEDED仅指模型结果通过本次校验，不保证随后业务事务提交成功；正式消息以snapshot/events为准。stage仅在上游失败可定位时保存single/draft/review/repair，其余为null。错误输入、完整响应、认证头、密钥和reasoning_content均不入日志、表或诊断响应。

查询普通后端：`GET /api/discussions/{id}/diagnostics?run_id={run}&limit=100`。默认最新100条，id倒序；有next_before时用`before={next_before}`取旧页。limit=1–100，before为正整数。不存在讨论404，外场run返回404/RUN_NOT_FOUND，非法UUID或范围422。记录重启保留；旧失败场不能凭空补出当时诊断，因此查询可能为空。此接口为本地只读诊断，无登录，与现有本地部署边界一致。

## 纠正重试及句子约束

ModelRequest新增内部attempt与validation_feedback，首次反馈为空。发生InvalidModelResult后，统一调用层在原有限预算内把安全类别绑定成具体约束，例如“每项仅一句”“仅合法闭合JSON”“每项最多200字”。保留相同角色、领取、目标和公开消息前缀；不把上次坏输出作为上下文，不附带Pydantic输入异常。HTTP适配器不重试，次数、队列、退避、取消、每HTTP120秒和讨论600秒规则保持。

UtteranceResult与正式Message共用句子边界规则：小数、常见缩写、句末闭引号不产生额外句子；内嵌单个引述问句作为外层句子的一部分，多个引述句仍逐句计数，连续“？！”只算一次结束。正文不截断、不改写成任意句数；数组1–2项，每项一句/≤200字，组装正文≤400字。表层规则不能完全替代语言理解，罕见缩写或复杂嵌套仍可能保守拒绝，记录具体类别便于进一步定位。

## 主持最小恢复

仅非开场linking/followup的**非法结果校验重试耗尽**可恢复，且已至少提交一名专家发言、当前run/领取/cycle/前缀仍有效、尚未达到结束条件。默认DISCUSSION_HOST_SKIP_LIMIT=2，为每run累计上限，0关闭，配置范围0–3；不增加模型重试次数或总时长。

恢复事务取消原SPEAKING领取、写HOST_SKIPPED诊断、主持转IDLE并发布对应角色事件；不生成主持正式消息、不推进消息编号、不伪造未问出的提问。下一周期先执行专家参与决策，清除未实际发出问题的指定回应目标。允许专家PASS；无人参与时依原机制实际追问，受同一累计上限控制。跳过不会向专家灌入坏回答。

认证/余额/服务错误、模型超时、开场、专家发言、主持控制本身、数据库错误和取消均不进入此恢复。第三次主持非法结果耗尽时明确FAILED，已提交消息与观点保留。迟到结果、重复领取及重复跳过仍被状态/cycle/前缀守卫拒绝；服务关闭取消并收集模型与SQLite任务。恢复写失败整体回滚，不误报跳过成功。

## 本轮实际检查

首次有效red：15 failed / 4 passed（7.29秒），覆盖边界误分、无安全失败类别、无反馈/查询与直接终止。前面的测试夹具导入/嵌套事件循环问题单独纠正，不算业务red。

- 新增功能最初19通过，再扩充取消、持久化/归属、重复/写入失败等场景到28项。
- 八文件受影响联合检查 **165 passed / 49.07秒**：model_recovery、discussion_engine、deepseek、synthesis_call_budget、provider_failure_persistence、database、contracts、artifacts。旧迁移版本断言及重试元数据断言同步；首次误写的测试分类已按夹具空数组修正为SENTENCE_COUNT。
- 最后补验JSON纠正、一次跳过后完成、认证不跳过，**31 passed / 12.34秒**（与上项重叠，不相加）。一次恢复夹具先把结束条数误写6；实际主持问后先给专家响应机会所以7，修正断言，无业务代码变更。
- 可控上游验证请求反馈和解析，真实FastAPI/临时SQLite验证完整正常/恢复/失败与重启查询；两场诊断无交叉。合法短句、多句拒绝、有限跳过、取消时吞取消的迟到返回、重复提交及恢复写失败均有检查。

现有Starlette/httpx弃用提示沿用，未升级依赖。未重跑未受影响SSE、布局、安装或完整替身E2E；本轮没有真实内容质量结论。配置/导出/样例/包核对结果见[进展](progress.md)。

进一步检查共享调用层的阵容/观点/总结/事务及配置、导出、样例，八文件93 passed /63.63秒；与上面结果有重叠。最后两个新增模块联合34 passed /13.11秒（此时引号正文组装补验尚未加入）。收尾发现已合法通过的引号结尾发言会被旧正文组装多补一个句号，先1 failed /0.97秒再修复：只判断闭引号前已有终止符，不改正文、不删内容。最终model_recovery（32项）、host_invitation（3项）、discussion_engine及turn_transactions联合 **69 passed /40.10秒**。这同样不能倒推为原场具体失败原因。

## 用户真实复测前的操作与观察

**需要重启后端**：结束本人启动的旧后端，再在继承PANEL_API_KEY的终端运行README中的真实模式命令。启动自动应用007，保留旧数据；同库只运行一个worker。前端业务代码未变，无须为此重启前端。原失败场仍可查看，不能用重复start续播，请通过页面创建新讨论。

真实复测检查：阵容确认后发言持续更新，主持串联/追问每次1–2句；专家回应仍对应真实已提交内容；若自然出现非法输出，诊断能看到task/actor/position/attempt/类别，第二次得到纠正约束；必要跳过后角色回到待机且专家参与继续，没有虚假的主持消息或重复编号。持续失败应有明确终态，不停顿循环；观点保留和正常结束/总结行为一并观察。可查询新讨论/new run的diagnostics并保留ID反馈。

真实场可能不触发非法输出，不触发只能说明这次正常路径成功；故障分支的依据仍是受控测试。最新修正版的内容质量、真实纠正效果与延迟尚待用户复测，不能由31/165项通过推断。候选ZIP随本轮代码更新，远程发布及邮件仍未执行。

## 主持邀请修正

用户追加发现主持按职业分工引导。检查发现intent Prompt中的“应说明”易被理解为必答，utterance的“邀请不同视角/交给专家”没有禁止分工；host_control的关注点也缺少明确非强制说明。程序当前不强制出场：context_request(intent)不继承主持任务/关注点，choose_speaker先排除PASS，只给实际回应最新问题的被点名者20分机会，不压过明显更高的回应价值，因此不改调度权重。

原场第1条实际写道：“请赵明远、周敏、吴澜和孙可分别从劳动市场、劳动权利、教育分化和企业转型说明判断依据，并回应‘大规模’指总量还是局部、持续多久。”这确认了开场分工现象；原文双引号见database.json。分工不是后端固定顺序指令，但容易影响后续模型参与内容，故从主持文字及意图上下文纠正。

修改位置：backend/prompts/utterance.md的opening/followup/linking；host_control.md的内容介入与非强制规则；intent.md的自主决策/PASS与质疑前提；deepseek_gateway.public_context仅对intent增加participation_rules，并不传主持public_focus为专家任务。保留职业、stance、公开messages、真实回应目标与来源校验，不新增强制参与状态。

新HTTPcontext检查先1 failed /2 passed（1.92秒），随后实现；主持相关五文件119 passed /10.85秒。实际FastAPI/SQLite控制场验证被点名专家PASS，其他专家REBUT回应主持问题；纯仲裁验证点名低价值参与仍可被高价值他人回应超过。初版测试把REBUT误写为正式message.kind=rebuttal，按现有statement契约修正，参与类型在领取字段核对，非业务错误。

以下为**写法示例，不是本轮真实模型输出**：

- 当前开场：“关于AI与就业，需要区分任务替代、岗位变化和就业总量变化。你认为AI的飞速发展，在未来几年是否会造成大规模失业？”
- 有人已提出“企业效率提高就会扩大招聘”之后追问：“刚才提到效率提高会扩大招聘，但这是否取决于需求也增长？林老师愿意澄清一下这个前提吗，其他人也可以提出不同判断。”

示例不预分嘉宾角度或安排顺序，点名只邀请说明前提，不规定答案；专家可质疑、补充或不参与。主持文本是否在真实输出中自然执行新规则仍待用户复测，不能由测试Prompt内容或模拟响应直接判定。

### 开场背景与原题补正（2026-10-11）

用户进一步要求给出简短背景并保留创建时的问题。此前示例把原题改成“哪些条件会……”子问题，确实缩小了提问范围；此处当前示例已修正，旧任务及提交历史保留。utterance Prompt规定最多一句中立背景，最后一项照引原题，不预设答案、造数字、分工排序或追加替代问题；host_control规定条件追问不能重新定义整场议题。

DeepSeek的opening请求增加opening_rules.original_question（直接来自request.topic）、background_max_sentences=1、question_must_be_last=true、assign_guest_directions=false，仅用于opening。不截取模型回答或在后端硬拼正文，既有1–2句/长度/身份/归属校验不变；原题非问句时原样呈现议题。暂未增加逐字匹配的业务提交校验，避免将最长500字议题与单句200字约束的冲突暗中变成输入限制；超长/多句原题与短句限制的兼容仍有限。真实模型是否忠实照引仍需实际输出复核。

两个不同原题的HTTPcontext用例先2 failed /1.19秒（missing opening_rules），实现后host_invitation/deepseek/deepseek_http联合80 passed /5.64秒。验证原题不改写地进入请求，受控响应背景+原题可解析；不把替身正文算真实效果。源代码/Prompt SHA和范围另存[opening-question.json](../data/quality/model-recovery/opening-question.json)，原verification.json仍对应上一修复版本。本轮付费调用0，旧场、调度/意图/诊断/预算及数据库不改；后端需重启加载新Prompt，候选包同步更新。
