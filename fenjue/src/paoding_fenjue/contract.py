"""paoding_fenjue 对其他组件的契约（EDR-001 D-4：跨组件只经 contract）。"""

from .shapes import (
    SLOTS,
    TOOL_EVENTS,
    active,
    check,
    digest,
    fire,
    fire_digest,
    fire_ids,
    form,
    gongfa,
    gongfa_digest,
    params,
    ref,
)
from .tables import ACTORS, PORTS, SEATS

__all__ = [
    "ACTORS",
    "PORTS",
    "SEATS",
    "SLOTS",
    "TOOL_EVENTS",
    "active",
    "check",
    "digest",
    "fire",
    "fire_digest",
    "fire_ids",
    "form",
    "gongfa",
    "gongfa_digest",
    "params",
    "ref",
]
