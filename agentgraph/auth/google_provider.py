# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
"""Google OAuth2 authentication provider.

Credentials are obtained via the OAuth2 browser flow (agentgraph auth google)
and stored in ~/.agentgraph/credentials.json.
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


def get_credentials() -> Any:
    """Return a valid google.auth.credentials.Credentials instance."""
    from google.auth.transport.requests import Request  # type: ignore[import-untyped]
    from google.oauth2.credentials import Credentials  # type: ignore[import-untyped]

    from agentgraph.auth.credentials import GoogleCredentials, update
    from agentgraph.auth.credentials import load as load_creds

    stored = load_creds()
    if stored.google is None:
        raise RuntimeError(
            "Google credentials not configured. Run: agentgraph auth google"
        )

    g = stored.google
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
        update(
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
    from agentgraph.auth.credentials import load as load_creds

    stored = load_creds()
    return stored.google.user_email if stored.google else None
