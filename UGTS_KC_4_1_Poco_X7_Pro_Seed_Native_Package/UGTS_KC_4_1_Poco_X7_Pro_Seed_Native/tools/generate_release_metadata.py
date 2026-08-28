#!/usr/bin/env python3
from __future__ import annotations
import csv, hashlib, json, mimetypes
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
MANIFEST_DIR=ROOT/'manifest'; CHECKSUM_DIR=ROOT/'checksums'

def digest(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):
            h.update(block)
    return h.hexdigest()

def all_files():
    excluded_parts={'.git','.gradle','.cxx','build','__pycache__'}
    for path in sorted(p for p in ROOT.rglob('*') if p.is_file()):
        rel=path.relative_to(ROOT)
        if any(part in excluded_parts for part in rel.parts): continue
        yield rel,path

def main():
    MANIFEST_DIR.mkdir(exist_ok=True);CHECKSUM_DIR.mkdir(exist_ok=True)
    for p in MANIFEST_DIR.glob('*'): p.unlink()
    for p in CHECKSUM_DIR.glob('*'): p.unlink()
    payload=[]
    for rel,path in all_files():
        if rel.parts[0] in {'manifest','checksums'}: continue
        payload.append({
            'path':rel.as_posix(),
            'bytes':path.stat().st_size,
            'sha256':digest(path),
            'media_type':mimetypes.guess_type(path.name)[0] or 'application/octet-stream',
        })
    manifest={
        'schema':'ugts-kc-file-manifest-4.1',
        'version':'4.1.0',
        'payload_file_count':len(payload),
        'payload_bytes':sum(x['bytes'] for x in payload),
        'files':payload,
    }
    (MANIFEST_DIR/'file_manifest_4_1.json').write_text(json.dumps(manifest,indent=2)+'\n')
    with (MANIFEST_DIR/'file_manifest_4_1.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['path','bytes','sha256','media_type']);w.writeheader();w.writerows(payload)
    tree=[]
    for rel,_ in all_files():
        if rel.parts[0] in {'manifest','checksums'}: continue
        tree.append(rel.as_posix())
    (MANIFEST_DIR/'package_tree_4_1.txt').write_text('\n'.join(tree)+'\n')
    # Checksums cover all files after manifests exist, excluding the checksum list itself.
    entries=[]
    for rel,path in all_files():
        if rel.as_posix()=='checksums/SHA256SUMS_4_1.txt': continue
        entries.append(f'{digest(path)}  {rel.as_posix()}')
    (CHECKSUM_DIR/'SHA256SUMS_4_1.txt').write_text('\n'.join(entries)+'\n')
    print(json.dumps({'payload_files':len(payload),'payload_bytes':manifest['payload_bytes'],'checksum_entries':len(entries)}))

if __name__=='__main__': main()
