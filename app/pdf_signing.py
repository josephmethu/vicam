"""Certificate signing of final server-generated PDF bytes. No keys are bundled."""
import io
from datetime import datetime,timezone,timedelta
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa,ec
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import signers
from pyhanko.sign.fields import MDPPerm,SigSeedSubFilter


def load_signer(settings):
    if settings.pdf_signing_mode=='disabled':raise ValueError('PDF signing is not configured')
    if not settings.pdf_signing_pfx or not settings.pdf_signing_password:raise ValueError('A certificate file and its password are required')
    key,cert,chain=pkcs12.load_key_and_certificates(Path(settings.pdf_signing_pfx).read_bytes(),settings.pdf_signing_password.encode())
    if not key or not cert:raise ValueError('The certificate file must contain a private key and certificate')
    if key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)!=cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo):raise ValueError('The signing key does not match the certificate')
    current=datetime.now(timezone.utc)
    if not cert.not_valid_before_utc<=current<cert.not_valid_after_utc:raise ValueError('The signing certificate is not currently valid')
    if isinstance(key,rsa.RSAPrivateKey):
        if key.key_size<2048:raise ValueError('RSA signing requires at least 2048 bits')
    elif isinstance(key,ec.EllipticCurvePrivateKey):
        if key.key_size<256:raise ValueError('EC signing requires at least 256 bits')
    else:raise ValueError('Use an RSA or elliptic curve signing certificate')
    try:
        usage=cert.extensions.get_extension_for_class(x509.KeyUsage).value
        if not (usage.digital_signature and usage.content_commitment):raise ValueError('Certificate must permit digital signature and content commitment')
    except x509.ExtensionNotFound:
        raise ValueError('Certificate key usage is missing')
    if settings.production and cert.issuer==cert.subject:raise ValueError('Self-signed test certificates are not allowed in production')
    signer=signers.SimpleSigner.load_pkcs12(str(settings.pdf_signing_pfx),passphrase=settings.pdf_signing_password.encode())
    if signer is None:raise ValueError('Could not load the signing certificate')
    return signer,cert.fingerprint(hashes.SHA256()).hex()


def sign_pdf(pdf,settings):
    signer,fingerprint=load_signer(settings)
    output=io.BytesIO()
    metadata=signers.PdfSignatureMetadata(field_name='VICAMCertification',md_algorithm='sha256',certify=True,
        docmdp_permissions=MDPPerm.NO_CHANGES,subfilter=SigSeedSubFilter.PADES,
        reason='VICAM issued quotation/invoice: no changes permitted')
    signers.PdfSigner(metadata,signer=signer).sign_pdf(IncrementalPdfFileWriter(io.BytesIO(pdf)),output=output)
    return output.getvalue(),fingerprint


def create_test_certificate(path,password):
    """Explicit local test command only. This identity is not externally trusted."""
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'VICAM LOCAL TEST - NOT TRUSTED')])
    current=datetime.now(timezone.utc)
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(current-timedelta(minutes=1)).not_valid_after(current+timedelta(days=90))
        .add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True,content_commitment=True,key_encipherment=False,data_encipherment=False,key_agreement=False,key_cert_sign=False,crl_sign=False,encipher_only=None,decipher_only=None),critical=True)
        .sign(key,hashes.SHA256()))
    data=pkcs12.serialize_key_and_certificates(b'VICAM local test',key,cert,None,serialization.BestAvailableEncryption(password.encode()))
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    import os
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'wb') as file:file.write(data)
    return cert
