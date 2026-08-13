"""Google OAuth credentials shared by the Google connector package."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

GOOGLE_OAUTH_CLIENT_ID = "243010728161-k5ms99bjeg9n1ub464fgl4lbaf4dtp2q.apps.googleusercontent.com"
GOOGLE_OAUTH_CLIENT_SECRET = "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"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid",
]
GOOGLE_REAUTH_HINT = "run: agentgraph auth google"


class GoogleCredentials(BaseModel):
    """Per-account Google OAuth tokens stored in credentials.json."""

    client_id: str
    access_token: str
    refresh_token: str
    token_expiry: datetime | None = None
    user_email: str | None = None
    display_name: str | None = None


def _invalid_auth_detail(reason: str) -> str:
    return f"{reason} - {GOOGLE_REAUTH_HINT} to re-authorize Google"


def load_google_creds(account_id: str | None = None) -> tuple[GoogleCredentials, str]:
    from agentgraph.auth.credentials import load_platform_account

    data = load_platform_account("google", account_id)
    if data is None:
        raise RuntimeError("Google credentials not configured. Run: agentgraph auth google")
    creds = GoogleCredentials(**data)
    resolved_account_id = str(data.get("account_id") or creds.user_email or "google")
    return creds, resolved_account_id


def list_google_accounts() -> list[dict[str, str | None]]:
    from agentgraph.auth.credentials import load_platform_accounts

    results: list[dict[str, str | None]] = []
    for raw in load_platform_accounts("google"):
        try:
            creds = GoogleCredentials(**raw)
        except Exception:
            continue
        account_id = str(raw.get("account_id") or creds.user_email or "google")
        email = creds.user_email
        results.append(
            {
                "account_id": account_id,
                "email": email,
                "display_name": creds.display_name,
                "label": creds.display_name or email or account_id,
            }
        )
    return results


def get_credentials(account_id: str | None = None) -> Any:
    """Return a valid google-auth Credentials instance."""
    from google.auth.transport.requests import Request  # type: ignore[import-untyped]
    from google.oauth2.credentials import Credentials  # type: ignore[import-untyped]

    from agentgraph.auth.credentials import upsert_platform_account

    stored, resolved_account_id = load_google_creds(account_id)
    credentials = Credentials(
        token=stored.access_token,
        refresh_token=stored.refresh_token,
        token_uri=GOOGLE_TOKEN_URI,
        client_id=stored.client_id,
        client_secret=GOOGLE_OAUTH_CLIENT_SECRET,
        expiry=stored.token_expiry,
    )
    if not credentials.valid and credentials.refresh_token:
        credentials.refresh(Request())
        upsert_platform_account(
            "google",
            resolved_account_id,
            GoogleCredentials(
                client_id=stored.client_id,
                access_token=credentials.token or "",
                refresh_token=credentials.refresh_token or "",
                token_expiry=credentials.expiry,
                user_email=stored.user_email,
                display_name=stored.display_name,
            ),
            make_default=(account_id is None),
        )
    return credentials


def get_user_email(account_id: str | None = None) -> str | None:
    try:
        credentials, _ = load_google_creds(account_id)
    except Exception:
        return None
    return credentials.user_email


def verify_google_auth(account_id: str | None = None) -> tuple[str, str | None]:
    """Verify stored credentials by exercising the refresh token."""
    from pydantic import ValidationError

    from agentgraph.auth.credentials import load_platform_account

    data = load_platform_account("google", account_id)
    if data is None:
        return ("missing", None)

    try:
        stored = GoogleCredentials(**data)
    except ValidationError:
        return ("invalid", _invalid_auth_detail("stored Google credentials are unreadable"))

    if not stored.refresh_token:
        return ("invalid", _invalid_auth_detail("missing Google refresh token"))

    try:
        credentials = get_credentials(account_id) if account_id is not None else get_credentials()
    except Exception as exc:
        return (
            "invalid",
            _invalid_auth_detail(f"Google refresh token was rejected ({type(exc).__name__})"),
        )

    if not credentials.valid:
        return ("invalid", _invalid_auth_detail("Google token is expired"))

    return ("ok", data.get("user_email") or "authenticated")
