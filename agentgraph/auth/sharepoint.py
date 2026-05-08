"""SharePoint cookie-based authentication flow."""

from __future__ import annotations

_INSTRUCTIONS = """\

SharePoint uses browser session cookies for authentication.
To get your cookies:

  1. Open your SharePoint site in Chrome/Edge/Firefox and sign in
  2. Open DevTools (F12) → Application tab → Cookies (left sidebar)
  3. Click the SharePoint domain (e.g. contoso-my.sharepoint.com)
  4. Find 'FedAuth' (and 'rtFa' if present) — right-click each → Copy Value

Then run:
  agentgraph auth sharepoint --domain contoso-my.sharepoint.com \\
      --fed-auth "<FedAuth value>"

Note: cookies expire after ~24 hours. Re-run the command to refresh them.
"""


def run_cookie_flow(
    domain: str | None = None,
    fed_auth: str | None = None,
    rt_fa: str | None = None,
) -> None:
    """Store SharePoint browser cookies for a site."""
    import typer

    from agentgraph.auth.credentials import SharePointSiteCredentials, load, save

    if not domain or not fed_auth:
        typer.echo(_INSTRUCTIONS)
        if not domain:
            domain = typer.prompt("SharePoint domain (e.g. contoso-my.sharepoint.com)")
        if not fed_auth:
            fed_auth = typer.prompt("FedAuth cookie value")

    assert domain and fed_auth  # guaranteed by prompts above
    domain = domain.strip().removeprefix("https://").removeprefix("http://").rstrip("/")
    fed_auth = fed_auth.strip()
    rt_fa = rt_fa.strip() if rt_fa else None

    creds = load()
    sites = [s for s in creds.sharepoint if s.domain != domain]
    sites.append(SharePointSiteCredentials(domain=domain, fed_auth=fed_auth, rt_fa=rt_fa))
    save(creds.model_copy(update={"sharepoint": sites}))

    typer.echo(f"SharePoint credentials saved for {domain}.")


def get_cookies_for_domain(domain: str) -> dict[str, str]:
    """Return cookie dict for the given domain (may be empty if not configured)."""
    from agentgraph.auth.credentials import load

    creds = load()
    for site in creds.sharepoint:
        if site.domain == domain or domain.endswith(f".{site.domain}"):
            cookies: dict[str, str] = {"FedAuth": site.fed_auth}
            if site.rt_fa:
                cookies["rtFa"] = site.rt_fa
            return cookies
    return {}


def get_cookies_for_url(url: str) -> dict[str, str]:
    """Return cookies for the SharePoint domain in a URL (may be empty if not configured)."""
    from urllib.parse import urlparse
    domain = urlparse(url).netloc
    return get_cookies_for_domain(domain)
