"""Production transport-security guard (SEC-7.14.1 / PRV-11.22.1).

Averiq does not terminate the external client -> Averiq TLS hop itself --
that belongs to whatever reverse proxy sits in front of it (Webuzo or
equivalent), and isn't something this process can enforce. What this process
does own are its two outbound hops: object storage and the database. In
production, each MUST either use real transport encryption or have an
explicit operator attestation that its network path is private (e.g. a
Docker-internal network, a VPC-only link). If neither is true, the app fails
to start rather than silently trusting an unconfigured deployment.

`internal_transport_trusted` is a deliberate escape hatch, not a default:
it exists because "every internal hop must always be public TLS" is the
wrong requirement when the real topology already confines that traffic to a
private network. It's on the operator to attest that honestly.
"""

from apps.api.paxli_api.config import Settings


class InsecureProductionConfigurationError(RuntimeError):
    """Raised when a production deployment can't establish its required
    transport-security guarantees and refuses to start."""


def _database_url_requests_ssl(database_url: str) -> bool:
    # Declarative check against the connection string, not a live TLS
    # handshake verification -- consistent with `internal_transport_trusted`
    # being an attestation, not a runtime-verified guarantee.
    lowered = database_url.lower()
    return "sslmode=require" in lowered or "sslmode=verify" in lowered or "ssl=true" in lowered


def validate_production_transport_security(settings: Settings) -> None:
    if settings.app_env != "production":
        return

    if not settings.storage_secure and not settings.internal_transport_trusted:
        raise InsecureProductionConfigurationError(
            "APP_ENV=production requires STORAGE_SECURE=true (TLS to object "
            "storage) or INTERNAL_TRANSPORT_TRUSTED=true (an explicit "
            "operator attestation that the object-storage network path is "
            "private)."
        )

    if (
        not _database_url_requests_ssl(settings.database_url)
        and not settings.internal_transport_trusted
    ):
        raise InsecureProductionConfigurationError(
            "APP_ENV=production requires DATABASE_URL to request SSL "
            "(sslmode=require, sslmode=verify-*, or ssl=true) or "
            "INTERNAL_TRANSPORT_TRUSTED=true."
        )
