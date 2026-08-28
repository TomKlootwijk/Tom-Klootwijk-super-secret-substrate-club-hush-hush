#!/usr/bin/env python3
from pathlib import Path
import hashlib,struct,sys
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import padding

MAGIC=b'APK Sig Block 42'; V2_ID=0x7109871a; ALG=0x0103; CHUNK=1024*1024
u32=lambda b,o:struct.unpack_from('<I',b,o)[0]
u64=lambda b,o:struct.unpack_from('<Q',b,o)[0]
def p32(v):return struct.pack('<I',v)
def lp_read(b,o):
 n=u32(b,o); o+=4
 if o+n>len(b):raise ValueError('length overflow')
 return b[o:o+n],o+n
def find_eocd(apk):
 off=apk.rfind(b'PK\x05\x06',max(0,len(apk)-65557))
 if off<0:raise ValueError('EOCD missing')
 return off,u32(apk,off+16),u32(apk,off+12)
def digest(sections):
 ds=[]
 for sec in sections:
  for pos in range(0,len(sec),CHUNK):
   c=sec[pos:pos+CHUNK]; ds.append(hashlib.sha256(b'\xa5'+p32(len(c))+c).digest())
 return hashlib.sha256(b'\x5a'+p32(len(ds))+b''.join(ds)).digest()
def verify(path):
 apk=Path(path).read_bytes(); eo,cd,cds=find_eocd(apk)
 if apk[cd-16:cd]!=MAGIC:raise ValueError('signing magic missing')
 sz=u64(apk,cd-24); start=cd-(sz+8)
 if start<0 or u64(apk,start)!=sz:raise ValueError('size mismatch')
 pairs=apk[start+8:cd-24]; po=0; v2=None
 while po<len(pairs):
  n=u64(pairs,po);po+=8; pid=u32(pairs,po); value=pairs[po+4:po+n];po+=n
  if pid==V2_ID:v2=value
 if v2 is None:raise ValueError('v2 pair missing')
 signer,so=lp_read(v2,0)
 if so!=len(v2):raise ValueError('multiple signers unsupported')
 signed_data,o=lp_read(signer,0); sigs,o=lp_read(signer,o); pub,o=lp_read(signer,o)
 if o!=len(signer):raise ValueError('signer trailing data')
 # Parse digest
 digests,do=lp_read(signed_data,0); certs,do=lp_read(signed_data,do); attrs,do=lp_read(signed_data,do)
 rec,ro=lp_read(digests,0); alg=u32(rec,0); expected,_=lp_read(rec,4)
 cert_der,co=lp_read(certs,0); cert=x509.load_der_x509_certificate(cert_der)
 sigrec,sro=lp_read(sigs,0); salg=u32(sigrec,0); signature,_=lp_read(sigrec,4)
 if alg!=ALG or salg!=ALG:raise ValueError('unexpected algorithm')
 if pub!=cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo):raise ValueError('public key mismatch')
 cert.public_key().verify(signature,signed_data,padding.PKCS1v15(),hashes.SHA256())
 eocd=bytearray(apk[eo:]); struct.pack_into('<I',eocd,16,start)
 actual=digest([apk[:start],apk[cd:eo],bytes(eocd)])
 if actual!=expected:raise ValueError(f'content digest mismatch {actual.hex()} != {expected.hex()}')
 return {'apk_bytes':len(apk),'signing_block_offset':start,'signing_block_bytes':cd-start,'content_digest':actual.hex(),'cert_sha256':cert.fingerprint(hashes.SHA256()).hex(),'subject':cert.subject.rfc4514_string()}
if __name__=='__main__':
 r=verify(sys.argv[1])
 for k,v in r.items():print(f'{k}={v}')
