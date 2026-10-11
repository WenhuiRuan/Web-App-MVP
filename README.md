# AI Panel Studio

本地多专家实时圆桌 Web 应用：输入议题 → 生成主持人与专家 → 确认阵容 → 观看自主讨论及实时共识/分歧 → 查看主持人自然语言总结。默认前端使用真实 HTTP/SSE 和 SQLite；运行模型由后端配置，与 Codex 开发工具独立。

## 环境与首次安装

已验证 Windows、Python 3.12.10 / SQLite 3.49.1、Node 24.18.0 / npm 10.5.0、Edge。要求 Python 3.12、SQLite ≥3.37（STRICT 表），Node ≥22.12，建议 Node 24。Linux/macOS 命令可等价执行，尚未实机验证。

在本文件所在的项目根目录打开 PowerShell：

```powershell
.\scripts\setup.ps1
```

脚本建立 `.venv`，按 `backend/requirements.lock` 安装完整锁定版本、在 frontend 执行 `npm ci`，再初始化数据库；不自动创建或覆盖 `.env`。前端传递版本锁定于 `frontend/package-lock.json`，不要常规安装时升级。安装需要网络；当前 npm 锁的下载源为 npmmirror，pip 源沿用本机配置。

若执行策略限制脚本，可逐条运行等价命令，不必修改全局策略：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --cache-dir .cache/pip -r backend/requirements.lock
Push-Location frontend
npm ci --no-fund --no-audit
Pop-Location
.\.venv\Scripts\python.exe -m backend.app.database
```

## 两种运行模型模式

首次解压没有 `.env`，默认为后端确定性模拟，**不调用付费 API**。可按需复制 `.env.example` 为 `.env`；已有文件请保留。后端进程环境变量优先于项目 `.env`，修改后需重启后端；已保存讨论不自动重写。

**后端模拟模式**（完整真实前后端、SQLite、SSE，模型是替身）：

```powershell
# 窗口 1，项目根目录；明确覆盖已有 .env 的 provider
.\scripts\start-backend.ps1 -ModelMode mock
```

```powershell
# 窗口 2，项目根目录
.\scripts\start-frontend.ps1
```

访问 http://127.0.0.1:5173；页面标识当前后端模拟模型。独立前端台本仅用于演示/页面测试：`http://127.0.0.1:5173/?mode=mock`，无需后端，不代表自主模型讨论，不写 SQLite。

**DeepSeek 真实模式**：在后端 `.env` 配置下列项目，密钥由后端启动终端继承的 `PANEL_API_KEY` 提供，不要写入源码或前端环境。已设置系统环境但老终端尚未继承时，新开后端终端即可；不要输出密钥。

```dotenv
MODEL_PROVIDER=deepseek
MODEL_BASE_URL=https://api.deepseek.com
MODEL_NAME=deepseek-flash
MODEL_API_KEY=${PANEL_API_KEY}
MODEL_THINKING_MODE=enabled
MODEL_REASONING_EFFORT=low
MODEL_THINKING_MAX_TOKENS=16384
```

运行 `.\scripts\start-backend.ps1`（configured，遵循已有配置）或显式 `-ModelMode deepseek`，另一个终端启动前端。页面显示“DeepSeek · deepseek-flash（真实服务）”。官方 OpenAI 兼容 Chat Completions；六任务均启用 enabled/low，仅使用最终回答，不保存/展示 reasoning_content。模型名称对应关系以供应商为准。

就绪检查只检查配置和数据库，**不调用模型、不证明上游连通**；点击生成阵容后开始真实付费调用。缺少配置会报告变量名，认证/余额/限流/超时有明确失败。不要把任何密钥放入 PANEL_PUBLIC_* / VITE_*，也不要在截图或日志中输出环境变量。

## 预算与端口

Settings、`.env.example` 和日常真实配置采用同一套已验证有限预算；模拟模型迅速返回，不会等待耗尽预算。

| 配置 | 默认值 | 含义 |
|---|---|---|
| MODEL_TIMEOUT_SECONDS | 120 秒 | 每个模型 HTTP 请求上限；多步提取/总结共用下方任务预算 |
| INSIGHT_MAX_SECONDS | 240 秒 | 每批观点总预算，包含排队、草稿、整批复核、有限收窄和重试 |
| SUMMARY_MAX_SECONDS | 180 秒 | 总结独立预算，讨论时长用尽后仍可生成 |
| DISCUSSION_MAX_SECONDS | 600 秒 | 运行上限；启动时冻结到 run，旧 run 不变 |
| DISCUSSION_MAX_TURNS | 20 | 日常最多正式发言数，含主持人；主持可提前结束 |
| DISCUSSION_HOST_SKIP_LIMIT | 2 | 每run累计最多跳过两次重试耗尽的非法非开场主持发言；0关闭，不跳过认证/取消/数据库错误 |
| MODEL_MAX_ATTEMPTS / MODEL_MAX_CONCURRENCY | 2 / 4 | 含首次的有限尝试数 / 全局模型并发 |
| DISCUSSION_MAX_ACTIVE | 3 | GENERATING、RUNNING、SUMMARIZING 的活动容量 |
| BACKEND_HOST / BACKEND_PORT | 127.0.0.1 / 8000 | 单进程本地服务，禁止多 worker 共管同一数据库 |
| DATABASE_PATH / LOG_LEVEL | local-data/panel.sqlite3 / INFO | 相对根目录的 SQLite 路径 / 安全基础日志 |

