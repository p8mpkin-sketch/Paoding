"""对外契约接口。其它组件只许 import 本模块（ci/check_deps.py 强制）。

评测台是量具（规格 §8 的 T-0）：只产生读数，不驱动任何行为，因此没有被别的组件依赖的被调用接口；
这里再导出评测自己要用的公开名字，供 scripts/ 与测试调用。"""

from .harness import NATIVE_TOOLS, MeteringLedger  # noqa: F401
from .record import MODES, TERMINALS, Record, log_dir_field, run_dirname, stamp  # noqa: F401
from .runner import run_baseline, run_full  # noqa: F401
from .spec import DRYRUN, ProblemSpec, load, sha256_hex  # noqa: F401
