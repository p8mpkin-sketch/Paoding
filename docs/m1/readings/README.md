# M1 真实读数

每批读数一个文档（`<日期>-<批次>.md`），原始记录放在同名目录的 `records/` 下，由评测台收集：

```
uv run python -m paoding_eval collect --out runs --into docs/m1/readings/<日期>-<批次>/records
```

`records/` 里每条运行一个 JSON（record 与 meta：运行器提交号、清单摘要、baseline 是否在沙箱里），外加 `summary.md`。
两者都不含答案与密钥。CLI 流水、工作区、事件日志等大件留在本机的 `runs/`，不入库。

读数文档的约定：

- 结论引用 `records/summary.md` 的数，注明运行器提交号与清单摘要；两批读数只有摘要相同才能直接比较。
- 修正读数时写明前一版错在哪里，不只换数字。
- baseline 的 meta 里 `sandbox` 必须为 true：在宿主上跑的 baseline 连不到题目环境，对照不成立（见 `eval/SPEC.md` 的“两臂环境对等”）。

## 已知问题

- `2026-11-18-first-comparison.md`（baseline 0/3、full 3/3）：那一批的 baseline 在宿主上跑，原生工具面里没有 Bash，
  提示里也没说要写 answer.txt，所以三次全败量到的是环境差异，不能用来裁 G1、G2。同一道题上，单 CLI 早先 26 秒解出过
  （`docs/m0/report.md` 的 B1 一栏）。修复见 `eval/SPEC.md`；这一批待按新运行器重跑后替换。
