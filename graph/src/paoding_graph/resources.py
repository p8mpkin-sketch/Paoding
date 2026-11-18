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
