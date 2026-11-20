# 整理与软删（前端重新设计 v5 第三期）

cz 2026-11-20 裁决：任务可以删，做软删。“删除”不改日志、不删账：它是人提交的一条 `curate` 事件。

## 操作

`curate`（只有人；关题之后照样能提交），事件体取下面一项或几项：

| 字段 | 取值 | 说明 |
| --- | --- | --- |
| `shelf` | `active` / `archived` / `trash` | 归档、移进回收站、移回；进回收站要先关题 |
| `title` | 1–200 字 | 改显示名；原名记进 `renamed` |
| `pinned` | 布尔 | 置顶 |

- 正在跑的任务删除时，前端在同一批里先提交 `close_problem` 再提交 `curate {shelf: trash}`；批内依次校验，所以两条一起成功或一起被拒。
- 回收站保留 30 天（`reducer/curate.py` 的 `TRASH_DAYS`）。期内可移回；过期后读端标成 `purged`，再整理被拒。
- 过期后由全栈的看门循环清掉那道题各会话的目录（`adapter/purge.py`），只删工作区与 home；事件账、留档 Blob、花费都不动。

## 读端

`GET /v1/problems` 每行多三项：`shelf`（`active | archived | trash | purged`）、`pinned`、`trash_until`。
软删的题照样计入 `totals` 与读数页；任务列表按 `shelf` 把它们收进“归档”“回收站”，`purged` 不再列出。

`curate` 不进等级、消费门、画像与终态。
