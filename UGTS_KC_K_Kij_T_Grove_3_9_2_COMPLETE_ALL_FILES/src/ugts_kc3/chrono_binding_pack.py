"""Sparse editable-scene bindings for the native chrono substrate runtime.

``KCCH392`` is an optional sidecar keyed by the canonical ``KC3D392`` node
index.  It leaves the established scene-node ABI untouched: an ordinary,
editable :class:`~ugts_kc3.mobile3d.Node3DRecord` owns each binding through
metadata, while Android consumes a compact native record.

The binding is deliberately not an observation container.  A root seed
regenerates GSP4 traversal/program state; arbitrary camera samples remain exact
novelty evidence in the referenced or newly recorded seed stream.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from numbers import Real
from pathlib import Path, PurePosixPath
import re
import struct
from typing import Any, Mapping

from .gsp4_camera_codeword import (
    AUTHORITY as GSP4_CAMERA_AUTHORITY,
    PIXEL_PROFILE as GSP4_CAMERA_PIXEL_PROFILE,
)
from .packed_kinematics import LogPolarProfile, PolarLookupTable


CHRONO_BINDING_METADATA_KEY = "chrono_substrate_binding"
CHRONO_BINDING_SCHEMA = "ugts-kc-chrono-substrate-binding-3.9.2"
CHRONO_BINDING_PACK_ASSET = "chrono_bindings.kcch"
CHRONO_BINDING_PACK_MAGIC = b"KCCH392\0"
CHRONO_BINDING_PACK_ENDIAN = 0x01020304
CHRONO_BINDING_PACK_VERSION = 1
CHRONO_BINDING_HEADER_BYTES = 64
CHRONO_BINDING_RECORD_BYTES = 176
MAX_CHRONO_BINDINGS = 64
MAX_CHRONO_STRING_BYTES = 65_535

MODE_RECORDER = "RECORDER"
MODE_PLAYER = "PLAYER"
PIXEL_PROFILE = GSP4_CAMERA_PIXEL_PROFILE
STORAGE_APP_PRIVATE = "APP_PRIVATE_GSP4_SEED"
STORAGE_PACKAGED = "PACKAGED_GSP4_SEED"
AUTHORITY = GSP4_CAMERA_AUTHORITY
NOVELTY_POLICY = "EXACT_RESIDUAL_REQUIRED"
GEOMETRY_STATUS = "UNKNOWN"

_MODE_CODES = {MODE_RECORDER: 1, MODE_PLAYER: 2}
_MODE_NAMES = {value: key for key, value in _MODE_CODES.items()}
_PIXEL_PROFILE_CODE = 1
_STORAGE_CODES = {STORAGE_APP_PRIVATE: 1, STORAGE_PACKAGED: 2}
_STORAGE_NAMES = {value: key for key, value in _STORAGE_CODES.items()}
_AUTHORITY_CODE = 1
_NOVELTY_CODE = 1
_GEOMETRY_CODE = 1
_GSP4_SEED_MAGIC = b"UGYUVS1\0"

_HEADER = struct.Struct("<8sIHHIIII32s")
_RECORD = struct.Struct("<I8B2I4H2Q4d32sQ32sIHHIHHIHHI")
_DIGEST_OFFSET = 32
_SAFE_CAMERA_ID = re.compile(r"[A-Za-z0-9._:-]{1,64}\Z")
_SAFE_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,126}\.ugsp4c\Z")
_SAFE_ASSET_PATH = re.compile(r"[A-Za-z0-9._/-]+\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_COMMON_KEYS = frozenset(
    {
        "schema",
        "mode",
        "width",
        "height",
        "fps",
        "queue_slots",
        "pixel_profile",
        "root_seed_u64",
        "recipe_seed_u64",
        "uglut2",
        "storage_policy",
        "novelty_policy",
        "authority",
        "autostart",
        "geometry_status",
    }
)
_UGLUT_KEYS = frozenset(
    {"resolution", "r0", "rho_min", "rho_max", "core_radius", "sha256"}
)
_SOURCE_ASSET_KEYS = frozenset({"path", "bytes", "sha256"})

if _HEADER.size != CHRONO_BINDING_HEADER_BYTES:  # pragma: no cover
    raise RuntimeError("KCCH392 header layout is not exactly 64 bytes")
if _RECORD.size != CHRONO_BINDING_RECORD_BYTES:  # pragma: no cover
    raise RuntimeError("KCCH392 record layout is not exactly 176 bytes")


class ChronoBindingPackError(ValueError):
    """Invalid authored chrono binding or malformed KCCH392 bytes."""


@dataclass(frozen=True)
class ChronoNodeBinding:
    """One validated, node-indexed chrono recorder or player binding."""

    node_index: int
    mode: str
    width: int
    height: int
    fps: int
    queue_slots: int
    root_seed_u64: int
    recipe_seed_u64: int
    uglut2_resolution: int
    uglut2_r0: float
    uglut2_rho_min: float
    uglut2_rho_max: float
    uglut2_core_radius: float
    uglut2_sha256: str
    storage_policy: str
    camera_id: str = ""
    output_name: str = ""
    input_name: str = ""
    source_asset_path: str = ""
    source_asset_bytes: int = 0
    source_asset_sha256: str = ""
    pixel_profile: str = PIXEL_PROFILE
    novelty_policy: str = NOVELTY_POLICY
    authority: str = AUTHORITY
    autostart: bool = False
    geometry_status: str = GEOMETRY_STATUS

    @property
    def packaged_asset_path(self) -> str:
        if not self.source_asset_path:
            return ""
        return f"chrono/{self.source_asset_path}"

    @property
    def uglut2_profile(self) -> LogPolarProfile:
        return LogPolarProfile(
            self.uglut2_r0,
            self.uglut2_rho_min,
            self.uglut2_rho_max,
            self.uglut2_core_radius,
        )

    def validate(self) -> None:
        _integer(self.node_index, "node_index", 0, 0xFFFFFFFF)
        if not isinstance(self.mode, str) or self.mode not in _MODE_CODES:
            raise ChronoBindingPackError("chrono mode must be RECORDER or PLAYER")
        _integer(self.width, "width", 2, 65_534)
        _integer(self.height, "height", 2, 65_534)
        if self.width & 1 or self.height & 1:
            raise ChronoBindingPackError(
                "UGCODE24-420 camera width and height must be even"
            )
        if self.width * self.height > 1 << 30:
            raise ChronoBindingPackError("chrono raster exceeds the UGTRV1 pixel limit")
        _integer(self.fps, "fps", 1, 240)
        _integer(self.queue_slots, "queue_slots", 3, 16)
        _uint64(self.root_seed_u64, "root_seed_u64")
        _uint64(self.recipe_seed_u64, "recipe_seed_u64")
        if self.recipe_seed_u64 != 1:
            raise ChronoBindingPackError(
                "KCCH392 v1 fixes recipe_seed_u64 to the profile constant 1"
            )
        _integer(self.uglut2_resolution, "uglut2.resolution", 16, 4096)
        if self.uglut2_resolution & (self.uglut2_resolution - 1):
            raise ChronoBindingPackError(
                "uglut2.resolution must be a power of two for UGTRV1"
            )
        try:
            profile = self.uglut2_profile
        except (TypeError, ValueError) as exc:
            raise ChronoBindingPackError(f"invalid UGLUT2 profile: {exc}") from exc
        for label, value in (
            ("uglut2.r0", profile.r0),
            ("uglut2.rho_min", profile.rho_min),
            ("uglut2.rho_max", profile.rho_max),
            ("uglut2.core_radius", profile.core_radius),
        ):
            if not math.isfinite(value) or (
                value == 0.0 and math.copysign(1.0, value) < 0.0
            ):
                raise ChronoBindingPackError(
                    f"{label} must be canonical finite binary64"
                )
        lut_bytes = PolarLookupTable.generate(
            profile, self.uglut2_resolution
        ).to_bytes()
        radius_scale = struct.unpack_from("<6sHddddd", lut_bytes)[-1]
        if radius_scale != 1.0:
            raise ChronoBindingPackError(
                "KCCH392 UGTRV1 requires exact unit UGLUT2 radius scale"
            )
        expected_lut_hash = hashlib.sha256(lut_bytes).hexdigest()
        _sha256(self.uglut2_sha256, "uglut2.sha256")
        if self.uglut2_sha256 != expected_lut_hash:
            raise ChronoBindingPackError(
                "uglut2.sha256 does not match the canonical profile preimage"
            )
        if (
            not isinstance(self.pixel_profile, str)
            or self.pixel_profile != PIXEL_PROFILE
        ):
            raise ChronoBindingPackError(f"pixel_profile must be {PIXEL_PROFILE}")
        if (
            not isinstance(self.novelty_policy, str)
            or self.novelty_policy != NOVELTY_POLICY
        ):
            raise ChronoBindingPackError(f"novelty_policy must be {NOVELTY_POLICY}")
        if not isinstance(self.authority, str) or self.authority != AUTHORITY:
            raise ChronoBindingPackError(f"authority must be {AUTHORITY}")
        if not isinstance(self.autostart, bool):
            raise ChronoBindingPackError(
                "autostart must be an editable boolean node property"
            )
        if (
            not isinstance(self.geometry_status, str)
            or self.geometry_status != GEOMETRY_STATUS
        ):
            raise ChronoBindingPackError(
                "geometry_status must remain UNKNOWN until evidence promotes it"
            )
        if self.mode == MODE_RECORDER:
            if self.storage_policy != STORAGE_APP_PRIVATE:
                raise ChronoBindingPackError(
                    "RECORDER requires APP_PRIVATE_GSP4_SEED storage"
                )
            if not isinstance(self.camera_id, str) or not _SAFE_CAMERA_ID.fullmatch(
                self.camera_id
            ):
                raise ChronoBindingPackError(
                    "RECORDER camera_id must be 1..64 portable Camera2 characters"
                )
            if not isinstance(self.output_name, str) or not _SAFE_FILENAME.fullmatch(
                self.output_name
            ):
                raise ChronoBindingPackError(
                    "RECORDER output_name must be a portable .ugsp4c basename"
                )
            if (
                self.input_name
                or self.source_asset_path
                or self.source_asset_bytes
                or self.source_asset_sha256
            ):
                raise ChronoBindingPackError(
                    "RECORDER cannot bind a packaged source asset"
                )
        else:
            if self.camera_id or self.output_name:
                raise ChronoBindingPackError(
                    "PLAYER cannot own Camera2 or an app-private output name"
                )
            if self.storage_policy == STORAGE_APP_PRIVATE:
                if not isinstance(self.input_name, str) or not _SAFE_FILENAME.fullmatch(
                    self.input_name
                ):
                    raise ChronoBindingPackError(
                        "app-private PLAYER input_name must be a portable .ugsp4c basename"
                    )
                if (
                    self.source_asset_path
                    or self.source_asset_bytes
                    or self.source_asset_sha256
                ):
                    raise ChronoBindingPackError(
                        "app-private PLAYER cannot bind a packaged source asset"
                    )
            elif self.storage_policy == STORAGE_PACKAGED:
                if self.input_name:
                    raise ChronoBindingPackError(
                        "packaged PLAYER cannot bind an app-private input_name"
                    )
                _asset_path(self.source_asset_path)
                _integer(
                    self.source_asset_bytes,
                    "source_asset.bytes",
                    8,
                    (1 << 64) - 1,
                )
                _sha256(self.source_asset_sha256, "source_asset.sha256")
            else:
                raise ChronoBindingPackError(
                    "PLAYER storage must be APP_PRIVATE_GSP4_SEED or PACKAGED_GSP4_SEED"
                )


@dataclass(frozen=True)
class ResolvedChronoAsset:
    """A verified authoring source and its packaged Android asset path."""

    source: Path
    source_relative_path: str
    packaged_path: str
    byte_count: int
    sha256: str


def _integer(value: object, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ChronoBindingPackError(f"{label} must be an integer")
    if not minimum <= value <= maximum:
        raise ChronoBindingPackError(f"{label} must be between {minimum} and {maximum}")
    return value


def _uint64(value: object, label: str) -> int:
    return _integer(value, label, 0, (1 << 64) - 1)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ChronoBindingPackError(f"{label} must be text")
    return value


def _finite_float(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ChronoBindingPackError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ChronoBindingPackError(f"{label} must be a finite number")
    return result


def _sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ChronoBindingPackError(f"{label} must be lowercase 64-digit SHA-256 hex")
    return value


def _asset_path(value: object) -> str:
    if not isinstance(value, str) or not _SAFE_ASSET_PATH.fullmatch(value):
        raise ChronoBindingPackError(
            "source_asset.path must use portable ASCII asset characters"
        )
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or value != path.as_posix()
        or not path.parts
        or any(part in ("", ".", "..") for part in path.parts)
        or path.suffix.lower() != ".ugsp4c"
    ):
        raise ChronoBindingPackError(
            "source_asset.path must be a canonical relative GSP4 seed-stream path"
        )
    return value


def canonical_uglut2_descriptor(
    profile: LogPolarProfile, resolution: int = 16
) -> dict[str, Any]:
    """Return the strict metadata preimage and digest for one UGLUT2 table."""

    _integer(resolution, "uglut2.resolution", 16, 4096)
    if resolution & (resolution - 1):
        raise ChronoBindingPackError("uglut2.resolution must be a power of two")
    data = PolarLookupTable.generate(profile, resolution).to_bytes()
    radius_scale = struct.unpack_from("<6sHddddd", data)[-1]
    if radius_scale != 1.0:
        raise ChronoBindingPackError(
            "KCCH392 UGTRV1 requires exact unit UGLUT2 radius scale"
        )
    return {
        "resolution": resolution,
        **profile.to_dict(),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _exact_keys(raw: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
    actual = set(raw)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    details = []
    if missing:
        details.append("missing " + ", ".join(missing))
    if unknown:
        details.append("unknown " + ", ".join(unknown))
    raise ChronoBindingPackError(
        f"{label} fields are not canonical: {'; '.join(details)}"
    )


def chrono_binding_from_metadata(
    metadata: Mapping[str, Any], node_index: int
) -> ChronoNodeBinding | None:
    """Parse one optional ordinary-node metadata component strictly."""

    if CHRONO_BINDING_METADATA_KEY not in metadata:
        return None
    raw = metadata[CHRONO_BINDING_METADATA_KEY]
    if not isinstance(raw, Mapping):
        raise ChronoBindingPackError(
            f"node metadata.{CHRONO_BINDING_METADATA_KEY} must be an object"
        )
    mode = raw.get("mode")
    if mode == MODE_RECORDER:
        expected = _COMMON_KEYS | {"camera_id", "output_name"}
    elif mode == MODE_PLAYER:
        if raw.get("storage_policy") == STORAGE_APP_PRIVATE:
            expected = _COMMON_KEYS | {"input_name"}
        elif raw.get("storage_policy") == STORAGE_PACKAGED:
            expected = _COMMON_KEYS | {"source_asset"}
        else:
            raise ChronoBindingPackError(
                "PLAYER storage must be APP_PRIVATE_GSP4_SEED or PACKAGED_GSP4_SEED"
            )
    else:
        raise ChronoBindingPackError("chrono mode must be RECORDER or PLAYER")
    _exact_keys(raw, frozenset(expected), CHRONO_BINDING_METADATA_KEY)
    if raw["schema"] != CHRONO_BINDING_SCHEMA:
        raise ChronoBindingPackError(
            f"chrono binding schema must be {CHRONO_BINDING_SCHEMA}"
        )
    uglut = raw["uglut2"]
    if not isinstance(uglut, Mapping):
        raise ChronoBindingPackError("uglut2 must be an object")
    _exact_keys(uglut, _UGLUT_KEYS, "uglut2")
    try:
        profile = LogPolarProfile(
            _finite_float(uglut["r0"], "uglut2.r0"),
            _finite_float(uglut["rho_min"], "uglut2.rho_min"),
            _finite_float(uglut["rho_max"], "uglut2.rho_max"),
            _finite_float(uglut["core_radius"], "uglut2.core_radius"),
        )
    except (TypeError, ValueError) as exc:
        raise ChronoBindingPackError(f"invalid UGLUT2 profile: {exc}") from exc

    source_path = ""
    source_bytes = 0
    source_hash = ""
    if mode == MODE_PLAYER and raw["storage_policy"] == STORAGE_PACKAGED:
        source = raw["source_asset"]
        if not isinstance(source, Mapping):
            raise ChronoBindingPackError("source_asset must be an object")
        _exact_keys(source, _SOURCE_ASSET_KEYS, "source_asset")
        source_path = _asset_path(source["path"])
        source_bytes = _integer(source["bytes"], "source_asset.bytes", 8, (1 << 64) - 1)
        source_hash = _sha256(source["sha256"], "source_asset.sha256")

    binding = ChronoNodeBinding(
        node_index=_integer(node_index, "node_index", 0, 0xFFFFFFFF),
        mode=_text(mode, "mode"),
        width=_integer(raw["width"], "width", 2, 65_534),
        height=_integer(raw["height"], "height", 2, 65_534),
        fps=_integer(raw["fps"], "fps", 1, 240),
        queue_slots=_integer(raw["queue_slots"], "queue_slots", 3, 16),
        root_seed_u64=_uint64(raw["root_seed_u64"], "root_seed_u64"),
        recipe_seed_u64=_uint64(raw["recipe_seed_u64"], "recipe_seed_u64"),
        uglut2_resolution=_integer(uglut["resolution"], "uglut2.resolution", 16, 4096),
        uglut2_r0=profile.r0,
        uglut2_rho_min=profile.rho_min,
        uglut2_rho_max=profile.rho_max,
        uglut2_core_radius=profile.core_radius,
        uglut2_sha256=_sha256(uglut["sha256"], "uglut2.sha256"),
        storage_policy=_text(raw["storage_policy"], "storage_policy"),
        camera_id=_text(raw.get("camera_id", ""), "camera_id"),
        output_name=_text(raw.get("output_name", ""), "output_name"),
        input_name=_text(raw.get("input_name", ""), "input_name"),
        source_asset_path=source_path,
        source_asset_bytes=source_bytes,
        source_asset_sha256=source_hash,
        pixel_profile=_text(raw["pixel_profile"], "pixel_profile"),
        novelty_policy=_text(raw["novelty_policy"], "novelty_policy"),
        authority=_text(raw["authority"], "authority"),
        autostart=raw["autostart"],
        geometry_status=_text(raw["geometry_status"], "geometry_status"),
    )
    binding.validate()
    return binding


def metadata_with_chrono_binding(
    metadata: Mapping[str, Any], binding: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Return copied node metadata with a validated editable binding attached."""

    result = dict(metadata)
    if binding is None:
        result.pop(CHRONO_BINDING_METADATA_KEY, None)
        return result
    result[CHRONO_BINDING_METADATA_KEY] = dict(binding)
    chrono_binding_from_metadata(result, 0)
    return result


