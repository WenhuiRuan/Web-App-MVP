# AI Panel Studio

本地多专家圆桌讨论应用。阶段5已接通真实HTTP/SSE及浏览器E2E；默认页面使用FastAPI/SQLite持久化，从创建、生成阵容和确认启动自动推进到观点更新、总结或明确失败。阶段6A已接入后端独立DeepSeek ModelGateway，MODEL_PROVIDER=mock保留工程替身；真实内容首轮验证另行记录。独立前端台本保留在`?mode=mock`。开发工具Codex与应用运行模型分开配置。

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

默认值已能运行，无需 Key。需要修改时可将 `.env.example` 复制为项目根 `.env`（若已有文件先审阅，不覆盖）；真实 `.env` 不提交。后端进程环境变量优先于 .env。前端不会读取根 .env，不提供完整配置或密钥查询接口。

| 变量 | 默认值 / 范围 | 作用 |
|---|---|---|
| BACKEND_HOST / BACKEND_PORT | 127.0.0.1 / 8000；端口1024–65535 | 本地服务地址，host限定loopback |
| DATABASE_PATH | local-data/panel.sqlite3 | 相对路径以项目根解析 |
| LOG_LEVEL | INFO；DEBUG/INFO/WARNING/ERROR | 日志级别；不打印请求体或密钥 |
| MODEL_PROVIDER | mock | mock或deepseek；配置缺失/不支持时ready返回503 |
| MODEL_BASE_URL / MODEL_NAME / MODEL_API_KEY | 空 | DeepSeek由后端独立配置；Key仅后端读取，不进入响应/日志/数据库 |
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

