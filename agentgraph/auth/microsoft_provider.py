"""Microsoft authentication providers.

Two implementations are available:
  - OAuthProvider    — custom OAuth2 flow, credentials stored in ~/.agentgraph/credentials.json
  - AzureCliProvider — uses `az account get-access-token` (az login)

Select via config: AGENTGRAPH_MICROSOFT_AUTH_PROVIDER=oauth|az
"""

from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod


class MicrosoftAuthProvider(ABC):
    @abstractmethod
    def get_access_token(self) -> str: ...

    @abstractmethod
    def get_user_email(self) -> str | None: ...


class OAuthProvider(MicrosoftAuthProvider):
    """Uses the OAuth2 credentials stored in ~/.agentgraph/credentials.json."""

    def get_access_token(self) -> str:
        from agentgraph.auth.microsoft import get_access_token
        return get_access_token()

    def get_user_email(self) -> str | None:
        from agentgraph.auth.credentials import load as load_creds
        stored = load_creds()
        return stored.microsoft.user_email if stored.microsoft else None


class AzureCliProvider(MicrosoftAuthProvider):
    """Uses `az account get-access-token` (requires `az login` first)."""

    _RESOURCE = "https://graph.microsoft.com"

    def get_access_token(self) -> str:
        try:
            result = subprocess.run(
                ["az", "account", "get-access-token",
                 "--resource", self._RESOURCE,
                 "--query", "accessToken",
                 "--output", "tsv"],
                capture_output=True,
                text=True,
                check=True,
            )
            token = result.stdout.strip()
            if not token:
                raise RuntimeError("az returned an empty token")
            return token
        except FileNotFoundError:
            raise RuntimeError(
                "Azure CLI not found. Install it from https://aka.ms/installazureclimacos "
                "then run: az login"
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"az account get-access-token failed: {exc.stderr.strip()}\n"
                "Run: az login"
            ) from exc

    def get_user_email(self) -> str | None:
        try:
            result = subprocess.run(
                ["az", "account", "show", "--query", "user.name", "--output", "tsv"],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip() or None
        except Exception:
            return None


def get_provider() -> MicrosoftAuthProvider:
    """Return the configured Microsoft auth provider."""
    from agentgraph.config import get_settings

    provider = get_settings().microsoft_auth_provider
    if provider == "az":
        return AzureCliProvider()
    return OAuthProvider()