def _materialized_project(project: Any) -> Any:
    metadata = getattr(project, "metadata", {})
    if not isinstance(metadata, Mapping) or not any(
        key in metadata for key in ("saved_scenes", "saved_scene_instances")
    ):
        return project
    from .saved_scene import materialize_saved_scenes

    return materialize_saved_scenes(project)


def collect_chrono_bindings(
    project: Any, *, materialize: bool = True
) -> tuple[ChronoNodeBinding, ...]:
    """Collect strict sparse bindings in canonical KC3D node-index order."""

    if materialize:
        project = _materialized_project(project)
    nodes = tuple(getattr(project, "nodes", ()))
    bindings: list[ChronoNodeBinding] = []
    for node_index, node in enumerate(nodes):
        metadata = getattr(node, "metadata", None)
        if not isinstance(metadata, Mapping):
            continue
        binding = chrono_binding_from_metadata(metadata, node_index)
        if binding is None:
            continue
        if bool(getattr(node, "dynamic", False)):
            raise ChronoBindingPackError(
                f"chrono node {node_index} must not be a dynamic physics writer"
            )
        collider = getattr(node, "collider", None)
        if getattr(collider, "shape", "none") != "none":
            raise ChronoBindingPackError(
                f"chrono node {node_index} must use a non-physical collider"
            )
        if any(float(value) != 0.0 for value in getattr(node, "velocity", ())):
            raise ChronoBindingPackError(
                f"chrono node {node_index} must not have linear velocity"
            )
        if any(float(value) != 0.0 for value in getattr(node, "angular_velocity", ())):
            raise ChronoBindingPackError(
                f"chrono node {node_index} must not have angular velocity"
            )
        bindings.append(binding)
    if len(bindings) > MAX_CHRONO_BINDINGS:
        raise ChronoBindingPackError(
            f"KCCH392 supports at most {MAX_CHRONO_BINDINGS} sparse bindings"
        )
    recorders = [binding for binding in bindings if binding.mode == MODE_RECORDER]
    if len(recorders) > 1:
        raise ChronoBindingPackError(
            "KCCH392 v1 permits only one Camera2 recorder owner"
        )
    app_private_players = [
        binding
        for binding in bindings
        if binding.mode == MODE_PLAYER
        and binding.storage_policy == STORAGE_APP_PRIVATE
    ]
    if app_private_players:
        if len(recorders) != 1:
            raise ChronoBindingPackError(
                "app-private PLAYER requires exactly one RECORDER owner"
            )
        output_name = recorders[0].output_name
        if any(binding.input_name != output_name for binding in app_private_players):
            raise ChronoBindingPackError(
                "app-private PLAYER input_name must match the RECORDER output_name"
            )
    folded_assets: set[str] = set()
    for binding in bindings:
        if not binding.source_asset_path:
            continue
        folded = binding.source_asset_path.casefold()
        if folded in folded_assets:
            raise ChronoBindingPackError(
                "PLAYER source assets must not duplicate or case-collide"
            )
        folded_assets.add(folded)
    return tuple(bindings)


