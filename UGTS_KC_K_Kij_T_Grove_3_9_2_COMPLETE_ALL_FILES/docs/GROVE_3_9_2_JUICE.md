# Grove 3.9.2 Juice Layer

The juice layer deliberately makes a major improvement without forcing Mali-G720-specific proprietary APIs. The focused POCO/Mali tier enables stronger post response, while the same pipeline scales down through six quality classes.

Events: jump, land, dash, pickup, hazard, goal.

Visual response: bloom-like threshold glow, flash, chromatic separation, vignette, saturation/contrast lift, pulse and radial shockwave.

Performance strategy: the expensive work is a single GLES 3 fullscreen pass after the existing scene framebuffer; internal render scale and post enablement remain adaptive.
