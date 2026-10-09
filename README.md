# AI Panel Studio

本地多专家圆桌讨论应用。当前完成 **阶段3：DDD前端页面与演播厅交互**：可创建话题、确认阵容、观看预设圆桌、查看共识分歧与总结。页面始终标识模拟模式；内容来自“四天工作制”台本，换话题不会生成新分析。后端讨论引擎、真实SSE和模型调用尚未实现。开发工具为Codex，应用运行时模型由后端独立配置。

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
| MODEL_TIMEOUT_SECONDS / MODEL_MAX_CONCURRENCY | 30 / 4 | 后续模型调用预算；本阶段读取验证但没有调度循环 |
| DISCUSSION_MAX_ACTIVE / DISCUSSION_MAX_TURNS / DISCUSSION_MAX_SECONDS | 3 / 20 / 300 | 后续引擎默认限制，当前不声称已经执行 |
| SUMMARY_MAX_SECONDS | 60 | 后续总结独立时间预算 |

若修改后端端口，启动前端前设置进程变量 `$env:PANEL_BACKEND_ORIGIN='http://127.0.0.1:新端口'`；它只是 Vite 服务端代理目标，不是模型配置。不要把密钥放入任何 `PANEL_PUBLIC_*` 或 `VITE_*` 变量。

## 启动

只体验阶段3前端模拟时，安装完成后运行 `scripts/start-frontend.ps1` 即可，无需启动后端。访问5173后可以新建讨论，或进入两场预设圆桌；右上“演示工具”提供播放速度和失败重试场景。模拟内容保存在当前浏览器localStorage，清空工具会删除这些模拟记录。

检查阶段2真实基础连接时，在两个项目根 PowerShell 窗口分别执行：

```powershell
# 窗口 1：后端，启动时自动检查/应用迁移
.\scripts\start-backend.ps1
```

```powershell
# 窗口 2：前端
.\scripts\start-frontend.ps1
```

访问 [本地前端](http://127.0.0.1:5173) 体验模拟流程；访问 [基础连接检查](http://127.0.0.1:5173/?view=system)。检查页显示“基础服务已连接 / 数据库已就绪 · 确定性模拟模式”代表前端通过代理访问了真实后端。按 Ctrl+C 停止对应进程；端口占用时明确失败，不偷偷切端口。后端 API 文档位于 [Swagger UI](http://127.0.0.1:8000/docs)。运行时只有三个基础接口。

其他系统的等价启动方式（未实机验证）：`python3 -m venv .venv`，用 `.venv/bin/python -m pip install -r backend/requirements.lock` 安装；用 `.venv/bin/python -m backend.app.server` 启动；前端目录执行 `npm ci` 和 `npm run dev`。

## 数据库初始化

```powershell
.\.venv\Scripts\python.exe -m backend.app.database
# 独立实验数据库，避免影响正常数据
.\.venv\Scripts\python.exe -m backend.app.database --path work/check.sqlite3
```

首次输出 `Migrations applied: [1]`，重复输出 `[]`，不会清空数据。迁移有校验和、版本顺序及事务回滚；已应用SQL不修改，新变更加新版本。没有自动降级/删除数据操作。不要把本地数据库或 WAL/SHM 文件放入提交或交付包。

## 实际可用接口与设计契约

| 接口 | 当前用途 |
|---|---|
| GET /api/health/live | 进程存活 |
| GET /api/health/ready | 迁移状态及当前模型适配是否可用 |
| GET /api/system | 安全的应用版本/阶段/模拟模式标识 |

完整创建、生成阵容、启动、快照、操作查询、总结重试与 SSE 定义在 [API 契约](docs/api.md) 和 [目标 OpenAPI](docs/contracts/openapi.json)；它们本阶段未挂载，`x-implemented=false`。不要把示例 JSON 当作真实讨论。

## 验证命令

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m scripts.export_contracts --check
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

## 已完成、限制与后续

- 已完成：阶段3前端模拟首页/创建/阵容/演播厅/总结、来源定位、历史阅读保护、模拟断线及失败重试；阶段2前后端骨架、锁文件和启动脚本、数据库迁移、健康/配置/日志/错误基础、数据与HTTP/SSE契约、模型协议和确定性模拟、结构约束测试及浏览器连通性冒烟。
- 未实现：业务HTTP路由、嘉宾生成任务、参与意图收集、发言调度、主持推进、实时洞察、总结工作流、真实SSE订阅与恢复、真实模型适配、五条最终质量样例。
- 结构约束可测不等于任务隔离和恢复已完成；单worker/本地使用，无登录权限与公网部署。真实模型质量、成本和时延未验证。
- 限制：前端模拟数据不写SQLite，无跨标签页协作；浏览器存储不可用时仅保留在内存。模拟时钟、固定台本、故障按钮不证明专家自主调度或真实服务质量。
- 下一步：阶段4核心引擎按TDD，阶段5替换HTTP/SSE客户端并完成真实业务链路E2E，阶段6真实服务与最终交付。

生产预览：项目根运行 `npm --prefix frontend run build`，再运行 `npm --prefix frontend run preview`，访问 http://127.0.0.1:4173。默认前端模拟无需后端；Ctrl+C停止。页面设计及组件边界见 [前端设计](docs/frontend-design.md)。

设计索引：[需求](docs/requirements.md)、[架构](docs/architecture.md)、[数据模型](docs/data-model.md)、[API](docs/api.md)、[验收](docs/acceptance.md)、[决策](docs/decisions.md)、[进展](docs/progress.md)、[Prompt](docs/prompt-log.md)。
