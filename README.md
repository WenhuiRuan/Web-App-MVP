# AI Panel Studio

本地多专家圆桌讨论应用。阶段5正在接通真实HTTP/SSE及浏览器E2E；默认页面使用FastAPI/SQLite持久化，从创建、生成阵容和确认启动自动推进到观点更新、总结或明确失败。运行模型仍为后端独立确定性ModelGateway，不代表真实模型分析。独立前端台本保留在`?mode=mock`。开发工具Codex与应用运行模型分开配置。

## 环境与安装

本机验证：Windows、Python 3.12.10（SQLite 3.49.1）、Node.js 24.18.0、npm 10.5.0、Microsoft Edge。Node 至少22.12，建议24；Python建议3.12，SQLite至少3.37（STRICT表）。Linux/macOS 尚未实机检查。

依赖锁：前端 package.json 使用精确版本，package-lock.json 锁定传递依赖；后端 requirements.in 记录直接依赖，requirements.lock 锁定已验证的完整版本。不要在常规安装时重新升级这些文件。安装需要网络；npm 包下载地址记录在锁文件中，当前使用本机可访问的 npmmirror，后端安装源沿用本机 pip 配置。

在本 README 所在的**项目根目录**打开 PowerShell：

```powershell
.\scripts\setup.ps1
```

脚本只在不存在时建立 `.venv`，按锁安装依赖，再执行幂等数据库迁移。npm 缓存使用前端 `.cache/npm`，不改全局设置。若系统禁止运行脚本，可按下面等价命令逐条操作，不必改变系统执行策略：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --cache-dir .cache/pip -r backend/requirements.lock
Push-Location frontend
npm ci --no-fund --no-audit
Pop-Location
.\.venv\Scripts\python.exe -m backend.app.database
```

## 配置

默认值已能运行，无需 Key。需要修改时可将 `.env.example` 复制为项目根 `.env`（若已有文件先审阅，不覆盖）；真实 `.env` 不提交。后端进程环境变量优先于 .env。前端不会读取根 .env，不提供配置查询接口。

| 变量 | 默认值 / 范围 | 作用 |
|---|---|---|
| BACKEND_HOST / BACKEND_PORT | 127.0.0.1 / 8000；端口1024–65535 | 本地服务地址，host限定loopback |
| DATABASE_PATH | local-data/panel.sqlite3 | 相对路径以项目根解析 |
| LOG_LEVEL | INFO；DEBUG/INFO/WARNING/ERROR | 日志级别；不打印请求体或密钥 |
| MODEL_PROVIDER | mock | 当前仅mock适配可用；其他值ready返回503 |
| MODEL_BASE_URL / MODEL_NAME / MODEL_API_KEY | 空 | 真实服务后续配置；Key仅后端读取，不进入响应/日志/数据库 |
| MODEL_TIMEOUT_SECONDS / MODEL_MAX_CONCURRENCY / MODEL_MAX_ATTEMPTS | 30 / 4 / 2 | 全部模型任务超时、全局并发和最多尝试次数（含首次，1–3）；run剩余时长优先 |
| DISCUSSION_MAX_ACTIVE / DISCUSSION_MAX_TURNS / DISCUSSION_MAX_SECONDS | 3 / 20 / 300 | 活动容量已执行：GENERATING/RUNNING/SUMMARIZING合计；发言/时长额度已执行；到期冻结实际消息边界并进入SUMMARIZING |
| SUMMARY_MAX_SECONDS / INSIGHT_MAX_SECONDS | 60 / 10 | 总结与每次提取的独立有限总预算，包含队列等待；均最多MODEL_MAX_ATTEMPTS次尝试 |

若修改后端端口，启动前端前设置进程变量 `$env:PANEL_BACKEND_ORIGIN='http://127.0.0.1:新端口'`；它只是 Vite 服务端代理目标，不是模型配置。不要把密钥放入任何 `PANEL_PUBLIC_*` 或 `VITE_*` 变量。

## 启动

独立前端模拟访问 `http://127.0.0.1:5173/?mode=mock`，只需运行 `scripts/start-frontend.ps1`。右上演示工具仅在此模式显示，记录保存在浏览器localStorage；默认业务模式的数据保存在后端SQLite，不读取前端台本。