最终真实质量验收**另设 8 条上限**以控制验证费用，实际因 turn_limit 结束；不是产品要求或日常默认值。该场观察耗时 418.333 秒、62 次 HTTP、返回用量 200543 tokens；最后提取 135.734 秒。并发 IO 耗时不能累加当整场时长，费用和 p95 未知。这套预算有一次完整成功证据，不是延迟 SLA。细节见[真实质量验收](docs/quality-acceptance.md)。

修改端口时，后端终端设 `$env:BACKEND_PORT='18100'`；前端终端设 `$env:PANEL_BACKEND_ORIGIN='http://127.0.0.1:18100'` 并执行 `.\scripts\start-frontend.ps1 -Port 15180`。代理目标只是本地 API 地址，不是模型配置。端口被占明确失败；Ctrl+C 停止本人启动的服务。

生产预览：`npm --prefix frontend run build`，然后 `npm --prefix frontend run preview`，访问 http://127.0.0.1:4173；默认业务模式仍需同时运行后端。基础连接页 `/?view=system`，后端 Swagger http://127.0.0.1:8000/docs。

## 数据库与样例

```powershell
.\.venv\Scripts\python.exe -m backend.app.database
# 独立试用库：不要让两个服务管理同一数据库
.\.venv\Scripts\python.exe -m backend.app.database --path work/examples.sqlite3
```

首次迁移 `[1, 2, 3, 4, 5, 6, 7]`，006旧库升级仅`[7]`，重复 `[]`，不清空内容。后端启动也会自动迁移。SQL 历史带校验和，新变化追加迁移；无自动降级。001 中的历史 SQL 默认值保留，应用创建 run 时显式写入当前 Settings 上限。

至少五份预设议题与阵容见[样例索引](data/samples/final/README.md)，可以直接阅读姓名、职业、立场和颜色，来源/质量说明分开记录。其中四份为编写复核的预设阵容，一份复用合格真实阵容；不冒充五场真实完整讨论。

```powershell
# 无模型调用，仅检查当前契约与归属
.\.venv\Scripts\python.exe -m scripts.final_samples
# 服务停止时离线导入独立库；再次执行 imported=0, skipped=5
.\.venv\Scripts\python.exe -m scripts.final_samples --database work/examples.sqlite3
# 启动此库，首页“已保存的讨论”可进入 READY 阵容，确认后才讨论
$env:DATABASE_PATH='work/examples.sqlite3'
.\scripts\start-backend.ps1 -ModelMode mock
```

导入事务涵盖全部五份阵容及对应事件，发生冲突或写入失败全部回滚，不覆盖用户数据。固定身份使重复导入跳过，已启动的样例也不重放。离线导入无需密钥、不读取 `.env`。附加完整真实演示保持原快照及版本，见样例索引；失败证据仅作质量资料。

## 主要 API 与行为

| API | 用途 |
|---|---|
| GET /api/health/live、/api/health/ready、/api/system | 存活、配置/数据库就绪、安全模型模式 |
| POST /api/discussions | 创建，默认 4 专家，允许 2–6 |
| GET /api/discussions、/api/discussions/{id} | active/all 列表、快照及事件高水位 |
| POST /api/discussions/{id}/roster-generation | 后台生成阵容，失败/中断可新键重试 |
| POST /api/discussions/{id}/start | 确认当前 roster_revision，唯一 run，自动调度 |
| POST /api/discussions/{id}/summary-retry | 原 run 与冻结消息边界的总结重试 |
| GET /api/discussions/{id}/operations/{operation_id} | 安全操作状态/错误码 |
| GET /api/discussions/{id}/diagnostics?run_id={run}&limit=100 | 普通启动持久化的模型尝试与恢复诊断；next_before用于旧页 |
| GET /api/discussions/{id}/events?after={seq} | 顺序持久化 SSE，Last-Event-ID 优先，15 秒心跳 |

所有命令要求 UUID 格式 Idempotency-Key；网络重发保留原键，失败后的显式重试用新键。快照读取后从高水位订阅，缺口/断线重新取快照恢复，不重放业务。每两条已提交发言触发观点，结束补尾；只引用本 run 已提交消息，共识需至少两专家的明确共同主张，证据不足允许为空。总结失败可重试，不重新生成阵容或讨论。

服务关闭/重启时遗留活动任务标为 INTERRUPTED；阵容与总结可按阶段重试，讨论运行中断不能自动续播。模型 IO 不持有数据库事务，事件与业务数据原子提交。完整示例及错误见[API](docs/api.md)。

