"""起草（一句话开题）的对外契约接口。其它组件只许 import 本模块（ci/check_deps.py 强制）。"""

from .card import render_card, render_view
from .catalog import Catalog, Form, catalog_of, defaults_catalog, installed_catalog
from .draft import Draft, DraftError, MessagesClient, ModelPort, draft, draft_doc, parse_draft, system
from .extract import Extraction, Span, extract
from .importer import ImportError_, import_vetted
from .ops import batch, blobs
from .policy import DEFAULT_CAPS, Intake, Prior, PriorSource, PriorTableError, Settings, TablePriors, placeholder_priors
from .service import BadRequest, Drafter, KaitiService, Picker, heuristic_drafter, model_drafter
from .vaultio import write_answer
from .vet import ANSWER_SLOT, Note, Vetted, derivation_bytes, override, vet
