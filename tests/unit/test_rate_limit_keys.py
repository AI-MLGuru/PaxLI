import pytest

from core.rate_limit.enums import RateLimitScope
from core.rate_limit.keys import build_scope_key


def test_tenant_scope_key_is_deterministic() -> None:
    first = build_scope_key(RateLimitScope.TENANT, "verification_create", tenant_id="tenant-a")
    second = build_scope_key(RateLimitScope.TENANT, "verification_create", tenant_id="tenant-a")
    assert first == second


def test_different_tenants_produce_different_keys() -> None:
    a = build_scope_key(RateLimitScope.TENANT, "verification_create", tenant_id="tenant-a")
    b = build_scope_key(RateLimitScope.TENANT, "verification_create", tenant_id="tenant-b")
    assert a != b


def test_different_scopes_never_collide_even_with_matching_identifier_strings() -> None:
    """A TENANT key and a CREDENTIAL key built from the same literal string
    must never collide -- the scope name is embedded in the key itself."""
    tenant_key = build_scope_key(RateLimitScope.TENANT, "op", tenant_id="same-value")
    credential_key = build_scope_key(RateLimitScope.CREDENTIAL, "op", credential_id="same-value")
    assert tenant_key != credential_key


def test_operation_scope_key_has_no_tenant_or_credential_dimension() -> None:
    first = build_scope_key(RateLimitScope.OPERATION, "verification_create")
    second = build_scope_key(RateLimitScope.OPERATION, "verification_create")
    assert first == second


def test_network_source_scope_key_uses_the_pre_hashed_value_verbatim() -> None:
    """This module never sees a raw IP -- it only composes whatever string
    the caller passes as network_source_key (an HMAC digest, computed
    elsewhere in Phase 2/3)."""
    key = build_scope_key(
        RateLimitScope.NETWORK_SOURCE, "authenticate", network_source_key="deadbeef"
    )
    assert "deadbeef" in key


def test_tenant_scope_requires_tenant_id() -> None:
    with pytest.raises(ValueError, match="tenant_id"):
        build_scope_key(RateLimitScope.TENANT, "op")


def test_credential_scope_requires_credential_id() -> None:
    with pytest.raises(ValueError, match="credential_id"):
        build_scope_key(RateLimitScope.CREDENTIAL, "op")


def test_network_source_scope_requires_network_source_key() -> None:
    with pytest.raises(ValueError, match="network_source_key"):
        build_scope_key(RateLimitScope.NETWORK_SOURCE, "op")
