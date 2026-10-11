# 测试说明与最终验证边界

更新：2026-10-11。核心业务实际按 red→green→重构推进，结果是分批运行记录，不把多个数字相加冒充一次全量测试。普通测试仅可控替身/本地 HTTP，不调用付费 DeepSeek。

## 本次交付检查

配置用例先 2 failed / 1 passed（0.44 秒），统一 Settings 与示例后通过；样例工具最初缺模块，加载器完成后导入 3 failed / 2 passed（0.53 秒），再实现同事务离线导入。新增配置/样例加受影响基础及契约共 **14 passed / 1.85 秒**。覆盖默认预算与环境优先级、日常 20 与验证 8 上限、重复导入、跨讨论引用、冲突不覆盖及整批写入失败回滚。警告是现有 Starlette TestClient/httpx 弃用提示，未更改锁定依赖。

独立新安装、数据库/样例重复操作、启动与浏览器代理检查结果见 [交付核对](delivery.md)，独立锁定安装/001–006/五份导入与重复/真实浏览器代理及阵容刷新全部通过，模型调用0。代码12ba05c，报告data/delivery/first-run.json。

## 沿用的已验证业务结果

| 范围 | 已有结果 | 依据及限制 |
|---|---|---|
| SSE 与前端业务、异常恢复 | 阶段5真实服务替身 E2E 13 passed | frontend/tests/live*.spec.ts；HTTP/SSE 经过 FastAPI/临时 SQLite，模型是可控替身 |
| 首页/创建/阵容/演播厅/总结、布局 | 四视口静态；真实增长 1366/2560/390 | docs/frontend-design.md 与 progress；此次配置变化不重新截图布局 |
| 真实适配、HTTP、共识连续性、多步预算 | 101 passed / 10.17 秒 | test_deepseek、test_deepseek_http、test_quality_continuity、test_synthesis_call_budget；不证明所有自然语言语义正确 |
| 调度/观点/总结与恢复 | 65 passed / 60.11 秒；006 后受影响 47 passed / 39.92 秒 | test_discussion_engine、test_insight_pipeline、test_summary_pipeline、test_summary_recovery；两批分别执行 |
| 供应商失败持久化及基础契约 | 46 passed / 7.85 秒 | test_provider_failure_persistence、test_database、foundation/contracts/artifacts，当时schema006；本轮007另验 |
| 最终真实模型完整浏览器流程 | 1 passed，观察 418.333 秒 | code0465f68；8正式发言、4成功观点批次、412字总结、turn_limit；62 HTTP / 200543 reported tokens |

最终真实场与逐条源消息判断见 [质量验收](quality-acceptance.md)，没有发生撤回或条件改变的场景；这些由之前独立定向验证和测试证明。原失败仍保留，不能把格式通过或定向生成替换原场内容验收。真实调用费用、真实并发、p95、跨平台未知。

## 复现入口

在项目根按 README 安装，再运行 `python -m pytest -q`；只复现本批用 `python -m pytest backend/tests/test_delivery_config.py backend/tests/test_final_samples.py backend/tests/test_foundation.py backend/tests/test_artifacts.py -q`。执行 `python -m scripts.export_contracts --check` 和 `python -m scripts.check_docs` 检查契约产物/文档，`npm --prefix frontend run build` 做类型及生产构建。

`npm --prefix frontend run test:live` 使用独立临时库和后端替身；`?mode=mock` 是另一种前端台本，不作业务验收。真实验证脚本是主动付费入口，不属于首次安装或常规测试步骤。

## 交付导出规则补验

导出边界新增用例先4 failed / 1 passed（0.20秒）：意外已跟踪的数据库WAL/SHM/journal与JKS也必须排除，不能只依赖.gitignore。补充拒绝规则后，导出安全、配置与样例13 passed / 0.59秒；不重跑未影响的引擎或E2E。当前包未发现真实运行文件，本次用例是防止导出规则将未来误跟踪文件带出。常见密钥模式与JSON隐藏推理字段负例通过，没有读取用户实际密钥。


## 交付后互动修正（2026-10-11）

新增test_interaction_revision从原d9efc8d6回放仲裁，真实FastAPI/SQLite验证主持追问、慢提取仍继续发言、两场合并边界/取消/关闭回收、失败无PENDING遗留；纯适配验证明确合并/不按相同来源合并、条件待澄清、主持身份/目标、显式候选编号、合并组不共享来源行、单项非法不丢独立合法项和一次有限收窄。

失败过程与结果分别记录quality-interaction。较大受影响回归163 passed/51.60秒（八文件、当时12新增用例），新增单项隔离/收窄后适配+连续性+本轮111 passed/5.60秒；不存在将两者相加作为一次全量的结论。当时14新增用例。前端类型/生产构建通过275ms，仅改最终观点核对状态及空分歧说明，不重跑四视口布局。当时全新真实浏览器验证待执行；实际执行结果见下方收尾，安装/静态布局/SSE协议未受影响。

本轮收尾：新增观点边界元数据用例先KeyError失败，个人早期摘录用例先DID NOT RAISE失败，再实现明确最新来源规则；当前16个新增互动用例。最新适配/连续性/互动/HTTP/制品联合116 passed / 8.48秒；此前较大163通过记录沿用，数字不相加。真实HTTP/SSE替身E2E补验创建完整流、总结失败恢复、提取失败保留三项3 passed /27.6秒；fixture followup改continue，异步提取的断言等待实际边界4，避免将发言推进等同观点已完成。真实DeepSeek浏览器1 passed /7.2分钟，干净23db026、11消息、host_end、运行中两次非空观点更新；内容残留另做实际提取/总结定向修正，原场不覆盖，最终范围见quality-interaction。未重跑未受影响安装、布局及SSE协议。

