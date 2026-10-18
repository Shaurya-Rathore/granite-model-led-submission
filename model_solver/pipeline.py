"""Public pipeline entrypoint; revisions are selected explicitly."""
from .incremental import ABLATIONS, BUDGETS, STAGES, process_item

# Retained for development replays of the measured v1 traces.
from .legacy_v1.pipeline import reading_signature, unknown, validate_scopes
