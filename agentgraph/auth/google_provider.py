# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
"""Google OAuth2 authentication provider.

Credentials are obtained via the OAuth2 browser flow (agentgraph auth google)
and stored in ~/.agentgraph/credentials.json under the 'google' key.
"""

from __future__ import annotations

from typing import Any

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid",
]

GOOGLE_REAUTH_HINT = "run: agentgraph auth google"


def _invalid_auth_detail(reason: str) -> str:
    return f"{reason} - {GOOGLE_REAUTH_HINT} to re-authorize Google"


def get_credentials() -> Any:
    """Return a valid google.auth.credentials.Credentials instance."""
    from google.auth.transport.requests import Request  # type: ignore[import-untyped]
    from google.oauth2.credentials import Credentials  # type: ignore[import-untyped]

    from agentgraph.auth.credentials import GoogleCredentials, load_platform, save_platform

    data = load_platform("google")
    if data is None:
        raise RuntimeError(
            "Google credentials not configured. Run: agentgraph auth google"
        )

    g = GoogleCredentials(**data)
    creds = Credentials(
        token=g.access_token,
        refresh_token=g.refresh_token,
        token_uri=g.token_uri,
        client_id=g.client_id,
        client_secret=g.client_secret,
        expiry=g.token_expiry,
    )
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        save_platform(
            "google",
            GoogleCredentials(
                client_id=g.client_id,
                client_secret=g.client_secret,
                access_token=creds.token or "",
                refresh_token=creds.refresh_token or "",
                token_expiry=creds.expiry,
                user_email=g.user_email,
                display_name=g.display_name,
            ),
        )
    return creds


def get_user_email() -> str | None:
    """Return the authenticated user's email, or None if unavailable."""
    from agentgraph.auth.credentials import load_platform

    data = load_platform("google")
    return data.get("user_email") if data else None


def verify_google_auth() -> tuple[str, str | None]:
    """Verify Google credentials by exercising the refresh token.

    Returns a (status, detail) tuple where status is "ok", "missing", or
    "invalid". On "ok", detail is the authenticated user_email; on
    "invalid", detail is a short error message.
    """
    from pydantic import ValidationError

    from agentgraph.auth.credentials import GoogleCredentials, load_platform

    data = load_platform("google")
    if data is None:
        return ("missing", None)

    try:
        stored = GoogleCredentials(**data)
    except ValidationError:
        return ("invalid", _invalid_auth_detail("stored Google credentials are unreadable"))

    if not stored.refresh_token:
        return ("invalid", _invalid_auth_detail("missing Google refresh token"))

    try:
        creds = get_credentials()
    except Exception as exc:
        return ("invalid", _invalid_auth_detail(f"Google refresh token was rejected ({type(exc).__name__})"))

    if not creds.valid:
        return ("invalid", _invalid_auth_detail("Google token is expired"))

    return ("ok", data.get("user_email") or "authenticated")
