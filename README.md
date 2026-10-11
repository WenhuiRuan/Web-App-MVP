# AI Panel Studio

阮文慧 · 2026年10月11日

源码仓库：[WenhuiRuan/Web-App-MVP](https://github.com/WenhuiRuan/Web-App-MVP)

这是一个本地运行的多专家圆桌讨论应用。用户输入议题和专家人数，确认生成的主持人与嘉宾后进入演播厅。专家根据公开发言决定是否参与、补充或反驳，主持人负责开场、追问、串联和结束。页面实时显示角色状态、正式发言、共识与分歧，最后生成自然语言总结。

## 项目文件

| 材料 | 位置 |
|---|---|
| 项目源码、依赖锁定、运行及配置说明 | [运行与配置](docs/running.md) |
| SQLite 初始化入口 | `backend/app/database.py` |
| 数据库迁移脚本 | `db/migrations/`，共七个迁移 |
| 五份预设议题及对应嘉宾 | [样例说明](data/samples/final/README.md)、`rosters.json` |
| 产品需求 | [需求文档](docs/requirements.md) |
| 架构与技术决策 | [架构说明](docs/architecture.md)、[技术决策](docs/decisions.md) |
| 数据模型与 Mermaid ER 图 | [数据模型](docs/data-model.md) |
| API、错误格式和 SSE 事件示例 | [API 文档](docs/api.md)、`docs/contracts/` |
| 前端设计与状态流转 | [页面设计](docs/frontend-design.md) |
| 测试代码 | `backend/tests/`、`frontend/tests/` |
| 测试结果与需求验收 | [测试说明](docs/testing.md)、[验收记录](docs/acceptance.md) |
| 六段核心开发 Prompt 及对应说明 | [开发指令记录](docs/core-prompts.md) |
| 开发流程、实际问题与处理方法 | [工作流说明](docs/workflow.md) |
| 分阶段提交历史 | [GitHub 提交记录](https://github.com/WenhuiRuan/Web-App-MVP/commits/main/) |

开发指令与工作流说明见上表。详细开发过程保存在 [开发日志](docs/prompt-log.md) 和 [进展记录](docs/progress.md)。

## 运行方法

已验证的本机环境为 Windows、Python 3.12 和 Node.js 24。在仓库根目录打开 PowerShell，安装依赖并初始化数据库：

```powershell
.\scripts\setup.ps1
```

随后分别在两个终端启动后端和前端：

```powershell
# 终端一
.\scripts\start-backend.ps1 -ModelMode mock
```

```powershell
# 终端二
.\scripts\start-frontend.ps1
```

打开 `http://127.0.0.1:5173/`。模拟模式使用确定性模型替身，可以检查完整前后端流程。数据库初始化只创建结构和应用缺失迁移，不清空现有讨论。

使用真实模型时，按 [运行与配置](docs/running.md#两种运行模型模式) 将 `.env.example` 复制为 `.env`，配置 DeepSeek 官方 API 和 `deepseek-flash`，并在后端启动环境提供 `PANEL_API_KEY`。示例文件不含实际密钥，真实 `.env` 和本机运行数据库不提交到仓库。详细配置、端口修改及脚本的等价命令见 [运行与配置](docs/running.md)。

五份样例包含四天工作制、写作课堂使用 AI、自行车道与停车位、员工 AI 对话留存、图书馆晚间服务。每份包含一位主持人、四位专家及姓名、职业、立场和颜色。四份为预设编写，一份复用真实生成的阵容；导入后为待确认状态，确认后才启动讨论。

## 验证情况

应用实现对应 `ae2f54a2b6bca79866d08034ddb5c0c8789f23c1`，各阶段开发与文档整理记录可在仓库提交历史中查看。

已有真实完整讨论记录，包括图书馆议题的8条发言，以及互动修正后另一场讨论的11条发言、运行中观点更新和主持人自主结束。相关消息、观点及总结复核见项目内的质量报告。

最新分歧修复新增15项验证；受影响回归分别通过174项和95项检查，三项真实 HTTP/SSE 的替身浏览器测试通过，前端类型检查和生产构建通过。七个迁移、重复初始化、五份样例首次及重复导入、源码解压后的后端启动也已有验证记录。不同批次存在重叠，具体范围分别记录在测试文档中。

最新诊断、开场和分歧修复尚未重新做整场真实模型验证。模型仍可能漏提观点、误判语义或出现相似表达；较慢的过程提取可能在发言结束后、总结前发布。本地服务采用单进程运行，大量真实并发和跨平台运行尚未验证；中断的讨论不会自动续播，已保存内容仍可查看。

## 后续改进

后续优先改善观点语义复核和模型响应时间，补充更多真实议题及并发场景。已验证范围和当前限制见 [测试说明](docs/testing.md)、[互动质量报告](docs/quality-interaction.md) 和 [分歧过程报告](docs/quality-disagreement.md)。
