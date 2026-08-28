"""UGTS spatial knowledge-distillation launchpad."""

from .graph import GraphPackage
from .model import UGTSSpatialModel, ModelConfig
from .novelty import NoveltyLog, NoveltyRecord

__all__ = [
    "GraphPackage",
    "UGTSSpatialModel",
    "ModelConfig",
    "NoveltyLog",
    "NoveltyRecord",
]

__version__ = "0.5.0"
