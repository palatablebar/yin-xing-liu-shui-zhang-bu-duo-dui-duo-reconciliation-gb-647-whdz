# ledgerbank 银行流水与账簿多对多对账

连锁零售财务共享组每月核对 12 个银行账户与账簿凭证。一笔付款可能拆成多张凭证，
多笔流水也可能合并支付一张发票；会计原先逐条手工比对，手续费与尾差经常对不上。

## 核心规则

- 候选：方向相同、金额差 ≤ 0.02 元、本地日期差 ≤ 3 天。
- 一对一、一对多、多对一都参与求解；多对一用受限子集和，最多 4 条，按金额降序枚举。
- 择一：层级优先（一对一 → 一对多 → 多对一），再按金额差、日期差、业务号升序，取不重叠的组合。
- 手续费只计银行侧，不进入匹配金额；匹配组按银行金额比例分摊手续费，尾差用最大余额法分到分。
- 银行合计 = 匹配金额 + 未匹配金额 − 手续费合计；账簿合计 = 匹配金额 + 未匹配金额。

## 功能模块

| 模块 | 使用者动作 | 入口 |
|---|---|---|
| M1 流水采信 | 导入银行流水或账簿凭证，看到编码、分段与逐行诊断 | `POST /api/statements/import`、页面 `/` |
| M2 金额日期规则 | 查看列定义、借贷符号、容差与日期窗口 | `GET /api/contract` |
| M3 质量隔离 | 按原因码看隔离行并导出 CSV | `GET /api/quarantine`、`/api/quarantine.csv`、页面 `/quarantine` |
| M4 候选匹配 | 生成一对一、一对多、多对一候选 | `POST /api/candidates`、页面 `/candidates` |
| M5 多对多求解 | 求解不重叠匹配组，看手续费分摊 | `POST /api/matches`、页面 `/matches` |
| M6 差异与批次 | 看两侧守恒、差异归因与历史批次 | `GET /api/differences`、`GET /api/batches`、页面 `/batches` |
| M7 报告导出 | 导出报告 CSV 与运行清单 JSON | `GET /api/export/report.csv`、`/api/export/manifest.json`、页面 `/export` |
| M8 口径升级 | 已复核批次保持原结论，待关账批次按新口径重算，看受影响匹配、差异与可发布范围 | `POST /api/upgrades`、`POST /api/upgrades/impact`、页面 `/upgrade` |

## 启动

```bash
docker compose up -d --build
```

打开 <http://127.0.0.1:18206/>，点「载入样例」即可跑完采信 → 质量 → 候选 → 匹配 → 差异 → 导出。

## 演示步骤

1. 首页点「载入样例」，页面顶部出现银行 22 笔、账簿 19 笔、匹配 11 组。
2. 打开「隔离区」，看 8 条隔离行的原因码，下载隔离 CSV。
3. 打开「候选」，核对一对一 7 条、一对多 2 条、多对一 2 条。
4. 打开「匹配」，看 11 组匹配与手续费分摊合计 22.31 元。
5. 打开「批次」，核对银行笔数、账簿笔数、手续费分摊、匹配差额四项平衡。
6. 打开「导出」，下载报告 CSV 与运行清单 JSON。

## 口径升级

1. `POST /api/upgrades/impact` 传 `{"rule_version": "2026.11.2", "tolerance": "0.01"}`，只看影响不落库。
2. `POST /api/upgrades` 用同一组参数执行；新批次、候选、匹配与升级清单在一个事务里写入。
3. 已复核批次（`POST /api/runs/{run_id}/review`）保持原结论，结果里标注「否，保持已复核结论」；
   待关账批次按新口径重算并标注「是，新口径结果待复核」。
4. 同一目标口径重复执行返回首次结果，不新增批次、流水、凭证或匹配记录。
5. 页面 `/batches?run_id=…` 与 `/api/export/*.csv`、`*.json?run_id=…` 读同一批次的同一份结论。

## 测试

```bash
docker compose exec -T app python -m pytest -q
```

## 页面

- `/` 工作台：左右对照、固定合计条、差异行左边框。
- `/quarantine` 隔离区。
- `/candidates` 候选清单。
- `/matches` 匹配组。
- `/batches` 对账与批次历史。
- `/export` 导出。
- `/upgrade` 口径升级：计算影响、执行升级、复核状态与升级历史。

## 目录

```text
app/            平台层与八个功能模块
app/templates/  base + 七个页面
app/static/     theme / layout / components + 三个脚本
docs/           DEPTH、DATA-DICTIONARY、RUNBOOK
sample_data/    六份脏样例与一份空白样例
tests/          模块测试、端到端、不变量
```

## 已知不覆盖

- 凭证拆分到科目层的匹配不做，只按银行账户与金额对账。
- 多币种不折算，样例只有人民币；外币流水会因金额列带币种符号之外的字符进隔离区。
- 跨年账单不分摊手续费，一次运行只对应一份月度流水。
