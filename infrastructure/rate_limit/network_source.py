import base64
import hashlib
import hmac
import os
from functools import lru_cache


def hash_network_source(ip: str, *, key_id: str, key: bytes) -> str:
    """HMAC-SHA256 of a raw client IP, keyed by a dedicated, governed
    network-source secret -- never the credential secret-hashing key, never
    the evidence-encryption key (Foundation-010 review guardrail #4). The
    raw IP is used only as HMAC input here and never returned, stored, or
    logged -- core.rate_limit.keys.build_scope_key only ever sees this
    digest."""
    digest = hmac.new(key, ip.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{key_id}:{digest}"


def _load_key(encoded_key: str | None) -> bytes:
    if not encoded_key:
        return os.urandom(32)
    return base64.b64decode(encoded_key)


@lru_cache
def get_network_source_hmac_key(*, key_id: str, encoded_key: str | None) -> bytes:
    return _load_key(encoded_key)
