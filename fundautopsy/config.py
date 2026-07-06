"""Centralized identity and configuration.

All public-facing identity strings live here. When bootstrapping under a
pseudonym, update this single file — every module, header, and template
reads from these values.
"""

import os as _os

# ── Public Identity ──────────────────────────────────────────────────────────
# Change these when setting up the fresh pseudonym / GitHub / email.
# Everything else in the codebase references these values.

ORG_NAME: str = "Tombstone Research"
ORG_TAGLINE: str = "Leave no stone unturned."
PROJECT_NAME: str = "Fund Autopsy"

# EDGAR requires a real contact email in the User-Agent header.
# SEC policy: https://www.sec.gov/os/accessing-edgar-data
# Use the pseudonym email once it's created.
CONTACT_EMAIL: str = "tombstoneresearch@proton.me"

# GitHub
GITHUB_ORG: str = "tombstoneresearch"
GITHUB_REPO: str = "fund-autopsy"
GITHUB_URL: str = f"https://github.com/{GITHUB_ORG}/{GITHUB_REPO}"

# ── EDGAR Access ─────────────────────────────────────────────────────────────
# SEC rate limit: 10 requests/second. We stay slightly under.
EDGAR_USER_AGENT: str = (
    f"{PROJECT_NAME}/0.1.0 ({CONTACT_EMAIL}; open-source fund cost analyzer)"
)
EDGAR_RATE_LIMIT_DELAY: float = 0.12  # seconds between requests

# ── Application ──────────────────────────────────────────────────────────────
APP_VERSION: str = "0.1.0"

# CORS: restrict to same-origin in production.
# Override via FUNDAUTOPSY_CORS_ORIGINS env var (comma-separated).
CORS_ALLOWED_ORIGINS: list[str] = [
    o.strip()
    for o in _os.environ.get("FUNDAUTOPSY_CORS_ORIGINS", "").split(",")
    if o.strip()
] or ["*"]

# Maximum size (bytes) for a single EDGAR XML download.
# N-PORT filings for mega-trusts can be 30-40 MB; 50 MB is generous.
MAX_XML_DOWNLOAD_BYTES: int = 50 * 1024 * 1024

# ── Dollar Impact Defaults ──────────────────────────────────────────────────
# Used by the web API and CLI when user doesn't specify custom values.
DEFAULT_INVESTMENT: float = 100_000  # $100k
DEFAULT_HORIZON_YEARS: int = 20
DEFAULT_ANNUAL_RETURN_PCT: float = 7.0  # 7% nominal
