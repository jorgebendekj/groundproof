"""Field-capture signing, verification and per-plot hash chain.

MVP signs a C2PA-style manifest with Ed25519 (dev key generated on first use). When `c2pa-python`
and a certificate are configured (C2PA_CERT_PATH / C2PA_KEY_PATH), `embed_c2pa` produces a real
C2PA manifest embedded in the JPEG; see docs/HANDOVER.md.
"""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .. import storage
from ..config import get_settings

GENESIS = "0" * 64
KEY_REL = "keys/dev_signing_ed25519.pem"
CLAIM_GENERATOR = "GroundProof/1.0 (dev self-signed)"


def _private_key() -> Ed25519PrivateKey:
    try:
        return serialization.load_pem_private_key(storage.get(KEY_REL), password=None)  # type: ignore[return-value]
    except FileNotFoundError:
        key = Ed25519PrivateKey.generate()
        storage.put(KEY_REL, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
        return key


def public_key_b64() -> str:
    raw = _private_key().public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()


def build_manifest(file_sha: str, plot_id: int, partner_id: int, captured_at: datetime, gps: dict[str, Any],
                   device: dict[str, Any], previous_hash: str) -> dict[str, Any]:
    return {"claim_generator": CLAIM_GENERATOR, "format": "c2pa-style/ed25519-v1",
            "assertions": {"c2pa.hash.data": {"alg": "sha256", "hash": file_sha},
                           "gp.location": gps, "gp.device": device,
                           "gp.capture": {"plot_id": plot_id, "partner_id": partner_id,
                                          "captured_at": captured_at.isoformat()},
                           "gp.chain": {"previous_hash": previous_hash}},
            "signing_mode": "dev-ed25519" if not get_settings().c2pa_cert_path else "c2pa-cert"}


def sign(manifest: dict[str, Any]) -> str:
    return base64.b64encode(_private_key().sign(canonical(manifest))).decode()


def chain_hash(previous_hash: str, file_sha: str, manifest: dict[str, Any]) -> str:
    return hashlib.sha256(previous_hash.encode() + file_sha.encode() + canonical(manifest)).hexdigest()


def verify_capture(file_bytes: bytes | None, manifest: dict[str, Any], signature: str, sha256: str,
                   previous_hash: str, stored_chain_hash: str) -> dict[str, Any]:
    checks = {"file_hash_matches": False, "signature_valid": False, "chain_hash_valid": False}
    if file_bytes is not None:
        actual = hashlib.sha256(file_bytes).hexdigest()
        checks["file_hash_matches"] = (actual == sha256 == manifest["assertions"]["c2pa.hash.data"]["hash"])
    try:
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64()))
        pub.verify(base64.b64decode(signature), canonical(manifest))
        checks["signature_valid"] = True
    except (InvalidSignature, ValueError):
        pass
    checks["chain_hash_valid"] = chain_hash(previous_hash, sha256, manifest) == stored_chain_hash
    return {"valid": all(checks.values()), **checks}


def embed_c2pa(path_in: str, path_out: str, manifest: dict[str, Any]) -> bool:  # pragma: no cover
    """Real C2PA embedding. Returns False (and the caller keeps the dev manifest) if not configured."""
    s = get_settings()
    if not (s.c2pa_cert_path and s.c2pa_key_path):
        return False
    try:
        import c2pa  # type: ignore
    except ImportError:
        return False
    with open(s.c2pa_cert_path, "rb") as c, open(s.c2pa_key_path, "rb") as k:
        signer = c2pa.create_signer(lambda data: _sign_with_pem(k.read(), data), "es256", c.read(), None)
    c2pa.Builder({"claim_generator": CLAIM_GENERATOR}).sign_file(path_in, path_out, signer)
    return True


def _sign_with_pem(pem: bytes, data: bytes) -> bytes:  # pragma: no cover
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    key = serialization.load_pem_private_key(pem, password=None)
    assert isinstance(key, ec.EllipticCurvePrivateKey)
    return key.sign(data, ec.ECDSA(hashes.SHA256()))
