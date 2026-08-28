"""UGTS-KC 3.9.1 — Tom Klootwijk Signature vector, game and native-mobile runtime.

The original 3.0 scene/geometry/two-hand/replay API remains import-compatible.
Version 3.9 adds the practical 2D stack; 3.9.1 adds a mobile-3D model and native Android source exporter.
"""
from .math3d import *
from .geometry import *
from .spatial import *
from .materials import *
from .scene import *
from .hands import *
from .runtime import *
from .replay import *
from .render import *
from .export import *
from .diagnostics import *

from .vector2d import *
from .collision2d import *
from .game_input import *
from .animation import *
from .tilemap import *
from .audio import *
from .game import *
from .project import *
from .webexport import *
from .templates import *
from .mobile3d import *
from .templates3d import *
from .androidexport import *
from .version import (__version__, __codename__, __edition__, __game_project_schema__,
    __mobile3d_schema__, __native_scene_pack__)
