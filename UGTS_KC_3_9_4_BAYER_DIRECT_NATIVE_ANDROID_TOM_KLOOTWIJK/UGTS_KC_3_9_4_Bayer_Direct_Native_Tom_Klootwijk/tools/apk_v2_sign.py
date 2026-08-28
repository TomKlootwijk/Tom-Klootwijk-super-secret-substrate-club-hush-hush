#!/usr/bin/env python3
"""Minimal APK Signature Scheme v2 signer for a small non-ZIP64 APK.
Adds a single RSA PKCS#1 v1.5 SHA-256 signer. The input may already carry v1 JAR signatures.
"""
from pathlib import Path
import hashlib, struct, sys
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import pkcs12

EOCD_SIG=b'PK\x05\x06'
APK_SIG_MAGIC=b'APK Sig Block 42'
V2_ID=0x7109871a
ALG_RSA_PKCS1_SHA256=0x0103
CHUNK=1024*1024

def u32(v): return struct.pack('<I',v)
def u64(v): return struct.pack('<Q',v)
def lp(data): return u32(len(data))+data

def find_eocd(apk: bytes):
    start=max(0,len(apk)-22-65535)
    off=apk.rfind(EOCD_SIG,start)
    if off<0 or off+22>len(apk): raise ValueError('EOCD not found')
    comment_len=struct.unpack_from('<H',apk,off+20)[0]
    if off+22+comment_len!=len(apk): raise ValueError('unsupported trailing data or malformed EOCD')
    cd_size=struct.unpack_from('<I',apk,off+12)[0]
    cd_offset=struct.unpack_from('<I',apk,off+16)[0]
    if cd_offset+cd_size!=off: raise ValueError('ZIP64 or noncanonical central directory unsupported')
    return off,cd_offset,cd_size

def chunked_digest(sections):
    chunk_digests=[]
    for section in sections:
        for pos in range(0,len(section),CHUNK):
            chunk=section[pos:pos+CHUNK]
            chunk_digests.append(hashlib.sha256(b'\xa5'+u32(len(chunk))+chunk).digest())
    return hashlib.sha256(b'\x5a'+u32(len(chunk_digests))+b''.join(chunk_digests)).digest()

def sign(in_path: Path,out_path: Path,key_path: Path,password: bytes):
    apk=in_path.read_bytes()
    eocd_off,cd_off,cd_size=find_eocd(apk)
    pre=apk[:cd_off]
    cd=apk[cd_off:eocd_off]
    eocd=bytearray(apk[eocd_off:])
    struct.pack_into('<I',eocd,16,cd_off)
    digest=chunked_digest([pre,cd,bytes(eocd)])

    key,cert,extras=pkcs12.load_key_and_certificates(key_path.read_bytes(),password)
    if key is None or cert is None: raise ValueError('PKCS12 lacks key/certificate')
    cert_der=cert.public_bytes(serialization.Encoding.DER)
    pub_der=key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)

    digest_record=u32(ALG_RSA_PKCS1_SHA256)+lp(digest)
    digests=lp(digest_record)
    certificates=lp(cert_der)
    attributes=b''
    signed_data=lp(digests)+lp(certificates)+lp(attributes)
    signature=key.sign(signed_data,padding.PKCS1v15(),hashes.SHA256())
    signature_record=u32(ALG_RSA_PKCS1_SHA256)+lp(signature)
    signatures=lp(signature_record)
    signer=lp(signed_data)+lp(signatures)+lp(pub_der)
    v2_value=lp(signer)
    pair=u64(4+len(v2_value))+u32(V2_ID)+v2_value
    block_size=len(pair)+8+16
    block=u64(block_size)+pair+u64(block_size)+APK_SIG_MAGIC

    final_eocd=bytearray(apk[eocd_off:])
    struct.pack_into('<I',final_eocd,16,cd_off+len(block))
    final=pre+block+cd+bytes(final_eocd)
    out_path.write_bytes(final)
    return {'digest':digest.hex(),'block_bytes':len(block),'apk_bytes':len(final),'cert_sha256':cert.fingerprint(hashes.SHA256()).hex()}

if __name__=='__main__':
    if len(sys.argv)!=5:
        raise SystemExit('usage: apk_v2_sign.py INPUT.apk OUTPUT.apk KEY.p12 PASSWORD')
    result=sign(Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3]),sys.argv[4].encode())
    for k,v in result.items(): print(f'{k}={v}')
