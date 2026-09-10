from enum import StrEnum


class RateLimitScope(StrEnum):
    """API-6.23's permitted scope dimensions, narrowed to the v1 set approved
    in the Foundation-010 discovery/implementation plan.

    NETWORK_SOURCE is deliberately narrow: it exists only for the pre-
    authentication throttle on the credential-lookup path (Foundation-010
    discovery question 6/9) -- never generalize it into a scope available to
    every endpoint's configured rules. Tenant-configurable limits and a
    general network-source dimension remain explicit non-goals.
    """

    TENANT = "TENANT"
    CREDENTIAL = "CREDENTIAL"
    OPERATION = "OPERATION"
    NETWORK_SOURCE = "NETWORK_SOURCE"
