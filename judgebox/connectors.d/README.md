# 连接器档案（外部裁决，docs/design/external-verdict/ §5.1）

一个 `*.yaml` 一份平台档案。平台的端点、字段、状态词只写在这里，组件代码与内核不出现（红线 3）。
启动时加载并按 `paoding_judgebox.connector.validate_profile` 校验形状，不合即启动失败；整份档案的摘要随开题抄进
判官快照，档案改动即换摘要，已开的题不受影响：`connector` 运行器按快照核对，不一致即拒绝运行（`inconclusive(env_error)`）。

形状见设计稿 §5.1。要点：

- `base_url` 是 http(s) 地址，不许带用户名口令。
- `credential` 只写钥匙环槽位名 `key_slot`（小写字母、数字、`-`、`_`，至多 32 字符），可另写请求头形状
  `header`（缺省 `Authorization`）与 `scheme`（缺省 `Bearer`，空串即裸值）。不写值。
  值在启动时从环境变量 `PD_CONNECTOR_<槽位名大写，非字母数字换成 _>` 注入，或在设置页“密钥”一节输入；
  只在钥匙环里，不落盘，不进日志。槽位 `default` 归模型密钥，不能用。
- `endpoints` 至少有 `submit` 与 `receipt`；路径里 `{task}`、`{sid}` 按绑定单与提交号填；POST 的 `body` 里
  `"$candidate"` 换成候选正文。
- `fields` 是 JSON 指针，至少有 `submission_id` 与 `status`；有 `task` 时核对回执归属，有 `submitted_at`（毫秒）时
  只认开题之后的提交。
- `verdict` 把回执状态映射到 `pass` / `fail` / `pending`；表外的值记 `inconclusive(unsupported)`。
- `deliver`：`judge`（缺省，判官代交，同一候选只交一次）或 `worker`（候选正文就是提交号，判官只读回执）。
- `poll`：`first_s`、`max_s` 是待定时复判的退避（按次数翻倍、封顶）。

提交号存在 `<home>/connectors/`（一个（题、候选）一个文件），重启之后复判照旧只读回执、不重交。

本目录缺省没有档案。配套平台模拟的档案见 `tests/integration/platform_mock.py` 的 `profile()`。
