#!/usr/bin/env python3
from pathlib import Path
import struct,sys

manifest=Path(sys.argv[1])
data=bytearray(manifest.read_bytes())

def replace_utf16(old,new):
    assert len(old)==len(new), (old,new)
    ob=old.encode('utf-16le'); nb=new.encode('utf-16le')
    count=data.count(ob)
    if count != 1:
        raise SystemExit(f'expected exactly one UTF-16 occurrence of {old!r}, got {count}')
    pos=data.index(ob); data[pos:pos+len(ob)]=nb

def put_u32(offset,value): struct.pack_into('<I',data,offset,value)

replace_utf16('3.9.2-poco-x7-pro-grove','3.9.4-bayer-direct-v001')
replace_utf16('nl.tomklootwijk.ugtskc.grove.poco','nl.tomklootwijk.ugtskc.bayer.poco')
replace_utf16('ugts_kc_grove','ugts_kc_bayer')

# Typed attribute data offsets from the supplied 3.9.2 binary manifest.
put_u32(2028,394)       # versionCode
put_u32(2864,0)         # allowBackup=false
put_u32(2884,0xffffffff)# extractNativeLibs=true

# Remove all five inherited uses-feature elements (5 x [76-byte start + 24-byte end]).
start=2252; end=2752
if len(data) != 3480 or data[start:start+2] != b'\x02\x01':
    raise SystemExit('unexpected base AndroidManifest.xml layout')
del data[start:end]
struct.pack_into('<I',data,4,len(data))
manifest.write_bytes(data)
print(f'patched {manifest}: {len(data)} bytes')
