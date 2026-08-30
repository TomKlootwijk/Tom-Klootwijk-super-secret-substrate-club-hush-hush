from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import tempfile

import pytest

from ugts_kc3.androidexport import build_android_project
from ugts_kc3.chrono_binding_pack import (
    AUTHORITY,
    CHRONO_BINDING_HEADER_BYTES,
    CHRONO_BINDING_METADATA_KEY,
    CHRONO_BINDING_PACK_ASSET,
    CHRONO_BINDING_RECORD_BYTES,
    CHRONO_BINDING_SCHEMA,
    CHRONO_UGLUT2_ASSET_DIRECTORY,
    GEOMETRY_STATUS,
    MODE_PLAYER,
    MODE_RECORDER,
    NOVELTY_POLICY,
    PIXEL_PROFILE,
    STORAGE_APP_PRIVATE,
    STORAGE_PACKAGED,
    ChronoBindingPackError,
    canonical_uglut2_descriptor,
    compile_chrono_binding_pack_bytes,
    inspect_chrono_binding_pack,
)
from ugts_kc3.mobile3d import Mobile3DProject
from ugts_kc3.packed_kinematics import LogPolarProfile
from ugts_kc3.templates3d import blank_mobile3d_project


def _uglut2() -> dict[str, object]:
    return canonical_uglut2_descriptor(
        LogPolarProfile(
            r0=1.0,
            rho_min=math.log(0.5),
            rho_max=math.log(16_000.0),
            core_radius=0.5,
        ),
        16,
    )


def _common(mode: str, storage: str) -> dict[str, object]:
    return {
        "schema": CHRONO_BINDING_SCHEMA,
        "mode": mode,
        "width": 1280,
        "height": 720,
        "fps": 30,
        "queue_slots": 6,
        "pixel_profile": PIXEL_PROFILE,
        "root_seed_u64": 0x1FC3807CFABA6718,
        "recipe_seed_u64": 1,
        "uglut2": _uglut2(),
        "storage_policy": storage,
        "novelty_policy": NOVELTY_POLICY,
        "authority": AUTHORITY,
        "autostart": False,
        "geometry_status": GEOMETRY_STATUS,
    }


def _recorder() -> dict[str, object]:
    return {
        **_common(MODE_RECORDER, STORAGE_APP_PRIVATE),
        "camera_id": "0",
        "output_name": "camera_capture.ugsp4c",
    }


def _player(path: Path) -> dict[str, object]:
    return {
        **_common(MODE_PLAYER, STORAGE_PACKAGED),
        "source_asset": {
            "path": path.name,
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        },
    }


def _app_private_player() -> dict[str, object]:
    return {
        **_common(MODE_PLAYER, STORAGE_APP_PRIVATE),
        "input_name": "camera_capture.ugsp4c",
    }


def _bound_project(binding: dict[str, object]):
    project = blank_mobile3d_project("KCCH392 test")
    first = project.nodes[0]
    metadata = dict(first.metadata)
    metadata[CHRONO_BINDING_METADATA_KEY] = binding
    return replace(
        project,
        nodes=(replace(first, metadata=metadata), *project.nodes[1:]),
    )


def _recorder_player_project(*, autostart: bool = False):
    project = _bound_project({**_recorder(), "autostart": autostart})
    first = project.nodes[0]
    playback = replace(
        first,
        id="chrono_seed_player",
        metadata={CHRONO_BINDING_METADATA_KEY: _app_private_player()},
    )
    return replace(project, nodes=(*project.nodes, playback))


def test_recorder_pack_is_sparse_canonical_and_json_round_trips() -> None:
    project = _bound_project(_recorder())
    project.validate()
    packed = compile_chrono_binding_pack_bytes(project)
    assert len(packed) >= CHRONO_BINDING_HEADER_BYTES + CHRONO_BINDING_RECORD_BYTES

    report = inspect_chrono_binding_pack(packed, node_count=len(project.nodes))
    assert report["binding_count"] == 1
    assert report["recorder_count"] == 1
    assert report["player_count"] == 0
    assert report["bindings"][0]["node_index"] == 0
    assert report["bindings"][0]["camera_id"] == "0"
    assert report["bindings"][0]["pixel_profile"] == "UGCODE24_420_CAMERA_EXACT"
    assert report["bindings"][0]["autostart"] is False
    assert "arbitrary observed pixels" in report["seed_boundary"]

    clone = Mobile3DProject.from_dict(project.to_dict())
    assert compile_chrono_binding_pack_bytes(clone) == packed


