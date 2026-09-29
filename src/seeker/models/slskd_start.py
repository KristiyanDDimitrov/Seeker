from dataclasses import dataclass


@dataclass(frozen=True)
class SlskdStartResult:
    """What a fresh slskd bring-up generated, so a caller that defers
    persisting (the wizard waits for a confirmed login) saves exactly
    the values the container was started with.
    """
    api_key: str
    download_dir: str