def _string_ref(
    text: str, table: bytearray, known: dict[str, tuple[int, int]]
) -> tuple[int, int, int]:
    if not text:
        return 0, 0, 0
    if text in known:
        offset, length = known[text]
        return offset, length, 0
    encoded = text.encode("utf-8")
    if not encoded or len(encoded) > MAX_CHRONO_STRING_BYTES:
        raise ChronoBindingPackError("KCCH392 string exceeds its uint16 limit")
    if len(table) + len(encoded) > 0xFFFFFFFF:
        raise ChronoBindingPackError("KCCH392 string table exceeds uint32")
    offset = len(table)
    table.extend(encoded)
    known[text] = (offset, len(encoded))
    return offset, len(encoded), 0


def _encode_bindings(bindings: tuple[ChronoNodeBinding, ...]) -> bytes:
    if not bindings:
        return b""
    table = bytearray()
    known: dict[str, tuple[int, int]] = {}
    records = bytearray()
    previous_index = -1
    for binding in bindings:
        binding.validate()
        if binding.node_index <= previous_index:
            raise ChronoBindingPackError(
                "KCCH392 node indices must be strictly increasing"
            )
        previous_index = binding.node_index
        camera_ref = _string_ref(binding.camera_id, table, known)
        stream_name = (
            binding.output_name if binding.mode == MODE_RECORDER else binding.input_name
        )
        output_ref = _string_ref(stream_name, table, known)
        asset_ref = _string_ref(binding.packaged_asset_path, table, known)
        asset_hash = (
            bytes.fromhex(binding.source_asset_sha256)
            if binding.source_asset_sha256
            else bytes(32)
        )
        records.extend(
            _RECORD.pack(
                binding.node_index,
                _MODE_CODES[binding.mode],
                _PIXEL_PROFILE_CODE,
                _STORAGE_CODES[binding.storage_policy],
                _AUTHORITY_CODE,
                _NOVELTY_CODE,
                _GEOMETRY_CODE,
                int(binding.autostart),
                0,
                binding.width,
                binding.height,
                binding.fps,
                binding.fps,
                binding.queue_slots,
                binding.uglut2_resolution,
                binding.root_seed_u64,
                binding.recipe_seed_u64,
                binding.uglut2_r0,
                binding.uglut2_rho_min,
                binding.uglut2_rho_max,
                binding.uglut2_core_radius,
                bytes.fromhex(binding.uglut2_sha256),
                binding.source_asset_bytes,
                asset_hash,
                *camera_ref,
                *output_ref,
                *asset_ref,
                0,
            )
        )
    header = _HEADER.pack(
        CHRONO_BINDING_PACK_MAGIC,
        CHRONO_BINDING_PACK_ENDIAN,
        CHRONO_BINDING_PACK_VERSION,
        CHRONO_BINDING_HEADER_BYTES,
        len(bindings),
        CHRONO_BINDING_RECORD_BYTES,
        len(table),
        0,
        bytes(32),
    )
    output = bytearray(header + records + table)
    digest = hashlib.sha256(output).digest()
    output[_DIGEST_OFFSET : _DIGEST_OFFSET + 32] = digest
    return bytes(output)


