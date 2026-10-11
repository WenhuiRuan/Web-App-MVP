# DeepSeek 模型适配（阶段6A）

采用已锁定 httpx 0.28.1 调用 Chat Completions，不增加 SDK。应用模型由后端独立配置，与 Codex 开发模型无关。mock 保留确定性替身；deepseek 配置齐全才建立真实网关。六任务沿用原引擎逐任务调用，不预生成整场台本。

当前配置（验收收尾）：六任务默认 thinking=enabled、reasoning_effort=low、max_tokens=16384；用户已允许全部任务思考。下文high/8192和短预算为历史验证配置。最终修正后的整场浏览器和本批核心内容复核通过；此前402失败独立保留，详见[本批质量记录](quality-acceptance.md)。

多步insights/summary网关显式声明multi_step_synthesis：MODEL_TIMEOUT_SECONDS用于每个HTTP请求的httpx超时，所有草稿、逐项复核、重试、排队共用INSIGHT_MAX_SECONDS或SUMMARY_MAX_SECONDS总截止时间。普通任务仍受原单次调用和讨论截止时间约束。统一调用层是唯一重试所有者，子请求不自行重试。有限过程覆盖为120/240/180/600秒（HTTP/观点/总结/讨论）；可控上游、引擎及一次新完整真实场通过，最后一批135.734秒仍成功。不是p95/并发保证；该验证阶段保留.env，阶段6B仅同步非敏感配置。

## 当前启动配置（2026-10-11）

最终默认与示例统一 thinking=enabled、effort=low、输出16384、HTTP120秒、提取240秒、总结180秒、讨论600秒、日常20条。项目.env的非敏感配置已同步，密钥引用保持原样；启动步骤以根README为准。最终代码0465f68完整真实流程及内容复核通过（418.333秒/62 HTTP/200543 tokens），验证单独设8条，实际turn_limit。原raw质量记录与失败保留，下面各阶段预算说明是历史决策，不作为当前启动指南。

## 官方接口依据（2026-10-10核对）