def test_player_asset_is_hash_checked_copied_and_receipted() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        stream = root / "literal_camera.ugsp4c"
        stream.write_bytes(b"UGYUVS1\0" + bytes(248))
        project = _bound_project(_player(stream))
        output = root / "android"

        built = build_android_project(project, output, asset_source_root=root)
        expected_pack = output / "app/src/main/assets" / CHRONO_BINDING_PACK_ASSET
        copied = output / "app/src/main/assets/chrono" / stream.name
        assert built.chrono_binding_pack == expected_pack
        assert copied.read_bytes() == stream.read_bytes()
        inspect_chrono_binding_pack(expected_pack, node_count=len(project.nodes))

        report = json.loads(built.build_report.read_text(encoding="utf-8"))
        runtime = report["chrono_substrate_runtime"]
        assert runtime["present"] is True
        assert runtime["pack"]["player_count"] == 1
        assert runtime["source_assets"] == [
            {
                "path": f"chrono/{stream.name}",
                "bytes": stream.stat().st_size,
                "sha256": hashlib.sha256(stream.read_bytes()).hexdigest(),
            }
        ]
        assert "arbitrary observed pixels" in runtime["seed_boundary"]


def test_recorder_export_packages_binding_but_no_legacy_media() -> None:
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "android"
        built = build_android_project(_bound_project(_recorder()), output)

        assert built.chrono_binding_pack is not None
        assert built.chrono_binding_pack.name == CHRONO_BINDING_PACK_ASSET
        report = json.loads(built.build_report.read_text(encoding="utf-8"))
        runtime = report["chrono_substrate_runtime"]
        assert runtime["pack"]["recorder_count"] == 1
        assert runtime["source_assets"] == []
        assert runtime["source_asset_bytes"] == 0
        dependencies = runtime["uglut2_dependencies"]
        assert len(dependencies) == 1
        assert runtime["uglut2_dependency_bytes"] == 144
        dependency = dependencies[0]
        assert dependency["bytes"] == 144
        assert dependency["path"] == (
            f"{CHRONO_UGLUT2_ASSET_DIRECTORY}/{_uglut2()['sha256']}.uglut2"
        )
        literal = output / "app/src/main/assets" / dependency["path"]
        assert literal.read_bytes().startswith(b"UGLUT2")
        assert hashlib.sha256(literal.read_bytes()).hexdigest() == dependency["sha256"]
        native = runtime["portable_native_sources"]
        assert native["present"] is True
        assert native["source_authority"] == "repository native/ugtc4d"
        assert [Path(receipt["path"]).name for receipt in native["files"]] == [
            "ugtc4d_decoder.hpp",
            "ugtc4d_decoder.cpp",
            "seeded_uglut2_traversal.hpp",
            "seeded_uglut2_traversal.cpp",
            "full_substrate_camera.hpp",
            "full_substrate_camera.cpp",
            "yuv_seed_capture.hpp",
            "yuv_seed_capture.cpp",
        ]
        for receipt in native["files"]:
            copied = output / receipt["path"]
            assert copied.stat().st_size == receipt["bytes"]
            assert hashlib.sha256(copied.read_bytes()).hexdigest() == receipt["sha256"]
        assert not tuple(output.rglob("*.mp4"))
        assert not tuple(output.rglob("*.ugtc4d"))


