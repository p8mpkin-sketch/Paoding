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
    form_of,
    gongfa,
    gongfa_digest,
    gongfa_of,
    kernel_config,
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
    "form_of",
    "gongfa",
    "gongfa_digest",
    "gongfa_of",
    "kernel_config",
    "params",
    "ref",
]