体验真实业务流程时，在两个项目根PowerShell窗口分别执行：

```powershell
# 窗口 1：后端，启动时自动检查/应用迁移
.\scripts\start-backend.ps1
```

```powershell
# 窗口 2：前端
.\scripts\start-frontend.ps1
```

访问 [本地前端](http://127.0.0.1:5173) 新建讨论、确认阵容、观看实时发言及观点并查看总结；访问 [基础连接检查](http://127.0.0.1:5173/?view=system)。检查页显示“基础服务已连接 / 数据库已就绪 · 确定性模拟模式”代表前端通过代理访问了真实后端。按Ctrl+C停止对应进程；端口占用时明确失败，不偷偷切端口。后端[Swagger UI](http://127.0.0.1:8000/docs)提供基础接口和讨论HTTP/SSE接口，可直接试用。

其他系统的等价启动方式（未实机验证）：`python3 -m venv .venv`，用 `.venv/bin/python -m pip install -r backend/requirements.lock` 安装；用 `.venv/bin/python -m backend.app.server` 启动；前端目录执行 `npm ci` 和 `npm run dev`。

## 数据库初始化

```powershell
.\.venv\Scripts\python.exe -m backend.app.database
# 独立实验数据库，避免影响正常数据
.\.venv\Scripts\python.exe -m backend.app.database --path work/check.sqlite3
```

空库首次输出 `Migrations applied: [1, 2, 3, 4, 5]`，重复输出 `[]`，不会清空数据。迁移有校验和、版本顺序及事务回滚；已应用SQL不修改，新变更加新版本。没有自动降级/删除数据操作。不要把本地数据库或 WAL/SHM 文件放入提交或交付包。

## 实际可用接口与设计契约

| 接口 | 当前用途 |
|---|---|
| GET /api/health/live | 进程存活 |
| GET /api/health/ready | 迁移状态及当前模型适配是否可用 |
| GET /api/system | 安全的应用版本/阶段/模拟模式标识 |
| POST /api/discussions | 创建DRAFT，默认4名专家；必填UUID格式Idempotency-Key |
| GET /api/discussions | active/all过滤、稳定排序与游标分页 |
| GET /api/discussions/{id} | 一致性快照及事件高水位 |
| POST /api/discussions/{id}/roster-generation | 后台生成；202受理后通过快照或操作查询等待READY |
| POST /api/discussions/{id}/start | 带roster_revision确认；幂等建立唯一run及后台任务，自动发言/提取/总结至COMPLETED或明确失败 |
| POST /api/discussions/{id}/summary-retry | 总结失败/中断后重试同run边界；重复及并发不新增有效任务 |
| GET /api/discussions/{id}/events?after={seq} | 持久化有序SSE补发、15秒心跳、终态关闭；Last-Event-ID优先 |
| GET /api/discussions/{id}/operations/{operation_id} | 查询本讨论操作的处理状态和安全错误码 |

请求、响应与错误示例见[API契约](docs/api.md)。[目标OpenAPI](docs/contracts/openapi.json)用x-implemented区分可用接口；所有讨论接口含SSE与总结重试均已挂载。创建返回201 Snapshot，生成返回202 OperationAccepted，成功后Snapshot为READY；POST start提交当前roster_revision，返回202/run_id并自动推进。每2条正式消息更新观点，结束补尾，冻结边界后生成总结。轮询Snapshot可见insights、insight_status、summary与生命周期。所有命令需要UUID幂等键；网络重发原键，显式失败或中断后的重试使用新键。

服务为**单进程、单worker、单数据库所有者**。未完成任务在关闭/重启后标INTERRUPTED；roster阶段可以新键生成，summary阶段通过POST `/api/discussions/{id}/summary-retry`（无body或`{}`）新键重试原run与冻结边界。不会重放发言/生成阵容；同一键返回原202响应，当前状态读Snapshot/Operation。并发重试键合并有效任务。讨论阶段中断不自动续跑。数据库持续不可写时需恢复可写后的下次启动处理。详见[生命周期](docs/backend-lifecycle.md)、[调度](docs/backend-orchestration.md)和[观点/总结](docs/backend-synthesis.md)。

## 验证命令

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m scripts.export_contracts --check
.\.venv\Scripts\python.exe -m scripts.check_docs
.\.venv\Scripts\python.exe -m scripts.smoke_lifecycle
.\.venv\Scripts\python.exe -m scripts.smoke_synthesis
.\.venv\Scripts\python.exe -m pip check
Push-Location frontend
npm run build
# Windows 若已安装 Edge，可免下载浏览器：
$env:PLAYWRIGHT_CHANNEL='msedge'
npm run test:smoke
Pop-Location
```

无 Edge 时在 frontend 执行 `npm exec playwright install chromium`，并移除 `PLAYWRIGHT_CHANNEL` 环境变量后执行冒烟。Playwright 自动在18080/15173启动并关闭独立测试服务，测试库使用项目 work/；若端口占用请先结束占用者。foundation.spec.ts的两项检查贯穿真实浏览器→Vite代理→FastAPI基础接口/SQLite，并覆盖503；discussion.spec.ts使用前端模拟数据验证用户流程、故障恢复和四种尺寸，projection.spec.ts检查公开事件投影。**这些均不是完整业务后端E2E**。截图保存在work/stage3-screenshots；浏览器测试后可运行 `python -m scripts.validate_frontend_capture` 校验实际模拟快照与事件格式。

数据契约修改后运行 `python -m scripts.export_contracts` 再执行检查。JSON Schema验证形状，Pydantic另外验证跨字段归属、阵容基数/身份、句数、来源等；单独JSON Schema通过不代表全部业务规则成立。

smoke_lifecycle自行启动临时loopback后端、独立work数据库，验证两场各8条发言/观点/总结及强制重启后数据保留。smoke_synthesis用受控后端替身和真实TCP HTTP，验证双场失败隔离、并发总结重试、中断/重启及新键恢复；报告在work/*-smoke-*/report.json。4C新增及受影响pytest168项通过（当时45新增）；收尾再补2项格式负例，相关55项回归通过，新增总数47；未受影响42项纯规则沿用4B结果，未重复执行。本批没有布局/截图/前端构建检查，frontend/src及依赖锁未改，仅基础浏览器测试的系统能力断言同步为true，浏览器检查仍需后续阶段执行。

## 已完成、限制与后续

- 已完成：前端模拟闭环、工程基础、后端生命周期/阵容/唯一运行、自主调度/主持控制、观点来源与版本/原子事件、独立预算总结/COMPLETED及失败/中断幂等重试。
- 未实现：真实SSE订阅与恢复、前端业务API接入、真实模型适配与内容质量验收、五条最终质量样例。
- 单worker/本地使用，无登录权限与公网部署。确定性后端生成验证结构和任务行为，不代表真实模型内容质量、成本或时延。
- 限制：前端模拟数据不写SQLite，无跨标签页协作；浏览器存储不可用时仅保留在内存。模拟时钟、固定台本、故障按钮不证明专家自主调度或真实服务质量。
- 下一步：阶段5接入HTTP/SSE、同步公开投影及完整业务E2E；阶段6真实服务、内容质量及最终交付。

生产预览：项目根运行 `npm --prefix frontend run build`，再运行 `npm --prefix frontend run preview`，访问 http://127.0.0.1:4173。默认前端模拟无需后端；Ctrl+C停止。页面设计及组件边界见 [前端设计](docs/frontend-design.md)。

设计索引：[需求](docs/requirements.md)、[架构](docs/architecture.md)、[数据模型](docs/data-model.md)、[API](docs/api.md)、[验收](docs/acceptance.md)、[决策](docs/decisions.md)、[进展](docs/progress.md)、[Prompt](docs/prompt-log.md)。
