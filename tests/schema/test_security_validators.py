"""
Tests for SecurityConfig schema validation (TODO-8).

Covers:
- auth_type="jwt" without jwt_algorithm → ValidationError
- auth_type="jwt", jwt_algorithm="RS256" without jwks_url → ValidationError
- auth_type="jwt", jwt_algorithm="HS256" → valid
- auth_type="jwt", jwt_algorithm="RS256", jwks_url="..." → valid
- auth_type="api_key" / "none" → valid
- Computed enable_auth property: True for api_key/jwt, False for none
- Legacy enable_auth=True/False translation
"""
import pytest
from pydantic import ValidationError

from agentforge.schema.models import SecurityConfig


# ── Sad paths ─────────────────────────────────────────────────────────────────

def test_jwt_without_algorithm_raises():
    """auth_type='jwt' without jwt_algorithm must raise ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        SecurityConfig(auth_type="jwt")  # type: ignore[call-arg]
    assert "jwt_algorithm" in str(exc_info.value).lower() or "jwt" in str(exc_info.value)


def test_jwt_rs256_without_jwks_url_raises():
    """auth_type='jwt' with RS256 but no jwks_url must raise ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        SecurityConfig(auth_type="jwt", jwt_algorithm="RS256")  # type: ignore[call-arg]
    assert "jwks_url" in str(exc_info.value).lower()


def test_jwt_rs256_empty_jwks_url_raises():
    """RS256 with an empty string jwks_url must raise ValidationError."""
    with pytest.raises(ValidationError):
        SecurityConfig(auth_type="jwt", jwt_algorithm="RS256", jwks_url="")  # type: ignore[call-arg]


# ── Happy paths ───────────────────────────────────────────────────────────────

def test_jwt_hs256_valid():
    """auth_type='jwt', jwt_algorithm='HS256' must be valid (no jwks_url needed)."""
    cfg = SecurityConfig(auth_type="jwt", jwt_algorithm="HS256")  # type: ignore[call-arg]
    assert cfg.auth_type == "jwt"
    assert cfg.jwt_algorithm == "HS256"
    assert cfg.jwks_url is None


def test_jwt_rs256_with_jwks_url_valid():
    """auth_type='jwt', RS256 + jwks_url must be valid."""
    cfg = SecurityConfig(  # type: ignore[call-arg]
        auth_type="jwt",
        jwt_algorithm="RS256",
        jwks_url="https://example.com/.well-known/jwks.json",
    )
    assert cfg.auth_type == "jwt"
    assert cfg.jwt_algorithm == "RS256"
    assert cfg.jwks_url == "https://example.com/.well-known/jwks.json"


def test_auth_type_api_key_valid():
    """auth_type='api_key' must be valid."""
    cfg = SecurityConfig(auth_type="api_key")  # type: ignore[call-arg]
    assert cfg.auth_type == "api_key"


def test_auth_type_none_valid():
    """auth_type='none' (default) must be valid."""
    cfg = SecurityConfig()  # type: ignore[call-arg]
    assert cfg.auth_type == "none"


def test_jwt_hs256_with_optional_issuer_audience():
    """JWT HS256 with optional issuer and audience must be valid."""
    cfg = SecurityConfig(  # type: ignore[call-arg]
        auth_type="jwt",
        jwt_algorithm="HS256",
        jwt_issuer="https://auth.example.com/",
        jwt_audience="my-api",
    )
    assert cfg.jwt_issuer == "https://auth.example.com/"
    assert cfg.jwt_audience == "my-api"


# ── enable_auth property ──────────────────────────────────────────────────────

def test_enable_auth_true_for_api_key():
    """enable_auth property must return True when auth_type='api_key'."""
    assert SecurityConfig(auth_type="api_key").enable_auth is True  # type: ignore[call-arg]


def test_enable_auth_true_for_jwt():
    """enable_auth property must return True when auth_type='jwt'."""
    assert SecurityConfig(auth_type="jwt", jwt_algorithm="HS256").enable_auth is True  # type: ignore[call-arg]


def test_enable_auth_false_for_none():
    """enable_auth property must return False when auth_type='none'."""
    assert SecurityConfig(auth_type="none").enable_auth is False  # type: ignore[call-arg]


def test_enable_auth_default_is_false():
    """Default SecurityConfig (auth_type='none') must have enable_auth=False."""
    assert SecurityConfig().enable_auth is False  # type: ignore[call-arg]


# ── Legacy enable_auth translation ───────────────────────────────────────────

def test_legacy_enable_auth_true_translates_to_api_key():
    """enable_auth=True (old field) must translate to auth_type='api_key'."""
    cfg = SecurityConfig(enable_auth=True)  # type: ignore[call-arg]
    assert cfg.auth_type == "api_key"
    assert cfg.enable_auth is True


def test_legacy_enable_auth_false_translates_to_none():
    """enable_auth=False (old field) must translate to auth_type='none'."""
    cfg = SecurityConfig(enable_auth=False)  # type: ignore[call-arg]
    assert cfg.auth_type == "none"
    assert cfg.enable_auth is False


def test_legacy_enable_auth_true_auth_type_wins():
    """When both enable_auth and auth_type are supplied, auth_type takes precedence."""
    cfg = SecurityConfig(enable_auth=True, auth_type="none")  # type: ignore[call-arg]
    assert cfg.auth_type == "none"
    assert cfg.enable_auth is False
