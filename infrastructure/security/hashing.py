import base64
import hashlib
import hmac
import os

_SCHEME = "scrypt"
_SALT_BYTES = 16
_KEY_BYTES = 32
_N = 2**14
_R = 8
_P = 1


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


class ScryptSecretHasher:
    def hash(self, secret: str) -> str:
        return hash_secret(secret)

    def verify(self, secret: str, verifier: str) -> bool:
        return verify_secret(secret, verifier)


def hash_secret(secret: str) -> str:
    salt = os.urandom(_SALT_BYTES)
    derived = hashlib.scrypt(
        secret.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_KEY_BYTES
    )
    return f"{_SCHEME}${_N}${_R}${_P}${_encode(salt)}${_encode(derived)}"


def verify_secret(secret: str, verifier: str) -> bool:
    try:
        scheme, n, r, p, encoded_salt, encoded_derived = verifier.split("$", 5)
        if scheme != _SCHEME:
            return False
        salt = base64.urlsafe_b64decode(encoded_salt.encode("ascii"))
        expected = base64.urlsafe_b64decode(encoded_derived.encode("ascii"))
        actual = hashlib.scrypt(
            secret.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False