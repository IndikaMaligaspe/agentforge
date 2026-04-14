"""JWT authentication settings — values read from environment variables."""
import os


# Algorithm used to verify tokens. Matches the value in project.yaml.
JWT_ALGORITHM: str = os.environ.get("JWT_ALGORITHM", "RS256")

# Expected issuer claim (iss). Leave blank to skip issuer validation.
JWT_ISSUER: str | None = os.environ.get(
    "JWT_ISSUER",
"https://example.com",
)

# Expected audience claim (aud). Leave blank to skip audience validation.
JWT_AUDIENCE: str | None = os.environ.get(
    "JWT_AUDIENCE",
"full-stack-agent-api",
)

# JWKS endpoint URL — used to fetch the RS256 public keys.
JWKS_URL: str = os.environ.get("JWKS_URL", "https://example.com/.well-known/jwks.json")