def compile_chrono_binding_pack_bytes(project: Any) -> bytes:
    """Compile optional editable node bindings, or return ``b''`` when unused."""

    return _encode_bindings(collect_chrono_bindings(project))


def write_chrono_binding_pack(project: Any, path: str | Path) -> Path | None:
    """Write the optional KCCH392 sidecar without changing KC3D392."""

    data = compile_chrono_binding_pack_bytes(project)
    if not data:
        return None
    result = Path(path)
    result.parent.mkdir(parents=True, exist_ok=True)
    result.write_bytes(data)
    return result


def _decode_string(
    table: bytes, offset: int, length: int, reserved: int, label: str
) -> str:
    if reserved:
        raise ChronoBindingPackError(
            f"{label} string reference reserved field is nonzero"
        )
    if length == 0:
        if offset != 0:
            raise ChronoBindingPackError(f"{label} empty string offset is nonzero")
        return ""
    end = offset + length
    if end > len(table):
        raise ChronoBindingPackError(f"{label} string reference is out of range")
    try:
        return table[offset:end].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ChronoBindingPackError(f"{label} string is not UTF-8") from exc


def inspect_chrono_binding_pack(
    data_or_path: bytes | str | Path, *, node_count: int | None = None
) -> dict[str, Any]:
    """Strictly inspect layout, semantic invariants and canonical string packing."""

    data = (
        Path(data_or_path).read_bytes()
        if isinstance(data_or_path, (str, Path))
        else bytes(data_or_path)
    )
    if len(data) < CHRONO_BINDING_HEADER_BYTES:
        raise ChronoBindingPackError("KCCH392 asset is truncated before its header")
    (
        magic,
        endian,
        version,
        header_bytes,
        record_count,
        record_bytes,
        string_bytes,
        flags,
        content_digest,
    ) = _HEADER.unpack_from(data)
    if magic != CHRONO_BINDING_PACK_MAGIC:
        raise ChronoBindingPackError("KCCH392 magic mismatch")
    if endian != CHRONO_BINDING_PACK_ENDIAN:
        raise ChronoBindingPackError("KCCH392 endian marker mismatch")
    if version != CHRONO_BINDING_PACK_VERSION:
        raise ChronoBindingPackError("unsupported KCCH392 version")
    if header_bytes != CHRONO_BINDING_HEADER_BYTES:
        raise ChronoBindingPackError("KCCH392 header size mismatch")
    if record_bytes != CHRONO_BINDING_RECORD_BYTES:
        raise ChronoBindingPackError("KCCH392 record size mismatch")
    if not 1 <= record_count <= MAX_CHRONO_BINDINGS:
        raise ChronoBindingPackError("empty or oversized KCCH392 asset")
    if flags:
        raise ChronoBindingPackError("KCCH392 header flags are nonzero")
    expected = header_bytes + record_count * record_bytes + string_bytes
    if len(data) != expected:
        raise ChronoBindingPackError("KCCH392 byte length disagrees with its header")
    unsigned = bytearray(data)
    unsigned[_DIGEST_OFFSET : _DIGEST_OFFSET + 32] = bytes(32)
    if hashlib.sha256(unsigned).digest() != content_digest:
        raise ChronoBindingPackError("KCCH392 content SHA-256 mismatch")
    if node_count is not None:
        _integer(node_count, "node_count", 0, 0xFFFFFFFF)

    table_offset = header_bytes + record_count * record_bytes
    table = data[table_offset:]
    bindings: list[ChronoNodeBinding] = []
    for index in range(record_count):
        values = _RECORD.unpack_from(data, header_bytes + index * record_bytes)
        (
            node_index,
            mode_code,
            pixel_code,
            storage_code,
            authority_code,
            novelty_code,
            geometry_code,
            autostart,
            reserved,
            width,
            height,
            fps_min,
            fps_max,
            queue_slots,
            lut_resolution,
            root_seed,
            recipe_seed,
            r0,
            rho_min,
            rho_max,
            core_radius,
            lut_digest,
            asset_bytes,
            asset_digest,
            camera_offset,
            camera_bytes,
            camera_reserved,
            output_offset,
            output_bytes,
            output_reserved,
            asset_offset,
            asset_path_bytes,
            asset_reserved,
            reserved_tail,
        ) = values
        if reserved or reserved_tail:
            raise ChronoBindingPackError("KCCH392 record reserved field is nonzero")
        if pixel_code != _PIXEL_PROFILE_CODE:
            raise ChronoBindingPackError("KCCH392 pixel profile code is unsupported")
        if authority_code != _AUTHORITY_CODE or novelty_code != _NOVELTY_CODE:
            raise ChronoBindingPackError(
                "KCCH392 authority/novelty code is unsupported"
            )
        if geometry_code != _GEOMETRY_CODE:
            raise ChronoBindingPackError("KCCH392 geometry code is unsupported")
        if autostart not in (0, 1):
            raise ChronoBindingPackError("KCCH392 autostart must be boolean 0 or 1")
        if fps_min != fps_max:
            raise ChronoBindingPackError("KCCH392 v1 requires a fixed capture FPS")
        try:
            mode = _MODE_NAMES[mode_code]
            storage = _STORAGE_NAMES[storage_code]
        except KeyError as exc:
            raise ChronoBindingPackError(
                "KCCH392 mode/storage code is unsupported"
            ) from exc
        if node_count is not None and node_index >= node_count:
            raise ChronoBindingPackError("KCCH392 references a missing KC3D node")
        camera_id = _decode_string(
            table, camera_offset, camera_bytes, camera_reserved, "camera_id"
        )
        stream_name = _decode_string(
            table, output_offset, output_bytes, output_reserved, "stream_name"
        )
        packaged_path = _decode_string(
            table, asset_offset, asset_path_bytes, asset_reserved, "source_asset"
        )
        if packaged_path:
            if not packaged_path.startswith("chrono/"):
                raise ChronoBindingPackError(
                    "KCCH392 player asset is outside the chrono asset directory"
                )
            source_path = packaged_path[len("chrono/") :]
        else:
            source_path = ""
        binding = ChronoNodeBinding(
            node_index=node_index,
            mode=mode,
            width=width,
            height=height,
            fps=fps_min,
            queue_slots=queue_slots,
            root_seed_u64=root_seed,
            recipe_seed_u64=recipe_seed,
            uglut2_resolution=lut_resolution,
            uglut2_r0=r0,
            uglut2_rho_min=rho_min,
            uglut2_rho_max=rho_max,
            uglut2_core_radius=core_radius,
            uglut2_sha256=lut_digest.hex(),
            storage_policy=storage,
            camera_id=camera_id,
            output_name=stream_name if mode == MODE_RECORDER else "",
            input_name=(
                stream_name
                if mode == MODE_PLAYER and storage == STORAGE_APP_PRIVATE
                else ""
            ),
            source_asset_path=source_path,
            source_asset_bytes=asset_bytes,
            source_asset_sha256=(
                "" if asset_digest == bytes(32) else asset_digest.hex()
            ),
            autostart=bool(autostart),
        )
        binding.validate()
        bindings.append(binding)
    parsed = tuple(bindings)
    if _encode_bindings(parsed) != data:
        raise ChronoBindingPackError("KCCH392 asset is not in canonical form")
    return {
        "schema": "ugts-kc-native-chrono-binding-inspection-3.9.2",
        "format_version": version,
        "byte_length": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "content_sha256": content_digest.hex(),
        "record_bytes": record_bytes,
        "binding_count": len(parsed),
        "recorder_count": sum(item.mode == MODE_RECORDER for item in parsed),
        "player_count": sum(item.mode == MODE_PLAYER for item in parsed),
        "seed_boundary": (
            "root seed regenerates traversal; arbitrary observed pixels remain "
            "exact novelty evidence"
        ),
        "bindings": [
            {
                "node_index": item.node_index,
                "mode": item.mode,
                "width": item.width,
                "height": item.height,
                "fps": item.fps,
                "queue_slots": item.queue_slots,
                "camera_id": item.camera_id or None,
                "output_name": item.output_name or None,
                "input_name": item.input_name or None,
                "source_asset_path": item.packaged_asset_path or None,
                "source_asset_bytes": (
                    item.source_asset_bytes if item.source_asset_path else None
                ),
                "source_asset_sha256": item.source_asset_sha256 or None,
                "root_seed_u64": item.root_seed_u64,
                "recipe_seed_u64": item.recipe_seed_u64,
                "uglut2_resolution": item.uglut2_resolution,
                "uglut2_sha256": item.uglut2_sha256,
                "pixel_profile": item.pixel_profile,
                "storage_policy": item.storage_policy,
                "authority": item.authority,
                "novelty_policy": item.novelty_policy,
                "autostart": item.autostart,
                "geometry_status": item.geometry_status,
            }
            for item in parsed
        ],
    }