非法输出仍严格校验并在原有限预算内反馈具体纠正约束；只有非开场主持linking/followup耗尽校验重试，且已有专家发言、运行仍有效时可有限跳过。取消原领取并记录HOST_SKIPPED，随后专家自主参与，不生成虚假主持消息。持续失败明确终止，保留已有内容。诊断只保存安全类别、任务/角色/位置/尝试与耗时，不保存完整响应、密钥或隐藏推理。

本轮诊断/恢复与主持邀请修正已完成可控验证，**尚未进行修正版付费复测**。需要重启后端加载代码/Prompt及007迁移，前端无须因本轮修改重启。旧失败讨论保持原状，复测请新建讨论；具体观察及诊断查询见[模型恢复报告](docs/model-recovery.md)。

## 测试与已验证范围

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m scripts.export_contracts --check
.\.venv\Scripts\python.exe -m scripts.check_docs
.\.venv\Scripts\python.exe -m scripts.final_samples
npm --prefix frontend run build
# 已安装 Edge 时；测试自动使用独立库和可控后端替身
$env:PLAYWRIGHT_CHANNEL='msedge'
npm --prefix frontend run test:live
```

普通 pytest 与浏览器 test:live 不调用付费模型。test:live 使用 18081/15174，test:smoke 使用 18080/15173；若没有 Edge，在 frontend 运行 `npm exec playwright install chromium` 并去掉 PLAYWRIGHT_CHANNEL。测试故障入口只在专用 e2e_server，不用于日常运行。

业务 TDD、持久化/隔离、SSE 恢复、真实服务替身 E2E（13 项）、四尺寸布局及最终 DeepSeek 完整质量验收已有证据。阶段6B完成配置、样例导入和独立安装/启动检查；交付后本轮另补互动逻辑、受影响测试及真实完整讨论，详见互动质量报告。分批实际结果见[测试说明](docs/testing.md)，不能把不同批次计数相加当单次全量运行。

## 完成功能、限制及后续

已完成创建、生成/确认、专家自主参与与回应、主持控制、公开角色状态、正式短句、实时有来源观点、自然语言总结、失败恢复、持久化有序 SSE 和浏览器业务闭环。使用 React + TypeScript + Vite、FastAPI、SQLite、SSE、pytest、Playwright，模块说明见[架构](docs/architecture.md)。

本地单 worker、无登录/公网权限、多进程/大量并发尚未验证。真实模型语义不能仅凭结构保证；保守复核可能漏掉共识或隐含分歧，后续发言仍需用户辨别。费用、跨平台、真实并发及 p95 未知。运行中断不能自动继续；无视频录制或时间轴回放播放器。已保存内容可重新查看。

本地交付包含源码、锁、迁移、五份阵容样例、开发文档、六段核心 Prompt、一页工作流和必要质量证据；原始过程与 Git 历史保留。下一步由用户准备姓名、发布 GitHub/Gitee、核对 72 小时起算与发送邮件，不自动发布或发送。见[交付核对](docs/delivery.md)。

文档：[需求](docs/requirements.md) · [ER/数据模型](docs/data-model.md) · [验收](docs/acceptance.md) · [核心开发 Prompt](docs/core-prompts.md) · [工作流](docs/workflow.md) · [进展](docs/progress.md) · [原始 Prompt 记录](docs/prompt-log.md)。


## 自主互动与观点更新

主持可选择继续专家讨论、实际追问、串联或结束；选人按相关性与回应关系确定，公平性防止长期独占，不保证每人依次发言。观点提取与后续发言并行，每场只保留一个在途提取和一个最新待处理前缀，面板显示已成功提取的消息边界。结束后先核对最终前缀，再用独立预算总结；600秒讨论预算并非整体完成时间上限。

开场只简短提出核心取舍，不给每位嘉宾分配方向或排序；追问/串联基于已出现的具体主张，点名是邀请，不规定结论。专家依职业、立场和公开消息决定回应对象，可以质疑问题前提、补充或PASS，未回应不代表赞同。上下文明确标识邀请非强制，身份/引用校验保持；示例及验证范围见[模型恢复报告](docs/model-recovery.md#主持邀请修正)。

语义合并和未决条件仍需要模型判断，不宣称逐字来源校验能够保证全部内容正确。本轮原场问题、修正、定向与完整真实复核见[互动质量报告](docs/quality-interaction.md)。旧安装/布局记录沿用，本轮只补验受影响逻辑。五份离线阵容来源不变，不代表本轮新跑了五场付费讨论。

本轮真实场11条由主持决定结束，讨论推进190.455秒、含最终提取/总结总计418.705秒；最终观点核对仍需172.494秒，不承诺无等待。个人观点摘录保守选取作者最后发言，早期独立建议可能省略，早期有效共同主张仍按完整前缀复核。完整流程与之后受影响语义补验分开记录，不能把某次浏览器通过当作每场内容保证。
