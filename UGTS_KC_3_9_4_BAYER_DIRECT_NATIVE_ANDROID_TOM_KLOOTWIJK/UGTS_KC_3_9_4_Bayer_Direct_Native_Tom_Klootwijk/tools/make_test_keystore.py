#!/usr/bin/env python3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
import sys
out=Path(sys.argv[1]); password=sys.argv[2].encode()
key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
name=x509.Name([
    x509.NameAttribute(NameOID.COMMON_NAME,'UGTS-KC 3.9.4 Bayer Direct Test Build'),
    x509.NameAttribute(NameOID.ORGANIZATION_NAME,'Tom Klootwijk Signature Edition'),
    x509.NameAttribute(NameOID.COUNTRY_NAME,'NL'),
])
now=datetime.now(timezone.utc)
cert=(x509.CertificateBuilder()
      .subject_name(name).issuer_name(name).public_key(key.public_key())
      .serial_number(x509.random_serial_number())
      .not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=3650))
      .add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True)
      .sign(key,hashes.SHA256()))
p12=pkcs12.serialize_key_and_certificates(b'ugtskc394',key,cert,None,serialization.BestAvailableEncryption(password))
out.write_bytes(p12)
(out.with_suffix('.key.pem')).write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
(out.with_suffix('.cert.pem')).write_bytes(cert.public_bytes(serialization.Encoding.PEM))
print(cert.fingerprint(hashes.SHA256()).hex())