- [Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)：POST {MODEL_BASE_URL}/chat/completions，OpenAI兼容消息。
- [非思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)：顶层 thinking.type=disabled，只读取 message.content，不读取、持久化、展示或记录 reasoning_content。
- [JSON输出](https://api-docs.deepseek.com/guides/json_mode/)：response_format.type=json_object；Prompt 要求 JSON 并给出示例。空内容、截断及非法结构不能提交。
- [模型说明](https://api-docs.deepseek.com/quick_start/pricing/)：用户选择的 deepseek-flash 当前对应 DeepSeek-V4.1-Flash；实际响应只报告别名，不宣称精确权重版本已验证。
- [错误码](https://api-docs.deepseek.com/quick_start/error_codes/)：区分认证/余额/参数与限流/服务暂时失败。

## 配置与就绪

Settings 读取项目 .env，进程环境优先。MODEL_API_KEY=${PANEL_API_KEY} 使用 dotenv 展开；PANEL_API_KEY 必须被后端进程继承。机器级设置后已打开的终端可能尚未继承；重新打开终端，或仅将这个已授权变量导入后端启动进程。不打印密钥、不改写密钥引用、不读取 Codex 凭据。

必填 MODEL_BASE_URL、MODEL_NAME、MODEL_API_KEY；缺失/未展开时 ready=503，只列变量名。地址只允许 HTTPS，测试可 loopback HTTP；拒绝 URL 用户信息/query/fragment，关闭重定向。未知 provider 报 MODEL_PROVIDER。ready 只证明配置和数据库就绪，不检查认证、余额或网络，不发起付费调用。

system 返回 phase=6/version=0.6.0、model_mode=mock/real/unavailable、model_provider、model_name、discussion_engine_available；无密钥或地址。顶部真实模式为“DeepSeek · deepseek-flash（真实服务）”。mode=mock 页面仍是前端台本，后端 mock 是工程替身。

## Prompt与上下文

[通用规则](../backend/prompts/common.md)及六个任务文件位于 backend/prompts/，按任务加载和版本审查；每次仅包含本场公开资料，没有共享聊天历史。messages同时携带后端绑定的speaker_name/title/kind，避免把角色slot当发言序号；修改Prompt后重启后端加载新版本。

| 任务 | 模型提供 | 后端绑定/校验 |
|---|---|---|
| roster | kind/name/title/stance | 主持人优先、UUID5(讨论,revision:slot)、归属与颜色；主持人唯一、专家数量、字段及姓名唯一 |
| intent | kind/target_turn/relevance/public_focus | turn映射本场message_id；禁止跨场、不存在、自回应、PASS带目标 |
| utterance | sentences | 携带参与类型/target_turn或host_task；1–2句，每句≤200字，总≤400字 |
| host_control | action/public_focus | 开场/追问/串联仍通过独立发言任务，end冻结边界 |
| insights | kind/content/source_turns/evidence(turn,quote) | 同run及边界映射；每source必须有同一专家消息中的逐字片段，来源/evidence一一对应，至少两位不同专家；后端生成版本化ID |
| summary | content | 解开JSON包装后提交自然语言；捕获同run冻结前缀和观点，拒绝JSON正文 |

供应商结构禁止额外字段（含identity/reasoning），结果再经原ModelResult契约。逐字片段校验仅证明引用存在，不证明命题被来源完全支持。片段只在适配校验使用，不存隐藏推理或增加业务消息字段。真实内容单独人工核对，见[首轮质量记录](quality-first-round.md)。SQLite事务守卫、正式消息及SSE机制不变。

## 重试与观测

全部任务由 DiscussionEngine.call_model 唯一重试，网关不自行重试。普通任务每次尝试一个HTTP请求；观点/总结每次尝试为draft→review两个请求，结构非法的draft直接失败，不进入review。MODEL_MAX_ATTEMPTS含首次默认2，故观点/总结最多4次HTTP请求，并共享原任务总预算。401/403→MODEL_AUTH_FAILED、402→MODEL_BALANCE_EXHAUSTED、400/422→MODEL_REQUEST_INVALID、404→MODEL_NOT_FOUND，不自动重试；429→MODEL_RATE_LIMITED、5xx→MODEL_SERVICE_UNAVAILABLE、网络→MODEL_CONNECTION_FAILED、超时→MODEL_TIMEOUT，可在剩余预算内重试。Retry-After数值最多5秒，缺省0.5秒；HTTP-date不解析，回退0.5秒。非法输出依原策略最多2次。

阵容总预算=单次超时×次数+5秒×重试间隔数，默认65秒。讨论300秒、单次IO30秒、提取10秒、总结60秒（独立），并发4；排队和退避计入预算。取消向下传播，监督器关闭后拒绝迟到结果，收集任务后关闭client。

网关最多2000条安全内存指标：任务、讨论/run、stage(single/draft/review)、HTTP状态、安全码、耗时、返回model别名、用量数字（prompt/completion/total/cache hit/miss）。不含Prompt、回答、reasoning、请求头或原始错误。无返回usage时为null，不能估算0。生产不公开指标接口、不写业务库；验证入口每次完成写入ignored work/安全JSONL，不再仅等待进程退出导出。返回model别名仅当匹配配置才记录，其他值unknown。非法格式/来源只记固定validation_issue代码，不记原始值。

## 验证入口

test_deepseek.py 使用HTTP MockTransport检查请求/解析/错误/有限重试/取消；test_deepseek_http.py 使用实际loopback HTTP上游、FastAPI任务及临时SQLite验证六任务闭环，与真实供应商结果分开。

主动真实验证：项目根启动 `.venv/Scripts/python.exe -m scripts.real_validation_server`；前端目录设置 PANEL_REAL_VALIDATION=1、PLAYWRIGHT_CHANNEL=msedge，执行 `npm exec playwright -- test --config=playwright.real.config.ts`。该入口会付费调用，不属于普通自动测试；前端不传入密钥。保持单进程、单worker、单数据库所有者。

### 上游观点JSON示例（不是业务API）

```json
{"items":[{"kind":"consensus","content":"两位专家支持有限试点。","source_turns":[2,4],"evidence":[{"turn":2,"quote":"我支持有限试点"},{"turn":4,"quote":"我同意有限试点"}]}]}
```

引用需在本次输入中逐字存在，示例不能直接用作实际共识；非法source/quote/非专家引用/来源不对应会失败。空items合法。角色、观点ID与业务事件结构不由供应商提供，前端HTTP/SSE契约保持原形。无usage/null/没有可用计数字段时指标usage=null，不因缺用量丢弃合法回答；错误类型的usage被视为非法信封。

## 续批：证据复核与自然语言组装

insights/summary/host_control上下文不传人设stance。insights上游messages只含专家正式发言（保留原turn，不重新编号）；内部ModelRequest仍校验冻结完整前缀，summary/主持保留主持消息。summary候选带index、原来源完整消息、作者与semantic_status，不把结构通过当作语义认证。

普通六任务和业务契约不变，只有DeepSeek观点/总结内部增加独立、无共享历史的review；Prompt为insights_review.md、summary_review.md，review不混用draft格式示例。草稿不落业务库、不发布事件，review失败不退回草稿。全部IO在事务外，统一最多两次完整尝试，排队/退避/所有子调用计入同一任务预算。总结每次draft+review共2 HTTP；观点每次draft+逐候选review（空候选仍一次空review），请求数随有限候选集合变化，不再称固定四次上限。仍只占监督器同一任务和并发槽，子调用顺序执行，不能绕过取消/总预算。

观点review逐候选返回index、source_turns、content、可重选的evidence和七个公开checks（作者、对象、范围、条件、明确立场、提案属性、not_superseded）。任一false删除；这些是模型判断，不能当作确定性语义证明。程序检查完整唯一index、来源只能缩小不新增、引文逐字存在、专家及run/边界；引用作者外的已知角色姓名不允许写入保留观点。常见带单位数量须在共识每段保留quote中出现，否则排除该项，不能让它连带丢失其他有效项；不默认将指标认同扩大为阈值认同。不换算两周/2周、不证明否定/指代，仍有假阴性。

总结review返回introduction、positions(speaker_slot/source_turns/content)、consensus_indices、disagreement_indices、pending。作者由后端绑定且来源必须都是该专家的消息；共识/分歧只能选择捕获InsightBatch中相应kind的index，后端原样组装已有观点，不能由总结另造共识。输出业务Summary仍是自然语言content，非原JSON，无数据库迁移/API schema变更。其他段落的语义仍需人工复核，选择器不能证明概述和待澄清段绝无错误。

最终协议：introduction至多180字，positions至多3项且content至多160字，必须是其实际作者来源消息的原文连续片段，后端以“姓名建议／观点”呈现。pending至多2项(turn/quote/issue)，逐字来源校验；issue仅UNANSWERED_QUESTION/UNVERIFIED_PROPOSAL/SCOPE_UNCLEAR/UNIT_OR_DIRECTION_UNCLEAR。问句必须有问号或明确疑问标记（是否、如何、由谁、哪张、还是等），普通陈述不能标追问；标记不证明问题仍未解决，仍需模型及人工核对。位置/待澄清相同或包含的引文去重。候选与review中的完全相同观点按kind/content/来源集合去重。概述、片段选择和分类仍有语义局限，不认证原话事实。无数据库迁移、前端字段或业务JSON正文变更。

## 验收收尾：前批复核而非机械保留

内部ModelRequest.insights现在亦可供insights任务使用：必须是较旧版本，来源属于同discussion/run且不超过前批和当前边界。领取任务时从SQLite注入最新成功批次；public_context给出previous_through_turn与原来源。复核候选合并本次草稿和前批，旧项未被重提也会被审核，但只能经本次全前缀not_superseded/明确支持等检查后提交。后续撤回、条件变化可删除或由新候选更新；不是旧结果并集。

观点最终采用逐项聚焦review：每次候选index=0，messages包含原来源及其作者在来源边界后的发言；其他作者的反对由全前缀草稿生成独立分歧候选，不能将第三方反对误作原支持者撤回。后续消息只核查变化，不得扩充source_turns。kind可在原来源上纠正consensus/disagreement误分类，依据不足仍删除。review_origin_index仅安全指标定位。最后统一重新绑定ID/来源，跨项去重；原始草稿或未审核旧项不提交。

总结必须覆盖捕获批次的全部观点index，避免现场有有效共识而正文说没有。若总结再次认为候选不可靠而遗漏，触发summary_insight_omission及原有限失败/重试，不发布不一致正文；需人工核对提取结果，不强制模型确认无依据观点。该约束会使错误或过时提取造成总结失败，属于拒绝不一致而非语义认证。

草稿按候选校验引文与身份，个别非法来源项剔除，其他有效项仍进入复核；全部非法且没有前批候选时任务失败。复核可以从同一来源重选连续引文以收窄最小交集；最终仍经原ModelResult/Snapshot跨字段验证，空结果允许。来源扩展/格式异常仍有限失败，不落未经校验的数据。任务预算默认15秒（原10秒在双调用+重试时耗尽），排队/两段IO/退避计入预算。真实.env不改写，原配置10秒者需在后端进程设置INSIGHT_MAX_SECONDS=15再启动，环境值优先；最终验证显式使用15秒，不宣称旧配置已自动变更。


## 思考模式（用户追加授权）

本次用户允许全部任务思考。后端MODEL_THINKING_MODE=enabled/disabled（默认enabled），MODEL_REASONING_EFFORT=low/high/max（当前默认low，初始high），MODEL_THINKING_MAX_TOKENS当前默认16384（初始8192），允许1024–32768。enabled时显式发送thinking.type、reasoning_effort及该输出上限，disabled保持原输出额度且不传effort。模拟网关不使用这些配置，前端仍准确标为真实DeepSeek服务，未声称展示思考。

参数依据[官方思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)及[Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)（2026-10-10核对）。不使用工具调用、不回传历史推理，仅从message.content选择最终回答；不会保存reasoning_content。JSON格式及业务校验、独立上下文、统一有限重试保持。

追加保守守卫：分歧证据须含明确反对/撤回等标记；含“或/还是”的选择证据不能直接支撑“同时/并行”采用。相同kind及逐字证据集合只保留一项，支持者姓名由实际来源补齐。这些通用词形约束可能漏掉隐含反对或同一段支持的多个命题，不是语义保证；最终仍须实际输出复核。


思考high实测长前缀草稿已正确提取4/6共同主张，但多段IO耗尽60秒；先1失败测试，再允许有限提取预算1–300秒，95相关检查通过（4.55秒）。真实后端进程使用IO90/提取180/总结120；对照low努力级别仍为enabled思考，用实际输出决定适用预算，不重复认证已通过的SSE/布局。用户.env保持原样。


新定位到通用漏提根因：真实draft/review均确认4/6共同指标，但“这是两人的共同建议”被数量守卫误认为执行人数，因原引文不含“两人”而删除。先1失败，再将明确共同支持人数与绑定作者数核对，其他执行人数/数值仍须各来源支持；96检查通过（4.42秒）。

真实thinking返回多次completion约8193且信封校验失败（原finish_reason值未保留），可能耗尽输出额度；先默认额度1失败，再16384配置实现，97检查通过（4.43秒）。f9141e2中间完整浏览器人为停止以应用新守卫，保留快照/截图/journal，不称业务失败或通过。最终完整场将在新clean revision运行，仍为enabled/low；此前high/60秒耗尽记录保留。


长前缀实测提示MODEL_TIMEOUT_SECONDS实际约束整个generate尝试（含草稿/逐项复核），不仅是单个HTTP IO；90秒可截断多候选。新的验证采用120/240/180/600秒（尝试/提取/总结/讨论），所有仍有限；不修改用户.env。enabled默认effort改low、输出16384，先默认断言失败后通过。

独立复核坏引文使整批成功候选重试/消失：先1失败，再逐项InvalidModelResult剔除，全部非法仍失败，服务/取消/总超时仍整体失败。98检查通过（4.49秒）。真实撤回复核曾截出未重新认可的旧子主张；Prompt要求整体撤回删除，仅最新明确认可子主张可收窄。原输出保留，定向补验及最终clean版本8条有限讨论待验证。8仅验证入口参数，生产默认20不变；实际结束原因将据数据库记录。

以上为开发中的历史结果；最终0465f68清洁版本已完整验证，8条/turn_limit、四批提取、412字总结，62真实HTTP/reported200543 tokens，逐条内容复核核心要求通过。实际观察418.333秒，最后提取135.734秒/每HTTP最大54.640秒，预算修正版成功。非穷举召回、原文精选表达和压力/真实并发未验收范围不变，证据见quality-acceptance.md；本批不继续样例或交付包。

## 当前失败诊断与引导规则

日常预算保持enabled/low/16384、HTTP120、观点240、总结180、讨论600秒/20条，不因输出错误增加额度。统一调用层在普通启动持久化尝试诊断，分为空内容/截断/JSON/字段/句数/长度及其他约束，非法结果下一次带具体安全output_correction；HTTP层仍不重试。007追加安全表，无原始响应/认证头/隐藏推理；历史非法输出无原因不倒推。非开场主持校验重试耗尽按DISCUSSION_HOST_SKIP_LIMIT最多2次累计跳过，专家重新自主参与，无虚假主持正文，认证/取消等不跳过。

主持开场不按嘉宾职业分工排序，followup/linking只围绕已出现主张邀请回应；intent上下文participation_rules允许PASS及质疑提问，职业/stance/公开消息保留，public_focus不作为主持交派任务。六任务划分、身份和来源绑定不改。只完成受控验证，本轮真实付费复测由用户执行；重启后端加载代码/Prompt及迁移，详见[模型恢复报告](model-recovery.md)。
