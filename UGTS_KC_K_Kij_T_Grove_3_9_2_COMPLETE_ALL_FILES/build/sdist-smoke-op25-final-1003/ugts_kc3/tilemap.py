"""Tile layers, ASCII import, collision batching and deterministic A* pathfinding."""
from __future__ import annotations

from dataclasses import dataclass, field
import heapq
import math
from typing import Any, Iterable, Mapping, Sequence

from .collision2d import AABB2

Cell = tuple[int, int]


@dataclass(frozen=True)
class TileDefinition:
    id: str
    solid: bool = False
    cost: float = 1.0
    tags: frozenset[str] = frozenset()
    vector_asset: str | None = None

    def validate(self) -> None:
        if not self.id:
            raise ValueError("tile id is required")
        if not math.isfinite(self.cost) or self.cost <= 0:
            raise ValueError("tile traversal cost must be positive and finite")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "solid": self.solid,
            "cost": self.cost,
            "tags": sorted(self.tags),
            "vector_asset": self.vector_asset,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TileDefinition":
        tile = cls(
            str(data["id"]),
            bool(data.get("solid", False)),
            float(data.get("cost", 1.0)),
            frozenset(str(tag) for tag in data.get("tags", [])),
            data.get("vector_asset"),
        )
        tile.validate()
        return tile


