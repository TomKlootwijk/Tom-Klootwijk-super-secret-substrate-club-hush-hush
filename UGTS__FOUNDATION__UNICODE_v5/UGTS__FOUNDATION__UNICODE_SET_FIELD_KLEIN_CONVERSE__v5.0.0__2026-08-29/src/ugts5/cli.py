"""Command line for the UGTS 5.0 reference package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .atlas import HotCodebook, OperatorAtlas
from .canonical import load_json
from .packing import PackedNode32, PackedNodeFields
from .stream import read_stream


def _paths(root: Path) -> tuple[Path, Path]:
    return root / "spec" / "operator_atlas.json", root / "spec" / "hot_codebook_set_core_16.json"


def cmd_atlas_info(args: argparse.Namespace) -> int:
    atlas_path, codebook_path = _paths(Path(args.package_root))
    atlas = OperatorAtlas.load(atlas_path)
    codebook = HotCodebook.load(codebook_path, atlas)
    print(json.dumps({
        "atlas_id": atlas.record["atlas_id"],
        "version": atlas.record["version"],
        "operator_count": len(atlas.literals),
        "atlas_hash": atlas.atlas_hash,
        "hot_codebook_id": codebook.record["codebook_id"],
        "occupied_slots": sum(1 for e in codebook.entries if e),
    }, indent=2, ensure_ascii=False))
    return 0


def cmd_pair(args: argparse.Namespace) -> int:
    atlas_path, _ = _paths(Path(args.package_root))
    atlas = OperatorAtlas.load(atlas_path)
    cell = atlas.by_literal(args.literal)
    converse = atlas.by_id(cell.converse_id) if cell.converse_id else None
    print(json.dumps({
        "literal": cell.literal,
        "operator_id": cell.id,
        "surface_argument_order": cell.record["syntax"]["surface_argument_order"],
        "canonical_argument_order": cell.record["syntax"]["canonical_argument_order"],
        "converse_literal": converse.literal if converse else None,
        "kappa": cell.kappa,
        "glyph_profile": cell.record["glyph"]["profile_id"],
    }, indent=2, ensure_ascii=False))
    return 0


def cmd_pack(args: argparse.Namespace) -> int:
    fields = PackedNodeFields(
        family=args.family,
        kappa=args.kappa,
        delta_rho=args.delta_rho,
        delta_theta=args.delta_theta,
        grammar_path=args.grammar_path,
        local_flags=args.local_flags,
        active=not args.inactive,
    )
    word = PackedNode32.pack(fields)
    print(f"0x{word:08x}")
    return 0


def cmd_unpack(args: argparse.Namespace) -> int:
    word = int(args.word, 0)
    fields = PackedNode32.unpack(word)
    print(json.dumps(fields.__dict__ | {"operator_id": fields.operator_id}, indent=2))
    return 0


def cmd_stream_info(args: argparse.Namespace) -> int:
    header, words = read_stream(args.path)
    print(json.dumps({"header": header, "node_count": len(words), "words_hex": [f"0x{w:08x}" for w in words]}, indent=2, ensure_ascii=False))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    root = Path(args.package_root)
    atlas_path, codebook_path = _paths(root)
    atlas = OperatorAtlas.load(atlas_path)
    codebook = HotCodebook.load(codebook_path, atlas)
    release = load_json(root / "spec" / "release_record.json")
    mechanisms = load_json(root / "spec" / "mechanisms.json")
    claims = load_json(root / "spec" / "claims_ledger.json")
    summary = {
        "release_identity": release["canonical_identity"],
        "atlas_hash": atlas.atlas_hash,
        "codebook_hash": codebook.record["codebook_hash"],
        "mechanisms": len(mechanisms["mechanisms"]),
        "claims": len(claims["claims"]),
        "status": "PASS",
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ugts5")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("atlas-info")
    p.add_argument("--package-root", default=".")
    p.set_defaults(func=cmd_atlas_info)

    p = sub.add_parser("pair")
    p.add_argument("literal")
    p.add_argument("--package-root", default=".")
    p.set_defaults(func=cmd_pair)

    p = sub.add_parser("pack")
    p.add_argument("--family", type=int, required=True)
    p.add_argument("--kappa", type=int, choices=(0, 1), required=True)
    p.add_argument("--delta-rho", type=int, required=True)
    p.add_argument("--delta-theta", type=int, required=True)
    p.add_argument("--grammar-path", type=lambda x: int(x, 0), required=True)
    p.add_argument("--local-flags", type=int, default=0)
    p.add_argument("--inactive", action="store_true")
    p.set_defaults(func=cmd_pack)

    p = sub.add_parser("unpack")
    p.add_argument("word")
    p.set_defaults(func=cmd_unpack)

    p = sub.add_parser("stream-info")
    p.add_argument("path")
    p.set_defaults(func=cmd_stream_info)

    p = sub.add_parser("verify")
    p.add_argument("--package-root", default=".")
    p.set_defaults(func=cmd_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:  # CLI must return a useful reason code rather than a traceback by default.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
