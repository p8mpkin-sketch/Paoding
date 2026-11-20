"""书库对外的契约（ci/check_deps.py：别的组件只许 import 这里）。"""

from .embed import EMBEDDERS, Embedder, HashEmbedder, make_embedder
from .parse import MAX_BYTES, Unsupported
from .service import SEARCH_K_MAX, Rejected, Shuku, ShukuConfig
