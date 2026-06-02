"""fitrelief — turn a Garmin FIT activity into a 3D-printable terrain relief tile."""
from .config import TileConfig, auto_labels, load_yaml, merge
from .pipeline import build_tile

__all__ = ["TileConfig", "auto_labels", "load_yaml", "merge", "build_tile"]
