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
| 供应商失败持久化及基础契约 | 46 passed / 7.85 秒 | test_provider_failure_persistence、test_database、foundation/contracts/artifacts，007 未创建，当前 schema006 |
| 最终真实模型完整浏览器流程 | 1 passed，观察 418.333 秒 | code0465f68；8正式发言、4成功观点批次、412字总结、turn_limit；62 HTTP / 200543 reported tokens |

最终真实场与逐条源消息判断见 [质量验收](quality-acceptance.md)，没有发生撤回或条件改变的场景；这些由之前独立定向验证和测试证明。原失败仍保留，不能把格式通过或定向生成替换原场内容验收。真实调用费用、真实并发、p95、跨平台未知。

## 复现入口

在项目根按 README 安装，再运行 `python -m pytest -q`；只复现本批用 `python -m pytest backend/tests/test_delivery_config.py backend/tests/test_final_samples.py backend/tests/test_foundation.py backend/tests/test_artifacts.py -q`。执行 `python -m scripts.export_contracts --check` 和 `python -m scripts.check_docs` 检查契约产物/文档，`npm --prefix frontend run build` 做类型及生产构建。

`npm --prefix frontend run test:live` 使用独立临时库和后端替身；`?mode=mock` 是另一种前端台本，不作业务验收。真实验证脚本是主动付费入口，不属于首次安装或常规测试步骤。

## 交付导出规则补验

导出边界新增用例先4 failed / 1 passed（0.20秒）：意外已跟踪的数据库WAL/SHM/journal与JKS也必须排除，不能只依赖.gitignore。补充拒绝规则后，导出安全、配置与样例13 passed / 0.59秒；不重跑未影响的引擎或E2E。当前包未发现真实运行文件，本次用例是防止导出规则将未来误跟踪文件带出。常见密钥模式与JSON隐藏推理字段负例通过，没有读取用户实际密钥。
