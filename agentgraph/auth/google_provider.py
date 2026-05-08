# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
"""Google authentication providers.

Two implementations are available:
  - OAuthProvider  — custom OAuth2 flow, credentials stored in ~/.agentgraph/credentials.json
  - GCloudProvider — uses Application Default Credentials via `gcloud auth application-default login`

Select via config: AGENTGRAPH_GOOGLE_AUTH_PROVIDER=oauth|gcloud
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class GoogleAuthProvider(ABC):
    """Returns a refreshed google-auth Credentials object and the user's email."""

    @abstractmethod
    def get_credentials(self) -> Any:
        """Return a valid google.auth.credentials.Credentials instance."""
        ...

    @abstractmethod
    def get_user_email(self) -> str | None:
        """Return the authenticated user's email, or None if unavailable."""
        ...


class OAuthProvider(GoogleAuthProvider):
    """Uses the OAuth2 credentials stored in ~/.agentgraph/credentials.json."""

    def get_credentials(self) -> Any:
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

    def get_user_email(self) -> str | None:
        from agentgraph.auth.credentials import load as load_creds

        stored = load_creds()
        return stored.google.user_email if stored.google else None


GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid",
]

# Comma-separated for passing to gcloud --scopes flag
GCLOUD_SCOPES_ARG = ",".join(GOOGLE_SCOPES)


def run_gcloud_login() -> None:
    """Run `gcloud auth application-default login` with the required scopes.

    Note: Drive and Sheets scopes are blocked for the default gcloud client ID.
    This only works if you supply a custom --client-id-file. For most users,
    use the OAuth flow instead: agentgraph auth google (with provider=oauth).
    """
    import subprocess
    import typer

    typer.echo(
        "Warning: gcloud ADC blocks Drive/Sheets scopes for the default client ID.\n"
        "If you see scope errors, switch to OAuth: set AGENTGRAPH_GOOGLE_AUTH_PROVIDER=oauth\n"
        "and re-run: agentgraph auth google\n"
    )
    result = subprocess.run(
        ["gcloud", "auth", "application-default", "login",
         f"--scopes={GCLOUD_SCOPES_ARG},https://www.googleapis.com/auth/cloud-platform"],
        check=False,
    )
    if result.returncode != 0:
        typer.echo("gcloud login failed.", err=True)


class GCloudProvider(GoogleAuthProvider):
    """Uses Application Default Credentials (gcloud auth application-default login)."""

    def get_credentials(self) -> Any:
        import google.auth  # type: ignore[import-untyped]
        from google.auth.transport.requests import Request  # type: ignore[import-untyped]

        creds, _ = google.auth.default(scopes=GOOGLE_SCOPES)
        if hasattr(creds, "refresh") and not creds.valid:
            creds.refresh(Request())
        return creds

    def get_user_email(self) -> str | None:
        try:
            import requests  # type: ignore[import-untyped]
            from google.auth.transport.requests import Request  # type: ignore[import-untyped]

            creds = self.get_credentials()
            if not creds.valid:
                creds.refresh(Request())
            resp = requests.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {creds.token}"},
                timeout=10,
            )
            if resp.ok:
                return resp.json().get("email")
        except Exception:
            pass
        return None


def get_provider() -> GoogleAuthProvider:
    """Return the configured Google auth provider."""
    from agentgraph.config import get_settings

    provider = get_settings().google_auth_provider
    if provider == "gcloud":
        return GCloudProvider()
    return OAuthProvider()