def resolve_chrono_player_assets(
    bindings: tuple[ChronoNodeBinding, ...],
    asset_source_root: str | Path | None,
) -> tuple[ResolvedChronoAsset, ...]:
    """Resolve and hash-check every PLAYER asset before export mutation."""

    players = tuple(
        item
        for item in bindings
        if item.mode == MODE_PLAYER and item.storage_policy == STORAGE_PACKAGED
    )
    if not players:
        return ()
    if asset_source_root is None:
        raise ChronoBindingPackError(
            "PLAYER binding declared but no asset source root was provided"
        )
    root = Path(asset_source_root).resolve()
    if not root.is_dir():
        raise ChronoBindingPackError(
            f"chrono asset source root is not a directory: {root}"
        )
    resolved: list[ResolvedChronoAsset] = []
    for binding in players:
        relative = PurePosixPath(binding.source_asset_path)
        source = root.joinpath(*relative.parts).resolve()
        if not source.is_relative_to(root) or not source.is_file():
            raise ChronoBindingPackError(
                f"PLAYER asset is missing or escapes its root: {relative.as_posix()}"
            )
        byte_count = source.stat().st_size
        if byte_count != binding.source_asset_bytes:
            raise ChronoBindingPackError(
                f"PLAYER asset byte-count mismatch: {relative.as_posix()}"
            )
        digest = hashlib.sha256()
        with source.open("rb") as stream:
            first = stream.read(8)
            digest.update(first)
            for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                digest.update(chunk)
        if first != _GSP4_SEED_MAGIC:
            raise ChronoBindingPackError(
                f"PLAYER asset is not a GSP4 UGYUVS1 seed stream: {relative.as_posix()}"
            )
        if digest.hexdigest() != binding.source_asset_sha256:
            raise ChronoBindingPackError(
                f"PLAYER asset SHA-256 mismatch: {relative.as_posix()}"
            )
        resolved.append(
            ResolvedChronoAsset(
                source=source,
                source_relative_path=relative.as_posix(),
                packaged_path=binding.packaged_asset_path,
                byte_count=byte_count,
                sha256=binding.source_asset_sha256,
            )
        )
    return tuple(resolved)


__all__ = [
    "AUTHORITY",
    "CHRONO_BINDING_HEADER_BYTES",
    "CHRONO_BINDING_METADATA_KEY",
    "CHRONO_BINDING_PACK_ASSET",
    "CHRONO_BINDING_PACK_ENDIAN",
    "CHRONO_BINDING_PACK_MAGIC",
    "CHRONO_BINDING_PACK_VERSION",
    "CHRONO_BINDING_RECORD_BYTES",
    "CHRONO_BINDING_SCHEMA",
    "ChronoBindingPackError",
    "ChronoNodeBinding",
    "GEOMETRY_STATUS",
    "MODE_PLAYER",
    "MODE_RECORDER",
    "NOVELTY_POLICY",
    "PIXEL_PROFILE",
    "ResolvedChronoAsset",
    "STORAGE_APP_PRIVATE",
    "STORAGE_PACKAGED",
    "canonical_uglut2_descriptor",
    "chrono_binding_from_metadata",
    "collect_chrono_bindings",
    "compile_chrono_binding_pack_bytes",
    "inspect_chrono_binding_pack",
    "metadata_with_chrono_binding",
    "resolve_chrono_player_assets",
    "write_chrono_binding_pack",
]
