from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class SlskdStartResult:
    """What a fresh slskd bring-up generated, so a caller that defers
    persisting (the wizard waits for a confirmed login) saves exactly
    the values the container was started with.
    """
    api_key: str
    download_dir: str


class SlskdDataFolderState(Enum):
    """What slskd finds in the folder mounted as its /app."""

    MISSING = "missing"
    # No slskd.yml: slskd writes a new one and starts with no history.
    FRESH = "fresh"
    # A slskd.yml from an earlier container, beside its state and
    # finished downloads, which slskd carries on with.
    HOLDS_STATE = "holds_state"


@dataclass(frozen=True)
class SlskdStartDefaults:
    """What Settings' Start slskd form opens with: the saved login
    ("" when none), and each folder from the live container first,
    then the last bring-up's record. The data folder falls back to the
    per-user default; the share has none, so a person chooses it.
    """
    username: str
    password: str
    share_path: str | None
    data_dir: str
    data_dir_state: SlskdDataFolderState
