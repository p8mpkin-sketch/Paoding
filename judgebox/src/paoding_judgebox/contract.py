"""对外契约接口。其它组件只许 import 本模块（ci/check_deps.py 强制）。"""

from .builtin import BUILTINS, Outcome  # noqa: F401
from .connector import (  # noqa: F401
    Connector,
    ConnectorCallError,
    ProfileError,
    SubmissionStore,
    connector_judge,
    connector_plugins,
    validate_profile,
)
from .registry import CONNECTORS_DIR, DEFAULT_DIR, RegistryError, kernel_judges, load_connectors, load_registry  # noqa: F401
from .runner import JudgeConfig, JudgeRunner  # noqa: F401
from .vault import Vault, VaultError  # noqa: F401
