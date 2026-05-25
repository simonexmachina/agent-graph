# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
"""Google OAuth2 authentication provider.

Credentials are obtained via the OAuth2 browser flow (agentgraph auth google)
and stored in the AgentGraph config directory under the 'google' key.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentgraph.auth.credentials import GoogleCredentials

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


def load_google_creds(account_id: str | None = None) -> tuple[GoogleCredentials, str]:
    from agentgraph.auth.credentials import GoogleCredentials, load_platform_account

    data = load_platform_account("google", account_id)
    if data is None:
        raise RuntimeError(
            "Google credentials not configured. Run: agentgraph auth google"
        )
    creds = GoogleCredentials(**data)
    resolved_account_id = str(data.get("account_id") or creds.user_email or "google")
    return creds, resolved_account_id


def list_google_accounts() -> list[dict[str, str | None]]:
    from agentgraph.auth.credentials import GoogleCredentials, load_platform_accounts

    results: list[dict[str, str | None]] = []
    for raw in load_platform_accounts("google"):
        try:
            creds = GoogleCredentials(**raw)
        except Exception:
            continue
        account_id = str(raw.get("account_id") or creds.user_email or "google")
        email = creds.user_email
        results.append({
            "account_id": account_id,
            "email": email,
            "display_name": creds.display_name,
            "label": creds.display_name or email or account_id,
        })
    return results


def get_credentials(account_id: str | None = None) -> Any:
    """Return a valid google.auth.credentials.Credentials instance."""
    from google.auth.transport.requests import Request  # type: ignore[import-untyped]
    from google.oauth2.credentials import Credentials  # type: ignore[import-untyped]

    from agentgraph.auth.credentials import GoogleCredentials, upsert_platform_account

    g, resolved_account_id = load_google_creds(account_id)
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
        upsert_platform_account(
            "google",
            resolved_account_id,
            GoogleCredentials(
                client_id=g.client_id,
                client_secret=g.client_secret,
                access_token=creds.token or "",
                refresh_token=creds.refresh_token or "",
                token_expiry=creds.expiry,
                user_email=g.user_email,
                display_name=g.display_name,
            ),
            make_default=(account_id is None),
        )
    return creds


def get_user_email(account_id: str | None = None) -> str | None:
    """Return the authenticated user's email, or None if unavailable."""
    try:
        creds, _ = load_google_creds(account_id)
    except Exception:
        return None
    return creds.user_email


def verify_google_auth(account_id: str | None = None) -> tuple[str, str | None]:
    """Verify Google credentials by exercising the refresh token.

    Returns a (status, detail) tuple where status is "ok", "missing", or
    "invalid". On "ok", detail is the authenticated user_email; on
    "invalid", detail is a short error message.
    """
    from pydantic import ValidationError

    from agentgraph.auth.credentials import GoogleCredentials, load_platform_account

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
        creds = get_credentials(account_id) if account_id is not None else get_credentials()
    except Exception as exc:
        return ("invalid", _invalid_auth_detail(f"Google refresh token was rejected ({type(exc).__name__})"))

    if not creds.valid:
        return ("invalid", _invalid_auth_detail("Google token is expired"))

    return ("ok", data.get("user_email") or "authenticated")
