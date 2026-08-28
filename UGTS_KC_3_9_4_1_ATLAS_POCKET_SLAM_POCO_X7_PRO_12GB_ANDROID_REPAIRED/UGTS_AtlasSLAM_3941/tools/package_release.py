#!/usr/bin/env python3
from __future__ import annotations

import argparse
import stat
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOT_NAME = "UGTS_AtlasSLAM_3941"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        args.output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, allowZip64=True
    ) as archive:
        archive.comment = b"UGTS-KC 3.9.4.1 repaired Android source release"
        for path in sorted(ROOT.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(ROOT).as_posix()
            name = f"{ROOT_NAME}/{relative}"
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            executable = path.name == "gradlew" or path.suffix == ".sh" or (
                path.suffix == ".py" and path.read_bytes().startswith(b"#!")
            )
            mode = 0o100755 if executable else 0o100644
            info.external_attr = mode << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(
                info,
                path.read_bytes(),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
