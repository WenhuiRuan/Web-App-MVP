# 提交说明

阮文慧 · 2026年10月11日

源码仓库：[WenhuiRuan/Web-App-MVP](https://github.com/WenhuiRuan/Web-App-MVP)

应用代码对应 `ae2f54a2b6bca79866d08034ddb5c0c8789f23c1`。README 与邮件附件采用一致的项目介绍，详细启动与配置说明位于 [运行与配置](running.md)。应用实现和测试代码保持原版本。

## 材料索引

| 材料 | 位置 |
|---|---|
| 完整源码、锁定依赖、环境与运行说明 | [README](../README.md)、[运行与配置](running.md)、backend、frontend |
| SQLite 初始化与迁移 | backend/app/database.py、db/migrations/001–007 |
| 五份议题与对应嘉宾阵容 | [样例说明](../data/samples/final/README.md)、rosters.json |
| 产品需求与架构 | [需求](requirements.md)、[架构](architecture.md)、[技术决策](decisions.md) |
| ER 图与数据模型 | [数据模型](data-model.md) |
| API、错误格式与 SSE 事件 | [API](api.md)、docs/contracts |
| 页面设计 | [前端设计](frontend-design.md) |
| 测试代码、结果与验收 | backend/tests、frontend/tests、[测试说明](testing.md)、[验收记录](acceptance.md) |
| 六段核心开发 Prompt | [开发指令记录](core-prompts.md) |
| 一页开发流程、实际问题与处理方法 | [工作流说明](workflow.md) |
| 分阶段提交与完整开发记录 | GitHub 提交历史、[进展](progress.md)、[开发日志](prompt-log.md) |

邮件附件为 `阮文慧_Web-App-MVP.zip`，包含上述材料及完整提交历史的离线 Git bundle。正式过程说明采用 Markdown；项目内的阶段记录保留原始内容。

## 已有验证

首次独立安装记录来自12ba05c及其依赖安装批次，使用全新虚拟环境和数据库，锁定依赖安装、当时001–006迁移、重复初始化、五份样例导入及前后端启动通过。后续新增007迁移，当前七个迁移和重复初始化另有检查记录。详情见[首次运行记录](../data/delivery/first-run.json)及[测试说明](testing.md)。

真实模型完整流程包括图书馆议题的8条发言，以及互动修正后另一场讨论的11条发言、运行中观点更新和主持人自主结束。完整场与后续定向修正分别记录在[真实质量报告](quality-acceptance.md)及[互动质量报告](quality-interaction.md)。

最新分歧修复新增15项验证，受影响回归分别通过174项和95项检查，三项真实 HTTP/SSE 的替身浏览器测试通过，前端类型及生产构建通过。批次计数存在重叠，分别保留执行范围。诊断和恢复见[模型恢复报告](model-recovery.md)，分歧证据与过程发布见[分歧过程报告](quality-disagreement.md)。

最新诊断、开场和分歧修复尚未重新做整场真实模型验证。模型语义判断、响应时间、大量真实并发与跨平台运行仍有未验证范围，具体限制见 README 和上述报告。

## 附件范围

附件保留源码、锁、迁移、样例、测试和选取的公开质量证据，不包含真实环境文件、模型密钥、依赖目录、虚拟环境、缓存、日志或本机运行数据库。文件校验见附件的 SHA256SUMS.txt。早期失败与实际模型输出保留原版本，历史测试和内容复核不改写为本次重新执行。

## 邮件

收件人：`xulei@wisquest.com`

主题：`【远程作业提交】阮文慧`

正文提供项目仓库链接，附上 ZIP。发送前核对附件、仓库访问和收到题目后72小时的实际截止时间。
