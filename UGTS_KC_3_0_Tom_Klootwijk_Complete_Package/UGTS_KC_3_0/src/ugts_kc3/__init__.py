"""UGTS-KC 3.0 reference package.

This package is a bounded, dependency-free engineering extension of the
query-first Unified Geometric-Topological Substrate.  It separates source-derived
mechanisms from engineering additions and keeps projection non-authoritative.
"""

__version__ = "3.0.0"

from .kinematics import JetState
from .uncertainty import Interval, TolerancePolicy

__all__ = ["JetState", "Interval", "TolerancePolicy", "__version__"]
