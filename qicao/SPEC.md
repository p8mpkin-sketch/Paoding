# qicao/：起草（一句话开题）

设计：[`docs/design/kaiti/README.md`](../docs/design/kaiti/README.md)（cz 2026-11-19 裁决：九条全部采纳）。本组件是迁移表第一期。

## 三层里的位置

| 层 | 模块 | 确定性 |
| --- | --- | --- |
| ① 前置抽取 | `extract.py`：答案标签行剪出；地址、网址、时长、金额、代码块、文件名、句子 → 区间表 | 是 |
| ② 起草 | `draft.py`：模型只指认区间，严格 Schema；经端点代理（`MessagesClient` 拿"开题"账户的任务令牌，不拿密钥） | 否 |
| ③ 校验 | `vet.py`：出处账、答案外泄、判据映射、风险表、预算先验与裁剪、分道 | 是（纯函数） |
| 批次 | `ops.py`：Vetted → 登记 + `open_problem`；答案先进保密库（`vaultio.py`），批次里只有 VaultRef | 是 |

写入路径上没有本组件：开题仍由人的令牌提交（`pd kaiti`，二期网页同一条 `app/submit.ts`）。图服务不调用本组件。

## 数据（`kaiti.d/`，领域词只许写在这里）

- `intake.yaml`：答案标签、URL 缺省端口、模板缺省、零确认开关 `zero_confirm`（**缺省 false**：放行由人按离线读数决定）。
- `practice.yaml`：练习道信封的资源、地址白名单与判官；金额与时长上限取设置层 `caps.practice_*`。
- `priors.placeholder.yaml`：预算先验的占位表。真实的"档位 → 默认预算"表由测试方注入（`--priors`），本仓库不读取任何题库或校准目录。

## 接口

- `PriorSource`：`lookup(tier, signature) → Prior | None`、`version()`；`TablePriors` 是注入表的实现。
- `Settings.from_doc`：读 `/v1/settings` 的形状（生命周期地图 PR #84）：`caps`、`risk`（顺序匹配，未命中 r2）、`models`（起草档案取 `routes.draft`，可按档案名覆盖，不许填端点或密钥）。
- `offline.py`：§10 第 3 条的离线读数；练习道判定精确率达到 1.0 是零确认放行的前提。

## 一期没有做的

内核的练习道信封与 `Problem.origin.draft`（第三期）；网页输入框与确认卡（第二期）；单题硬顶（生命周期地图线程的 L1①）；端点代理的"开题"账户与钥匙环（同上）。
