from dataclasses import dataclass
from pathlib import Path


@dataclass
class DataLocations:
    """Every real, resolved on-disk path Seeker's data lives at — for
    the Help page's "Where your data lives" section (item 55 §Help).
    All real paths, computed the exact same way Application itself
    resolves them; never a second, drifting copy.
    """
    database_path: Path
    config_path: Path
    spotify_token_path: Path
    slskd_data_dir: Path
    # The one common parent directory all of the above (except
    # slskd_data_dir, which is a subfolder of it) live in — what "Open
    # Data Folder" actually opens.
    base_dir: Path
