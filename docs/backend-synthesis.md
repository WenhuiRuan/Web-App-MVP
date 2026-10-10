# 4C 观点提取、总结与恢复

## 开始时的缺口与实施顺序

2026-10-09，main=31e0380，工作区干净。已有Insight/InsightBatch/Summary、对应事件、SQLite表和Snapshot读取；缺少提取触发与领取、原子写入、版本守卫、总结任务与完成事务、summary-retry路由。ModelRequest没有消息边界、提取版本及已提取观点；结果校验只检查来源ID，不检查多位专家的证据。旧机器样例仅引用主持开场作为共识，需要更正。4B的run任务只推进到SUMMARIZING。

按三个小批TDD：4C-1观点规则、领取/事务、运行中更新和有限失败；4C-2独立总结预算与COMPLETED原子提交；4C-3失败/中断恢复、幂等并发重试与真实HTTP检查。每批保存实际red/green结果并提交。

## 实现默认值（用户授权的普通参数）

- 每两条已提交正式消息提取一次（2、4、6……），结束时对未提取的最后边界补一次；开场本身不生成共识。模型IO不占数据库事务。
- 提取每边界最多一个领取，版本按领取递增，整批替换，空结果也是有效批次；只允许最新领取提交，不允许旧边界结果覆盖。共识/分歧必须有至少两位不同专家的正式发言来源；这是证据底线，不证明语义上已达成共识，真实模型质量仍待验收。
- 提取有独立有限预算，失败保留已提交批次，以公开安全状态说明，下一新消息边界继续提取；不阻止后续讨论或总结。
- 总结只使用runs.summary_through_turn，携带最新合法观点。单独使用SUMMARY_MAX_SECONDS，不复用已到期的讨论deadline；总结不作为普通发言加入Transcript。
- 自动总结和重试均有持久化领取；只允许一个有效领取与任务，完成事务同时保存总结、summary.ready、run完成及COMPLETED事件。失败/中断保留消息、观点、阵容和边界；新幂等键可重试原run总结，不重放讨论。

## 验证记录

本批已完成对应后端验证，具体结果见[progress.md](progress.md)。SSE、前端业务接入和真实模型验证不在当前范围。

## 完成后的编排与恢复

DiscussionEngine提交每条正式消息后，在偶数边界同步等待SynthesisEngine.extract。提取等待有限且计入讨论真实时长；不足两位专家可以成功提交空批，最后失败的公开insight_status与上一成功insights并存。终止时Supervisor补最后未领取边界并调用summarize；提取失败不阻止总结。

每次总结捕获主持人、原run、冻结前缀及成功观点版本；Summary不追加到messages。初次自动领取无operation_id，手动summary-retry关联独立操作。FAILED/INTERRUPTED/summary接受新键，进行中的手动重试接受其他键加入，初次自动总结进行中与COMPLETED后新键409。相同键始终重放受理响应，不恢复中断任务；状态通过Snapshot/Operation查询。

摘要重试只激活原run的总结阶段；运行started_at/stop_reason/边界、消息、阵容、观点保持。数据库唯一PENDING领取与进程任务登记共同防重复。关闭统一取消/收集任务，排空数据库工作后标中断；即使模型吞取消后返回，closing/cancelling检查也拒绝提交。永久拒绝取消/永不返回的适配仍需未来进程隔离或供应商侧机制，当前适配须合作取消。

## 实际验证与限制

14项观点、19项总结、14项恢复共47新增均已通过。先运行新增及受影响回归168项（当时45新增），收尾两项格式负例先失败再修复后，相关55项回归通过。独立TCP报告work/synthesis-smoke-8xiz3ce0/report.json：两场各8条消息，非空观点在RUNNING的turn4/6/8更新；A总结两次非法失败，B正常完成，A并发重试合并一个任务；中断重启后新键总结成功且原消息/观点/边界不变。基础smoke_lifecycle也验证完成数据强制重启保留。

证据约束验证归属、边界与至少两位专家，并不能证明模型语义正确；默认Gateway仅生成工程模拟内容。自然语言校验拒绝JSON/代码块/空白/超长，不能自动证明总结忠实度。单进程/worker/database owner、持续不可写需下次可写启动恢复；前端仍模拟，SSE/真实服务/真实内容质量/五份样例/完整浏览器业务E2E未完成。
# 阶段6A验收收尾新增检查

以下仅新增及受影响的验证，已有SSE、静态布局与完整替身E2E沿用，不重复。常规pytest只用可控网关/HTTP，不调用付费模型；真实检查由用户授权后显式启用。

| 文件／范围 | 本批实际结果 | 证明边界 |
|---|---|---|
| test_quality_continuity.py | 23项含旧4/6、前批复核、污染候选收窄、撤回/条件、分类、去重与守卫 | 程序逻辑和模拟协议；语义由真实输出另核读 |
| test_synthesis_call_budget.py＋适配/连续性/实际HTTP | 101 passed，10.17秒；多步预算先1失败/1通过 | 单HTTP超时、有限任务截止及取消/重试；慢HTTP为真实loopback服务 |
| 引擎/观点/总结/恢复 | 65 passed，60.11秒 | 预算变化受影响的回归；不与重叠检查相加 |
| test_provider_failure_persistence.py＋数据库/基础/契约/制品 | 46 passed，7.85秒；15新测试先失败 | 七类供应商错误原子保存、保留已有观点、同run冻结边界重试、v5→6升级和约束 |
| 迁移后观点/总结/恢复 | 47 passed，39.92秒 | 事务写入故障回滚和恢复，其他旧规则不重复 |
| real-quality.spec.ts，真实DeepSeek | 1 passed约7分钟，418.333秒流程观察 | 实际前后端/新SQLite/HTTP/SSE、两次RUNNING非空观点及总结；不是所有语义保证 |

复现程序小批可在根目录运行 `.venv/Scripts/python.exe -m pytest backend/tests/test_provider_failure_persistence.py backend/tests/test_database.py -q`；模型适配预算组为test_deepseek.py、test_deepseek_http.py、test_quality_continuity.py、test_synthesis_call_budget.py。完整真实脚本会付费，入口/环境/预算见README，不在普通测试中隐式开启。真实证据、逐条来源判断、代码/Prompt版本与覆盖限制见[验收收尾记录](quality-acceptance.md)。
