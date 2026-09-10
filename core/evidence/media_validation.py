"""Server-side evidence media validation (SEC-7.22.2).

Establishes the media type from the actual file bytes, independent of the
client-supplied Content-Type header, which MUST NOT be trusted alone. Scoped
to the image formats Averiq actually accepts today (selfie/document/liveness
capture); this is signature verification, not content/malware scanning.
"""

_JPEG_SIGNATURE = b"\xff\xd8\xff"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_RIFF_HEADER = b"RIFF"
_WEBP_MARKER = b"WEBP"


class UnsupportedMediaError(ValueError):
    """Raised when uploaded evidence bytes don't match an allowed, verified format."""


def detect_image_mime_type(content: bytes) -> str | None:
    if content.startswith(_JPEG_SIGNATURE):
        return "image/jpeg"
    if content.startswith(_PNG_SIGNATURE):
        return "image/png"
    if len(content) >= 12 and content[0:4] == _RIFF_HEADER and content[8:12] == _WEBP_MARKER:
        return "image/webp"
    return None


def verify_evidence_media(content: bytes) -> str:
    """Returns the verified mime type, or raises `UnsupportedMediaError`."""
    detected = detect_image_mime_type(content)
    if detected is None:
        raise UnsupportedMediaError("Unsupported or unrecognized file format")
    return detected
