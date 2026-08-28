#!/usr/bin/env python3
"""Verify packaged UGTS-KC 4.1 files against SHA256SUMS and manifest."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]

def digest(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):
            h.update(block)
    return h.hexdigest()

def main()->int:
    sums=ROOT/'checksums/SHA256SUMS_4_1.txt'
    if not sums.is_file():
        print(f'Missing {sums}',file=sys.stderr);return 2
    checked=0; failures=[]
    for line in sums.read_text().splitlines():
        if not line.strip(): continue
        expected,rel=line.split('  ',1)
        path=ROOT/rel
        if not path.is_file(): failures.append(f'missing: {rel}');continue
        actual=digest(path)
        if actual!=expected: failures.append(f'hash mismatch: {rel}')
        checked+=1
    manifest_path=ROOT/'manifest/file_manifest_4_1.json'
    try:
        manifest=json.loads(manifest_path.read_text())
    except Exception as exc:
        failures.append(f'manifest parse: {exc}');manifest={}
    payload=manifest.get('files',[])
    for item in payload:
        path=ROOT/item['path']
        if not path.is_file(): failures.append(f'manifest missing: {item["path"]}');continue
        if path.stat().st_size!=item['bytes']: failures.append(f'manifest size: {item["path"]}')
        if digest(path)!=item['sha256']: failures.append(f'manifest hash: {item["path"]}')
    if (ROOT/'VERSION').read_text().strip()!='4.1.0': failures.append('version is not 4.1.0')
    if failures:
        print(f'FAIL: {len(failures)} issue(s) after {checked} checksum entries')
        for item in failures: print(item,file=sys.stderr)
        return 1
    print(f'PASS: {checked} checksum entries and {len(payload)} manifest payload files')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
