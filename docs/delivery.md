# 本地交付核对与提交准备

更新：2026-10-11，第六阶段第二批完成后互动修正。任务边界是本地材料及已授权真实质量复核，不自动发布远程仓库或发送邮件。首次使用入口是根 README，历史细节在 progress、prompt-log 和质量记录，不要求收件人拼接历史启动步骤。

## 材料索引

| 题目材料 | 当前成果 |
|---|---|
| 完整源码与依赖锁 | backend、frontend、backend/requirements.lock、frontend/package-lock.json |
| 初始化及迁移 | python -m backend.app.database，db/migrations/001–007 |
| 至少五份不同议题和对应阵容 | data/samples/final/rosters.json 与 README，离线校验/导入脚本 |
| PRD、架构、ER、API、测试 | requirements、architecture、data-model（Mermaid ER）、api、testing及实际 tests |
| 运行/环境/选型/主要API/完成/后续 | 根 README |
| 至少五段核心开发 Prompt | core-prompts.md，六段完整实际任务原文覆盖SDD/DDD/TDD/E2E，不含授权/充值 |
| 1–1.5页工作流 | workflow.md 源文及 workflow.pdf，一页PDF，三项实际问题/修正 |
| 演进记录 | docs/progress.md、prompt-log.md、独立 main Git历史；ZIP附 Git日志，真实仓库仍在本地 |
| 本地 ZIP | outputs/ai-panel-studio-delivery.zip；同目录提供.zip.sha256 |

## 首次运行验证

已在work/first-install-20261011-015245/ai-panel-studio独立目录完成，未使用原项目venv/node_modules/数据库：

- setup.ps1建立全新Python3.12虚拟环境，按完整requirements.lock安装成功，pip check无缺失；npm ci锁安装29包（8秒），版本未升级。
- 首次迁移[1,2,3,4,5,6]；重复[]。样例校验5份，离线导入5/0，再次0/5；5场READY、0 run、15初始事件，FK无违例、integrity ok。
- 原样运行后端脚本mock/18100，前端脚本15180；Edge通过Vite代理取得ready/system/list/snapshot，首页已保存的讨论5份，阵容5人，刷新恢复，页面异常0。只有GET请求，模型调用0。
- TypeScript及生产构建通过（479ms）；包内契约与文档检查通过。初次发现Port参数位置/遗漏直接证据链接，两项修正后只补验相关启动与包内文档，锁定依赖保持不变。

报告 [first-run.json](../data/delivery/first-run.json)，截图 [安全证据索引](screenshots/README.md)。业务/SSE/布局及完整替身E2E沿用[测试说明](testing.md)，本次没有重跑完整讨论。

完整安装/启动证据执行源版本为12ba05c，首次依赖安装5195c0f。该证据来自当时001–006版本；互动修正未改锁/安装脚本，本轮失败修复另新增007迁移，相关数据库检查单独记录。首次安装不冒称在本轮重新执行；最新清单逐文件SHA256核对，历史完整新场另见quality-interaction，最新真实修复验收仍待用户。

## 打包边界

ZIP 包含源码、锁、迁移、最终样例、文档及必要安全质量证据，不含 .git 对象库、真实 .env、密钥、node_modules、虚拟环境、缓存、日志或运行数据库。全部源码测试保留，包括共识连续性实际快照回归fixture；临时调试目录和冗余旧请求转储不全量装包。原始失败/公开来源可在本地原仓库及历史追溯，选取的完整真实最终快照和版本/内容判断随包保留；包内清单列出实际路径、SHA256和遗漏规则。

原质量文档中的历史路径有些只在原仓库中，ZIP不是历史调试材料全集。未发布的远程链接不填假地址。构建工具仅读取明确列出的项目文件，不读取 PANEL_API_KEY 或展开 .env；安全核对验证排除路径、格式和明显密钥文本，并沿用既有真实密钥哨兵证据，不宣称本批读取密钥逐字扫描。

## 仍待完成的外部提交

1. 用户选择 GitHub 或 Gitee，创建远程并发布当前 main，检查公开或收件人可访问性；目前 git remote 为空，无可提供的仓库链接。
2. 填写真实姓名、联系方式；邮件主题为“【远程作业提交】姓名”。收件地址按题目为 xulei@wisquest.com，发送前由用户复核。
3. 核对题目“收到后72小时”的实际起算时刻，当前未知，不能断言截止时间或仍在期限内。
4. 附本地 ZIP、核心 Prompt 文档、工作流 PDF/源文和仓库链接，确认大小与访问权限后由用户发送；本批没有发送邮件。

建议邮件正文：您好，我是【姓名】。附件为 AI Panel Studio 本地交付包、核心开发 Prompt 与工作流说明。仓库：【GitHub/Gitee实际链接】。安装与验证入口见 README，已验证范围与限制见测试说明及验收矩阵。请查收。


## 本轮互动修正后的包核对

最新ZIP以本轮全部修改提交后的clean HEAD生成，含本轮原场只读证据、新完整真实场与之后定向修正、实际Prompt副本/SHA、TDD及浏览器测试。outputs/delivery-check.json和.zip.sha256给出实际revision/逐文件数量/校验结果；包内delivery/manifest.json与git-history.txt可查。完整场执行代码23db026，最终归纳/总结修改有独立实际验证，不将原截图描述为修改后结果。旧安装/迁移/锁依赖记录沿用，未重新安装或跑五场模型。ZIP再解压到独立目录做清单、当前契约、样例和文档核对，不影响原数据库/服务。

## 当前模型恢复与主持邀请候选包

本轮追加安全诊断007、严格句子/纠正重试、主持有限恢复与开放邀请，详细范围见[修复报告](model-recovery.md)。包内新增原1a44失败的只读公开证据、逐字段不变检查及可控验证记录，历史样例/成功与失败证据保留。五份阵容无需重新生成，当前契约离线检查通过；锁依赖/安装/布局/SSE未变，旧结果沿用，新增迁移与受影响逻辑分别补验。

outputs/ai-panel-studio-delivery.zip按修复提交的clean HEAD重建，manifest列出实际revision与文件SHA；outputs/delivery-check.json记录候选核对。**本轮未调用付费模型，不能把候选包描述为最新真实全程验收已通过**。用户应先重启后端（自动007）、新建场次验证主持开放引导及实际纠正/恢复行为，再决定正式外部提交。旧FAILED讨论不改写或续播，远程/邮件未执行。
