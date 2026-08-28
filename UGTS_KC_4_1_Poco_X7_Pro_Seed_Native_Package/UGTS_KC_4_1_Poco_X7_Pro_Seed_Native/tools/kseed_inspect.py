#!/usr/bin/env python3
"""Independent KSEED 4.1 structural, CRC and SHA-chain inspector."""
from __future__ import annotations
import argparse, hashlib, json, pathlib, struct, zlib
HEADER=128; CHUNK=64

def u16(b,o): return struct.unpack_from('<H',b,o)[0]
def u32(b,o): return struct.unpack_from('<I',b,o)[0]
def u64(b,o): return struct.unpack_from('<Q',b,o)[0]
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('path',type=pathlib.Path); ap.add_argument('--json',action='store_true',help='emit JSON (default)'); args=ap.parse_args()
    data=args.path.read_bytes()
    if len(data)<HEADER or data[:7]!=b'KSEED41': raise SystemExit('not KSEED 4.1')
    header_crc=zlib.crc32(data[:124])&0xffffffff
    out={'path':str(args.path),'file_bytes':len(data),'header':{'version':[u16(data,8),u16(data,10)],'session_seed':f'0x{u64(data,16):016x}','start_time_ns':u64(data,24),'analysis':[u16(data,32),u16(data,34)],'fps_x100':u16(data,36),'feature_budget':u16(data,38),'header_crc_ok':header_crc==u32(data,124)},'chunks':[]}
    chain=hashlib.sha256(b'KSEED41-CHAIN').digest(); off=HEADER; complete=False; all_crc=True; all_chain=True
    while off<len(data):
        if off+CHUNK>len(data): raise SystemExit('truncated chunk header')
        h=data[off:off+CHUNK]; off+=CHUNK
        if h[:4]!=b'KCH1': raise SystemExit('bad chunk magic')
        typ,flags,seq,count,raw_n,stored_n,raw_crc,stored_crc=struct.unpack_from('<HHIIIIII',h,4)
        stored=data[off:off+stored_n]; off+=stored_n
        if len(stored)!=stored_n: raise SystemExit('truncated chunk')
        stored_ok=(zlib.crc32(stored)&0xffffffff)==stored_crc
        expected=hashlib.sha256(chain+h[:32]+stored).digest(); chain_ok=expected==h[32:64]; chain=expected
        raw=zlib.decompress(stored) if flags&1 else stored
        raw_ok=len(raw)==raw_n and (zlib.crc32(raw)&0xffffffff)==raw_crc
        all_crc &= stored_ok and raw_ok; all_chain &= chain_ok
        item={'sequence':seq,'type':typ,'records':count,'compressed':bool(flags&1),'raw_bytes':raw_n,'stored_bytes':stored_n,'stored_crc_ok':stored_ok,'raw_crc_ok':raw_ok,'chain_ok':chain_ok}
        if typ==4 and len(raw)>=60:
            vals=struct.unpack_from('<QQQIIIIIQQ',raw,0)
            item['summary']={'session_seed':f'0x{vals[0]:016x}','start_time_ns':vals[1],'end_time_ns':vals[2],'frames_seen':vals[3],'keyframes_stored':vals[4],'proposals_seen':vals[5],'events_committed':vals[6],'rejected_proposals':vals[7],'raw_input_bytes':vals[8],'stored_bytes':vals[9]}
            complete=True
        out['chunks'].append(item)
    out['integrity']={'header_crc_ok':out['header']['header_crc_ok'],'chunk_crc_ok':all_crc,'chain_ok':all_chain,'complete':complete,'sha256':hashlib.sha256(data).hexdigest()}
    print(json.dumps(out,indent=2))
    if not all(out['integrity'][k] for k in ('header_crc_ok','chunk_crc_ok','chain_ok','complete')): raise SystemExit(2)
if __name__=='__main__': main()