访问 [本地前端](http://127.0.0.1:5173) 新建讨论、确认阵容、观看实时发言及观点并查看总结；访问 [基础连接检查](http://127.0.0.1:5173/?view=system)。检查页显示“基础服务已连接 / 数据库已就绪及当前实际模型模式”代表前端通过代理访问了真实后端。按Ctrl+C停止对应进程；端口占用时明确失败，不偷偷切端口。后端[Swagger UI](http://127.0.0.1:8000/docs)提供基础接口和讨论HTTP/SSE接口，可直接试用。

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
| GET /api/system | 安全的应用版本/阶段/模型模式标识 |
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
# 真实业务：自动启动临时库、可控后端替身和Vite，HTTP/SSE实际走服务
npm run test:live
Pop-Location
```

无Edge时可在frontend执行 `npm exec playwright install chromium`，移除PLAYWRIGHT_CHANNEL（其他浏览器尚未实机验收）。默认test:smoke在18080/15173运行基础/独立前端mock/投影与客户端检查；新test:live在18081/15174运行真实业务E2E，临时数据库每次新建work/stage5-e2e-*，不接触正常数据。端口被占时明确失败，不终止用户进程。test:live使用backend/tests/e2e_server中的可控ModelGateway，测试故障接口仅此专用服务拥有，禁止把测试服务当作日常服务。服务由Playwright统一启动和关闭。

实际业务E2E包含创建/阵容/确认/两次运行中观点/总结、首页加入/刷新、断网继续推进/恢复、gap/重复帧/提前关闭、总结重试、观点失败保留、双场隔离、三个尺寸增长滚动及密钥哨兵。截图work/stage5-screenshots，机器报告work/stage5-e2e-report.json，临时库信息work/stage5-e2e-last.json。静态1920等既有布局结果沿用阶段3。独立台本格式检查仍可运行 `python -m scripts.validate_frontend_capture`。

数据契约修改后运行 `python -m scripts.export_contracts` 再执行检查。JSON Schema验证形状，Pydantic另外验证跨字段归属、阵容基数/身份、句数、来源等；单独JSON Schema通过不代表全部业务规则成立。

smoke_lifecycle/smoke_synthesis是阶段4真实TCP验证脚本，历史结果沿用。阶段5SSE新增及受影响检查74 passed，另外生命周期/任务/发言/总结/模拟样例受影响回归111 passed；开放SSE关闭真实TCP补测1 passed。以上是分别运行结果，不宣称单次全量。前端类型检查/生产构建通过，真实业务E2E13 passed；前端回归最后结果见progress。既有纯仲裁/生命周期规则与静态布局未重复运行。

## 已完成、限制与后续

- 已完成：前述后端规则与恢复、持久化SSE、默认前端业务闭环、替身下真实HTTP/SSE浏览器E2E；DeepSeek六任务适配、真实浏览器讨论与针对来源/条件/总结的质量修正和定向复核。
- 未完成：最终版本完整讨论的内容质量复核、五份最终质量样例、工作流说明与交付包。已有完整真实流程技术通过，原场语义问题保留；定向修正不等于全场语义验收通过。费用账单及真实并发/p95未知。
- 单worker/本地使用，无登录权限与公网部署。确定性后端生成验证结构和任务行为，不代表真实模型内容质量、成本或时延。
- 限制：前端模拟数据不写SQLite，无跨标签页协作；浏览器存储不可用时仅保留在内存。模拟时钟、固定台本、故障按钮不证明专家自主调度或真实服务质量。
- 下一步：本批先在余额恢复后补完最新修正版的完整真实验收；通过并经用户复核后，下一批再选至少五份高质量样例、编写工作流与打包。本批不自动开始下一批或远程交付。

生产预览：项目根运行 `npm --prefix frontend run build`，再运行 `npm --prefix frontend run preview`，访问 http://127.0.0.1:4173。默认业务模式须同时运行后端；独立前端演示添加?mode=mock。Ctrl+C停止，服务5秒宽限后取消开放流并清理任务。页面设计及组件边界见 [前端设计](docs/frontend-design.md)。

设计索引：[需求](docs/requirements.md)、[架构](docs/architecture.md)、[数据模型](docs/data-model.md)、[API](docs/api.md)、[验收](docs/acceptance.md)、[决策](docs/decisions.md)、[进展](docs/progress.md)、[Prompt](docs/prompt-log.md)。

## DeepSeek真实模式（阶段6A）

已有.env请保留。设MODEL_PROVIDER=deepseek、MODEL_BASE_URL=https://api.deepseek.com、MODEL_NAME=deepseek-flash、MODEL_API_KEY=${PANEL_API_KEY}；后端进程需继承PANEL_API_KEY，进程环境优先于.env。机器级变量已设置但老终端未继承时，可新开终端；必要时仅在启动后端的PowerShell中执行：

```powershell
if (-not $env:PANEL_API_KEY) {
  $env:PANEL_API_KEY = [Environment]::GetEnvironmentVariable('PANEL_API_KEY', 'Machine')
}
.\scripts\start-backend.ps1
```

不要输出该变量，也不要在前端窗口复制它。顶部显示“DeepSeek · deepseek-flash（真实服务）”；ready仅配置检查，首次创建阵容才会真实付费调用。六任务Prompt、官方文档、重试及安全边界见[模型适配](docs/model-provider.md)。内容质量与样例交付分开：本批1–2真实议题复核，下一批至少五份最终样例和交付包。

首轮两个真实议题、具体来源、修正与限制见[内容质量记录](docs/quality-first-round.md)，文本证据在data/quality/stage6a。来源与作者归属改进已定向复核，但不承诺所有共识都语义正确。修改Prompt后需重启后端；已保存讨论不会被自动重写。真实检查脚本是主动付费入口，常规pytest/Playwright不调用真实模型。检查结果与无法取得的整场用量分别记录。

本次续批见[质量修正与验收](docs/quality-revision.md)：69项适配/实际HTTP检查、68项受影响回归、类型/构建及1个真实完整浏览器用例通过；原场11条正式消息、6次观点更新，实际结束为host_end。人工发现的误判按原边界另行修正，没有覆盖旧记录。最终摘要采用自然语言概述和实际作者的原文精选，提案与条件不自由改写；严格提取仍可能漏掉有效交集。

仅在明确要重新进行付费验证时，后端专用终端运行 `python -m scripts.real_validation_server --label stage6a-corrected`（新临时SQLite，端口18082）；另一个不含密钥的前端终端设置PANEL_REAL_VALIDATION=1、PLAYWRIGHT_CHANNEL=msedge，在frontend运行 `npm exec playwright test -- --config=playwright.corrected.config.ts`。已有报告存在时测试拒绝覆盖，先保留或另存旧证据。定向任务脚本 `python -m scripts.review_quality_cases --help` 可查看选项，它也调用真实服务。日常使用仍按启动脚本运行；应用Prompt缓存需重启后端才能更新。

## 本次验收收尾状态（2026-10-11）

详情见[共识连续性、总结分类及验收证据](docs/quality-acceptance.md)。用户已允许全部任务思考，当前后端默认enabled/low/16384；仍只读取最终content。前批观点重新复核、共同支持人数守卫、建议分类和撤回/条件变化已经定向验证；不以格式成功证明语义正确。

最新真实场8条发言、turn_limit结束，运行中有观点更新，但后续提取及总结返回HTTP402。随后修复多步总预算和供应商错误码持久化，当前工程检查通过，最终修正版没有新完整真实流程通过证据。本批未完成验收，不能选这场为最终样例。原场及失败报告保留；对其SQLite备份的启动恢复验证没有调用模型或覆盖原记录。

后端启动自动应用006迁移，保留001–005校验和、任务行及归属/唯一约束，重复初始化无操作。旧遗留PENDING按既有恢复规则标INTERRUPTED，不重播讨论。正常余额错误现在可保存失败状态；补充余额后总结可用页面原重试操作继续同run与冻结消息边界。ready仅配置检查，不证明余额充足。

真实思考的有限覆盖配置可仅在后端PowerShell设置，再运行启动脚本（不修改用户.env）：

```powershell
$env:MODEL_THINKING_MODE = 'enabled'
$env:MODEL_REASONING_EFFORT = 'low'
$env:MODEL_THINKING_MAX_TOKENS = '16384'
$env:MODEL_TIMEOUT_SECONDS = '120'
$env:INSIGHT_MAX_SECONDS = '240'
$env:SUMMARY_MAX_SECONDS = '180'
$env:DISCUSSION_MAX_SECONDS = '600'
.\scripts\start-backend.ps1
```

每HTTP有独立httpx超时，观点/总结的全部子调用和重试共享有限任务截止时间。这些参数通过可控上游和引擎检查，尚未通过最终修正版的整场真实质量验收；默认短预算适合替身，不保证真实思考耗时。运行时模型和Codex开发模型完全独立。常规pytest不发起真实付费调用。
