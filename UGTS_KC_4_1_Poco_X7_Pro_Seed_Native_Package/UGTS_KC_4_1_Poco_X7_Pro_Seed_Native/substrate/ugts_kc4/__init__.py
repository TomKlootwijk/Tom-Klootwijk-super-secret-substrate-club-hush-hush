"""UGTS-KC 4.0 spatial evidence and topological mapping substrate.

This namespace is additive. The retained :mod:`ugts_kc` and :mod:`ugts_kc3`
packages remain available under their original APIs.
"""
from .canonical import *
from .model import *
from .support import *
from .index import *
from .verify import *
from .topology import *
from .ledger import *
from .change import *
from .project import *
from .export import *
from .templates import *
from .version import (
    __version__, __codename__, __edition__, __schema__, __mechanism_range__,
    __android_status__,
)
