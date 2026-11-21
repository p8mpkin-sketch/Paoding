"""资源种类登记表（§3.1.2 画像推导、§3.6.2 授权编译）的单一事实源。

内核不理解 resource 的含义，只需要知道它是否 external（画像的信息轴：有 external 资源 → partial）。
执行层的资源种类插件按同一张表实现编译行为，CI 测试断言两边的键集合一致；画像与编译不得各持一份。

- net：网络地址。题目环境在本机之外或可能变化，算外部资源（§6.1 走查：目标环境在题目之外的题画像为 partial）。
- workspace：本题工作区，只读写自己的文件，信息完整（§6.4 走查：只有 workspace 的题为 complete）。
"""

RESOURCE_EXTERNAL: dict[str, bool] = {
    "net": True,
    "workspace": False,
}


def external_resources() -> frozenset[str]:
    return frozenset(k for k, ext in RESOURCE_EXTERNAL.items() if ext)


# 运行时扩权（设计 docs/design/runtime-grants/ §4.1）：申请里的 pattern 与 actions 在写入时就要能被执行层编译，
# 否则批下来的规则在起沙箱时才报错。形状与执行层插件一致（net 的 host:port 端口必须写明，异议 006 第 1 项；
# 动作只有 connect 有执行手段）；workspace 每题开题即有，不经申请。
# 只读白名单（地图 Q36）能自动批的动作：每种资源只列不改外部状态的那些。net 今天只有 connect 一个动作，
# 它是“连上去读”；以后加了会写的动作（如提交端点），不进这张表，命中白名单也照样出卡
READONLY_ACTIONS: dict[str, frozenset[str]] = {"net": frozenset({"connect"})}

RESOURCE_REQUESTABLE: dict[str, tuple[str, frozenset[str]]] = {
    "net": (
        r"^[^\s:/*?\[\]]+:(?:6553[0-5]|655[0-2]\d|65[0-4]\d{2}|6[0-4]\d{3}|[1-5]\d{4}|[1-9]\d{0,3})$",
        frozenset({"connect"}),
    ),
}
