# 运行手册 ledgerbank

## 启动与停止

```bash
docker compose up -d --build
docker compose ps
curl -s http://127.0.0.1:18206/api/health
docker compose down -v --remove-orphans
```

## 重建数据库

```bash
docker compose down -v
docker compose up -d --build
```

命名卷 `ledgerbank-data` 保存批次、流水行、候选与匹配。重建后从「载入样例」重新开始。

## 主流程

1. `POST /api/demo/run`：读取两份脏样例，采信、质量、候选、匹配一次跑完。
2. `GET /api/quarantine`：查看隔离行与原因分布。
3. `GET /api/candidates`：查看已生成候选。
4. `GET /api/matches`：查看匹配组与手续费分摊。
5. `GET /api/differences`：查看两侧守恒与差异归因。
6. `GET /api/export/report.csv` 与 `GET /api/export/manifest.json`：导出。

## 单步重跑

```bash
curl -s -X POST http://127.0.0.1:18206/api/candidates
curl -s -X POST http://127.0.0.1:18206/api/matches
```

同一输入重跑命中同一 `run_id`，先删后插，行数与合计不变。

## 导入自有文件

```bash
curl -s -X POST http://127.0.0.1:18206/api/statements/import \
  -F side=bank -F file=@sample_data/bank_statement_dirty.csv
```

支持 UTF-8（含 BOM）、UTF-8 无 BOM、GB18030；列名按 `GET /api/contract` 的别名表映射。

## 口径升级

```bash
# 1. 只看影响，不落库
curl -s -X POST http://127.0.0.1:18206/api/upgrades/impact \
  -H 'Content-Type: application/json' \
  -d '{"rule_version":"2026.11.2","tolerance":"0.01"}'

# 2. 执行升级（新批次、候选、匹配与升级清单同一事务写入）
curl -s -X POST http://127.0.0.1:18206/api/upgrades \
  -H 'Content-Type: application/json' \
  -d '{"rule_version":"2026.11.2","tolerance":"0.01"}'

# 3. 查看当前生效批次的升级结论
curl -s http://127.0.0.1:18206/api/upgrade/current

# 4. 标记某批次已复核（之后不可被重跑覆盖）
curl -s -X POST http://127.0.0.1:18206/api/runs/<run_id>/review \
  -H 'Content-Type: application/json' -d '{"reviewed_by":"张会计"}'
```

- 已复核批次不重算、不改写；升级结果 `batches[].re_review_required` 为 `false`，`decision` 为 `kept_reviewed`。
- 待关账批次按目标口径生成新批次，`re_review_required` 为 `true`，需重新复核后才算发布完成。
- 同一目标口径 + 同一组输入重复执行返回首次结果（`created: false`），不新增批次或行。
- 升级中断（进程被杀/写库异常）整体回滚，旧批次页面与导出保持完整可用；直接重试即可。
- 想要第 N 版页面与导出文件：`/batches?run_id=…`、`/api/export/report.csv?run_id=…`、
  `/api/export/manifest.json?run_id=…`，两者读同一批次同一口径。

## 失败处理

- 400：参数或文件不可用，页面顶部提示原因，保留已填内容。
- 404：批次或样例不存在，先执行 `POST /api/demo/run`。
- 409：还没有候选就求解匹配，先执行 `POST /api/candidates`。
- 隔离行不是失败：按原因码修正源文件后重新导入。

## 日志

```bash
docker compose logs -f app
```