def test_app_private_player_consumes_the_recorder_stream_without_packaged_input() -> (
    None
):
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "android"
        project = _recorder_player_project(autostart=True)
        built = build_android_project(project, output)
        inspection = inspect_chrono_binding_pack(
            built.chrono_binding_pack, node_count=len(project.nodes)
        )

        assert inspection["recorder_count"] == 1
        assert inspection["player_count"] == 1
        recorder, player = inspection["bindings"]
        assert recorder["output_name"] == "camera_capture.ugsp4c"
        assert recorder["autostart"] is True
        assert player["input_name"] == recorder["output_name"]
        assert player["source_asset_path"] is None

        report = json.loads(built.build_report.read_text(encoding="utf-8"))
        runtime = report["chrono_substrate_runtime"]
        assert runtime["source_assets"] == []
        assert runtime["pack"]["binding_count"] == 2
        assert len(runtime["uglut2_dependencies"]) == 1


def test_app_private_player_must_bind_the_unique_recorder_output() -> None:
    project = _recorder_player_project()
    playback = project.nodes[-1]
    metadata = dict(playback.metadata)
    binding = dict(metadata[CHRONO_BINDING_METADATA_KEY])
    binding["input_name"] = "different.ugsp4c"
    metadata[CHRONO_BINDING_METADATA_KEY] = binding
    project = replace(
        project,
        nodes=(*project.nodes[:-1], replace(playback, metadata=metadata)),
    )
    with pytest.raises(ChronoBindingPackError, match="must match the RECORDER"):
        compile_chrono_binding_pack_bytes(project)


def test_app_private_player_profile_must_equal_the_recorder() -> None:
    project = _recorder_player_project()
    playback = project.nodes[-1]
    metadata = dict(playback.metadata)
    binding = dict(metadata[CHRONO_BINDING_METADATA_KEY])
    binding["root_seed_u64"] = int(binding["root_seed_u64"]) + 1
    metadata[CHRONO_BINDING_METADATA_KEY] = binding
    project = replace(
        project,
        nodes=(*project.nodes[:-1], replace(playback, metadata=metadata)),
    )
    with pytest.raises(ChronoBindingPackError, match="profile disagrees"):
        compile_chrono_binding_pack_bytes(project)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("autostart", 1, "autostart must be an editable boolean"),
        ("recipe_seed_u64", 2, "fixes recipe_seed_u64"),
        ("novelty_policy", "DROP_RESIDUALS", "novelty_policy"),
        ("geometry_status", "METRIC", "geometry_status"),
    ],
)
def test_invalid_authority_fields_fail_project_validation(
    field: str, value: object, message: str
) -> None:
    binding = _recorder()
    binding[field] = value
    report = _bound_project(binding).validate(raise_on_error=False)
    matching = [
        issue for issue in report.issues if issue.code == "chrono_binding.invalid"
    ]
    assert len(matching) == 1
    assert message in matching[0].message


def test_uglut2_preimage_and_passive_node_are_enforced() -> None:
    binding = _recorder()
    uglut = dict(binding["uglut2"])
    uglut["sha256"] = "0" * 64
    binding["uglut2"] = uglut
    with pytest.raises(ChronoBindingPackError, match="canonical profile preimage"):
        compile_chrono_binding_pack_bytes(_bound_project(binding))

    project = _bound_project(_recorder())
    first = replace(project.nodes[0], dynamic=True)
    with pytest.raises(ChronoBindingPackError, match="dynamic physics writer"):
        compile_chrono_binding_pack_bytes(
            replace(project, nodes=(first, *project.nodes[1:]))
        )


def test_inspector_rejects_digest_failure_trailing_bytes_and_bad_node_index() -> None:
    project = _bound_project(_recorder())
    packed = compile_chrono_binding_pack_bytes(project)
    corrupt = bytearray(packed)
    corrupt[-1] ^= 1
    with pytest.raises(ChronoBindingPackError, match="content SHA-256"):
        inspect_chrono_binding_pack(corrupt)
    with pytest.raises(ChronoBindingPackError, match="byte length"):
        inspect_chrono_binding_pack(packed + b"x")
    with pytest.raises(ChronoBindingPackError, match="missing KC3D node"):
        inspect_chrono_binding_pack(packed, node_count=0)


def test_unbound_project_has_no_optional_sidecar() -> None:
    project = blank_mobile3d_project("No chrono")
    assert compile_chrono_binding_pack_bytes(project) == b""