@dataclass
class TileLayer:
    name: str
    width: int
    height: int
    tiles: list[str | None]
    visible: bool = True
    collision: bool = False
    z_index: int = 0
    opacity: float = 1.0

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("tile layer name is required")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("tile layer dimensions must be positive")
        if len(self.tiles) != self.width * self.height:
            raise ValueError("tile data length does not match layer dimensions")
        if not 0 <= self.opacity <= 1:
            raise ValueError("tile layer opacity must be in [0, 1]")

    def index(self, cell: Cell) -> int:
        x, y = cell
        if not self.in_bounds(cell):
            raise IndexError(cell)
        return y * self.width + x

    def in_bounds(self, cell: Cell) -> bool:
        x, y = cell
        return 0 <= x < self.width and 0 <= y < self.height

    def get(self, cell: Cell) -> str | None:
        return self.tiles[self.index(cell)]

    def set(self, cell: Cell, tile_id: str | None) -> None:
        self.tiles[self.index(cell)] = tile_id

    def iter_cells(self):
        for y in range(self.height):
            for x in range(self.width):
                yield (x, y), self.tiles[y * self.width + x]

    def to_dict(self) -> dict[str, Any]:
        rows = [self.tiles[y * self.width : (y + 1) * self.width] for y in range(self.height)]
        return {
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "tiles": rows,
            "visible": self.visible,
            "collision": self.collision,
            "z_index": self.z_index,
            "opacity": self.opacity,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TileLayer":
        rows = data["tiles"]
        width = int(data.get("width", len(rows[0]) if rows else 0))
        height = int(data.get("height", len(rows)))
        flat: list[str | None] = []
        if rows and isinstance(rows[0], list):
            if any(len(row) != width for row in rows):
                raise ValueError("tile rows must have equal width")
            flat = [None if value is None else str(value) for row in rows for value in row]
        else:
            flat = [None if value is None else str(value) for value in rows]
        return cls(
            str(data["name"]),
            width,
            height,
            flat,
            bool(data.get("visible", True)),
            bool(data.get("collision", False)),
            int(data.get("z_index", 0)),
            float(data.get("opacity", 1.0)),
        )


class TileMap:
    def __init__(
        self,
        map_id: str,
        width: int,
        height: int,
        tile_size: float = 32.0,
        origin: Sequence[float] = (0.0, 0.0),
        definitions: Iterable[TileDefinition] = (),
        layers: Iterable[TileLayer] = (),
    ):
        if not map_id:
            raise ValueError("tilemap id is required")
        if width <= 0 or height <= 0:
            raise ValueError("tilemap dimensions must be positive")
        if not math.isfinite(tile_size) or tile_size <= 0:
            raise ValueError("tile_size must be positive and finite")
        if len(origin) != 2:
            raise ValueError("origin must have two coordinates")
        self.id = map_id
        self.width = int(width)
        self.height = int(height)
        self.tile_size = float(tile_size)
        self.origin = (float(origin[0]), float(origin[1]))
        self.definitions: dict[str, TileDefinition] = {}
        self.layers: dict[str, TileLayer] = {}
        for definition in definitions:
            self.add_definition(definition)
        for layer in layers:
            self.add_layer(layer)

    @classmethod
    def from_ascii(
        cls,
        map_id: str,
        rows: Sequence[str],
        legend: Mapping[str, str | None],
        definitions: Iterable[TileDefinition],
        *,
        tile_size: float = 32.0,
        layer_name: str = "main",
        collision: bool = True,
        origin: Sequence[float] = (0.0, 0.0),
    ) -> "TileMap":
        if not rows:
            raise ValueError("ASCII tilemap requires rows")
        width = len(rows[0])
        if width == 0 or any(len(row) != width for row in rows):
            raise ValueError("ASCII tilemap rows must be non-empty and equal width")
        tiles: list[str | None] = []
        for row in rows:
            for character in row:
                if character not in legend:
                    raise KeyError(f"character {character!r} missing from tile legend")
                tiles.append(legend[character])
        layer = TileLayer(layer_name, width, len(rows), tiles, collision=collision)
        return cls(map_id, width, len(rows), tile_size, origin, definitions, (layer,))

    def add_definition(self, definition: TileDefinition, replace_existing: bool = False) -> None:
        definition.validate()
        if definition.id in self.definitions and not replace_existing:
            raise ValueError(f"tile definition already exists: {definition.id}")
        self.definitions[definition.id] = definition

    def add_layer(self, layer: TileLayer, replace_existing: bool = False) -> None:
        if layer.width != self.width or layer.height != self.height:
            raise ValueError("tile layer dimensions must match tilemap")
        unknown = sorted({tile_id for tile_id in layer.tiles if tile_id is not None and tile_id not in self.definitions})
        if unknown:
            raise KeyError(f"unknown tile definitions: {', '.join(unknown)}")
        if layer.name in self.layers and not replace_existing:
            raise ValueError(f"tile layer already exists: {layer.name}")
        self.layers[layer.name] = layer

    def in_bounds(self, cell: Cell) -> bool:
        x, y = cell
        return 0 <= x < self.width and 0 <= y < self.height

    def world_to_cell(self, point: Sequence[float]) -> Cell:
        return (
            math.floor((float(point[0]) - self.origin[0]) / self.tile_size),
            math.floor((float(point[1]) - self.origin[1]) / self.tile_size),
        )

    def cell_to_world(self, cell: Cell, center: bool = True) -> tuple[float, float]:
        x, y = cell
        offset = 0.5 if center else 0.0
        return self.origin[0] + (x + offset) * self.tile_size, self.origin[1] + (y + offset) * self.tile_size

    def cell_bounds(self, cell: Cell) -> AABB2:
        minimum = self.cell_to_world(cell, center=False)
        return AABB2(minimum, (minimum[0] + self.tile_size, minimum[1] + self.tile_size))

    def tile_id(self, layer_name: str, cell: Cell) -> str | None:
        return self.layers[layer_name].get(cell)

    def definition_at(self, layer_name: str, cell: Cell) -> TileDefinition | None:
        tile_id = self.tile_id(layer_name, cell)
        return None if tile_id is None else self.definitions[tile_id]

    def is_solid(self, cell: Cell, layer_names: Iterable[str] | None = None, out_of_bounds_solid: bool = True) -> bool:
        if not self.in_bounds(cell):
            return out_of_bounds_solid
        names = tuple(layer_names) if layer_names is not None else tuple(name for name, layer in self.layers.items() if layer.collision)
        for name in names:
            definition = self.definition_at(name, cell)
            if definition is not None and definition.solid:
                return True
        return False

    def traversal_cost(self, cell: Cell, layer_names: Iterable[str] | None = None) -> float:
        if not self.in_bounds(cell) or self.is_solid(cell, layer_names):
            return math.inf
        names = tuple(layer_names) if layer_names is not None else tuple(self.layers)
        costs = [self.definition_at(name, cell).cost for name in names if self.definition_at(name, cell) is not None]
        return max(costs, default=1.0)

    def neighbors(self, cell: Cell, diagonal: bool = False) -> tuple[Cell, ...]:
        x, y = cell
        offsets = [(1, 0), (-1, 0), (0, 1), (0, -1)]
        if diagonal:
            offsets.extend([(1, 1), (1, -1), (-1, 1), (-1, -1)])
        result: list[Cell] = []
        for dx, dy in offsets:
            candidate = (x + dx, y + dy)
            if self.in_bounds(candidate) and not self.is_solid(candidate):
                if diagonal and dx and dy and (self.is_solid((x + dx, y)) or self.is_solid((x, y + dy))):
                    continue
                result.append(candidate)
        return tuple(sorted(result))

    def find_path(self, start: Cell, goal: Cell, diagonal: bool = False, max_nodes: int = 100_000) -> tuple[Cell, ...]:
        if not self.in_bounds(start) or not self.in_bounds(goal):
            raise ValueError("path endpoints must be inside the tilemap")
        if self.is_solid(start) or self.is_solid(goal):
            return ()
        if start == goal:
            return (start,)

        def heuristic(cell: Cell) -> float:
            dx, dy = abs(cell[0] - goal[0]), abs(cell[1] - goal[1])
            return max(dx, dy) if diagonal else dx + dy

        frontier: list[tuple[float, float, Cell]] = [(heuristic(start), 0.0, start)]
        came_from: dict[Cell, Cell | None] = {start: None}
        cost_so_far: dict[Cell, float] = {start: 0.0}
        visited = 0
        while frontier:
            _, cost, current = heapq.heappop(frontier)
            if cost > cost_so_far.get(current, math.inf) + 1.0e-12:
                continue
            visited += 1
            if visited > max_nodes:
                raise RuntimeError("pathfinding node budget exceeded")
            if current == goal:
                break
            for neighbor in self.neighbors(current, diagonal):
                diagonal_step = neighbor[0] != current[0] and neighbor[1] != current[1]
                move_cost = (math.sqrt(2.0) if diagonal_step else 1.0) * self.traversal_cost(neighbor)
                new_cost = cost_so_far[current] + move_cost
                if new_cost < cost_so_far.get(neighbor, math.inf):
                    cost_so_far[neighbor] = new_cost
                    came_from[neighbor] = current
                    heapq.heappush(frontier, (new_cost + heuristic(neighbor), new_cost, neighbor))
        if goal not in came_from:
            return ()
        path: list[Cell] = []
        current: Cell | None = goal
        while current is not None:
            path.append(current)
            current = came_from[current]
        return tuple(reversed(path))

    def flood_fill(self, start: Cell, limit: int | None = None) -> tuple[Cell, ...]:
        if not self.in_bounds(start) or self.is_solid(start):
            return ()
        queue = [start]
        visited = {start}
        while queue and (limit is None or len(visited) < limit):
            current = queue.pop(0)
            for neighbor in self.neighbors(current):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
                    if limit is not None and len(visited) >= limit:
                        break
        return tuple(sorted(visited))

    def collision_boxes(self, layer_names: Iterable[str] | None = None) -> tuple[AABB2, ...]:
        """Merge solid cells into deterministic rectangles to reduce collider count."""
        names = tuple(layer_names) if layer_names is not None else tuple(name for name, layer in self.layers.items() if layer.collision)
        solid = {(x, y) for y in range(self.height) for x in range(self.width) if self.is_solid((x, y), names, False)}
        boxes: list[AABB2] = []
        while solid:
            x0, y0 = min(solid, key=lambda cell: (cell[1], cell[0]))
            x1 = x0
            while (x1 + 1, y0) in solid:
                x1 += 1
            y1 = y0
            while all((x, y1 + 1) in solid for x in range(x0, x1 + 1)):
                y1 += 1
            for y in range(y0, y1 + 1):
                for x in range(x0, x1 + 1):
                    solid.remove((x, y))
            minimum = self.cell_to_world((x0, y0), center=False)
            maximum = self.cell_to_world((x1 + 1, y1 + 1), center=False)
            boxes.append(AABB2(minimum, maximum))
        return tuple(boxes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "width": self.width,
            "height": self.height,
            "tile_size": self.tile_size,
            "origin": list(self.origin),
            "definitions": [self.definitions[name].to_dict() for name in sorted(self.definitions)],
            "layers": [self.layers[name].to_dict() for name in sorted(self.layers, key=lambda name: (self.layers[name].z_index, name))],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TileMap":
        definitions = [TileDefinition.from_dict(item) for item in data.get("definitions", [])]
        layers = [TileLayer.from_dict(item) for item in data.get("layers", [])]
        return cls(
            str(data["id"]),
            int(data["width"]),
            int(data["height"]),
            float(data.get("tile_size", 32.0)),
            data.get("origin", (0, 0)),
            definitions,
            layers,
        )