## 模型失败与非强制主持修正（当前代码的验证）

有效首批red为15 failed /4 passed（7.29秒），随后实现共享句子规则、安全错误分类、持久化诊断/查询、纠正重试与主持累计有限跳过。扩大到28项后，八文件受影响回归165 passed /49.07秒；最后新增JSON纠正、一次跳过完成、认证不跳过，model_recovery独立31 passed /12.34秒。迁移/重试元数据旧断言随新契约同步，夹具修正不冒称业务TDD。

主持邀请新增HTTPcontext用例先KeyError（1 failed /2 passed，1.92秒），实现非强制规则和隔离主持public_focus后，host_invitation、scheduling、interaction_revision、deepseek、deepseek_http联合119 passed /10.85秒。验证被点名者PASS、其他人质疑前提或更高价值回应被选、职业立场仍在上下文、身份/目标校验保持。三个新用例不是模型语义验收。

结果分批有重叠，不相加为全量。警告沿用Starlette/httpx弃用，未升级依赖。本轮没有付费调用、页面布局修改或完整浏览器重跑；历史SSE/布局/安装与未受影响E2E沿用。原场只读逐表14张/全部字段不变；具体已确认事实、未知原因、用户真实复测步骤见[模型恢复报告](model-recovery.md)。

复现：`python -m pytest backend/tests/test_model_recovery.py backend/tests/test_host_invitation.py -q`；八文件联合与主持相关五文件列表见报告及上文。新后端必须重启才能启用007与新Prompt。运行原FAILED讨论的重复start不会重放，真实复测应新建讨论。

共享调用层额外受影响回归：insight_pipeline、summary_pipeline、summary_recovery、roster_tasks、turn_transactions、delivery_config、delivery_archive、final_samples，93 passed /63.63秒。两个新增模块联合34 passed /13.11秒；收尾新增引号结尾正文不重复加句号用例先1 failed /0.97秒，再修复组装判断，新model_recovery增至32项。各批次有重叠，不能合计为全量。

最终引号组装修复后，仅两个新增模块/讨论引擎/发言事务再运行，69 passed /40.10秒（32+3项新增已含在内）。对应源码和Prompt SHA在data/quality/model-recovery/verification.json；包内manifest及Git历史标识提交版本。本轮真实调用数0，新的付费全程未执行。

历史PL-020（b53d42b）的开场背景/原题补正：两个不同原题HTTPcontext用例先2 failed /1.19秒，实现opening_rules与两份主持Prompt后，host_invitation、deepseek、deepseek_http联合80 passed /5.64秒；host_invitation目前5项。验证原题原样传递、背景+原题受控返回及原自主参与回归，不证明模型实际语义执行。代码/Prompt身份另存opening-question.json，不覆盖384dc6e对应verification.json；调用付费模型0，未重跑无关引擎/SSE/布局/安装。

PL-021开场隔离：先host_invitation 5 failed /4 passed（2.35秒），新规则缺失及mock固定框架；实现后`python -m pytest backend/tests/test_host_invitation.py backend/tests/test_deepseek.py backend/tests/test_deepseek_http.py -q`为84 passed /5.31秒。host_invitation现9项，验证四种原议题、独立开场Prompt、排除嘉宾立场/通用focus/专家分析示例、保留纠正反馈，后续追问仍有实际来源，以及专家自主PASS回归。替身实际HTTP不证明Prompt语义效果；付费调用0，原始质量记录保留。版本SHA另存opening-invitation.json；opening-question.json继续只对应b53d42b。未重跑未受影响布局/SSE/安装/完整E2E。

契约/制品受影响补验21 passed /1.52秒；export_contracts --check通过，未修改公开接口或机器契约。文档检查147需求/157验收/25文档通过（首次因新证据文件尚未生成而链接缺失，生成后通过，非业务TDD失败）。提交后交付包按manifest和当前opening-invitation.json逐文件核对，解包独立临时数据库/样例/普通FastAPI启动结果见outputs/delivery-check.json；使用现有锁定环境，不冒称重新安装依赖。

## PL-022：分歧与过程边界修复

新test_disagreement_live先10 failed/1 passed（3.12秒），覆盖旧证据字段不能区分支持关系、结束丢弃过程结果、无保护边界、总结误用旧批次；实现后11 passed/2.69秒。扩展奇数REBUT触发、同库双讨论与吞取消迟到拒绝、原任务1秒预算后最终成功，到14 passed/5.17秒；加入原文中的部分共识+相反判断同时保留，新模块共15项。普通补充/不同关注点/未回答及接受后的删除为受控审查结果分支，不能据此声称真实模型已经语义正确。

八文件：disagreement_live、insight_pipeline、interaction_revision、quality_continuity、summary_pipeline、summary_recovery、synthesis_call_budget、deepseek，174 passed/71.02秒。六文件：discussion_engine、model_recovery、provider_failure_persistence、host_invitation、contracts、artifacts，95 passed/46.31秒。最终新模块+delivery_archive 20 passed/5.70秒，范围重叠不合计全量。export_contracts与docs核对另列。生产业务没有测试控制入口。

前端npm run build（含类型检查）通过。`PLAYWRIGHT_CHANNEL=msedge npm run test:live -- --grep 'process disagreement publishes|failed extraction is streamed|real services create'`：3 passed/25.0秒，新断言通过实际前端/HTTP/FastAPI/临时SQLite/SSE看到零项旧范围提示、RUNNING中分歧发布、后续接受后最终共识；截图保留。最初浏览器缺Playwright自带Chromium，改用已安装Edge；一次新夹具host_control的public_focus空字符串违反既有ShortText导致失败，仅修正夹具，不算业务TDD。未升级依赖或付费重跑，旧安装、布局和未受影响协议/完整E2E结果沿用。
