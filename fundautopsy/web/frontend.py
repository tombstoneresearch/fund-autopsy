"""Frontend serving layer — FastAPI static file handler.

Serves the interactive dashboard from static files (HTML, CSS, JS) instead
of embedding everything inline. This keeps the codebase clean and allows
independent frontend iteration.

The static files are organized as:
  fundautopsy/web/static/
    index.html     — Main page structure, references CSS/JS
    styles.css     — All styling (variables, components, layouts)
    app.js         — Client-side logic (search, fetch, rendering)

This module simply loads and serves index.html. All assets are referenced
with absolute paths (/static/...) in the HTML, allowing FastAPI to serve
them via its mount point.
"""

from __future__ import annotations

import os
from pathlib import Path


def get_dashboard_html() -> str:
    """Load dashboard HTML from static/index.html.

    Returns:
        The complete HTML document as a string.

    Raises:
        FileNotFoundError: If index.html cannot be found.
    """
    static_dir = Path(__file__).parent / "static"
    index_path = static_dir / "index.html"

    if not index_path.exists():
        raise FileNotFoundError(
            f"Dashboard HTML not found at {index_path}. "
            "Ensure fundautopsy/web/static/index.html exists."
        )

    return index_path.read_text(encoding="utf-8")


def get_portfolio_html() -> str:
    """Load portfolio-page HTML from static/portfolio.html."""
    static_dir = Path(__file__).parent / "static"
    portfolio_path = static_dir / "portfolio.html"
    if not portfolio_path.exists():
        raise FileNotFoundError(
            f"Portfolio HTML not found at {portfolio_path}. "
            "Ensure fundautopsy/web/static/portfolio.html exists."
        )
    return portfolio_path.read_text(encoding="utf-8")


# Cache the HTML to avoid disk reads on every request
# (FastAPI will reload this module in dev mode anyway)
try:
    DASHBOARD_HTML = get_dashboard_html()
except FileNotFoundError as e:
    # Graceful fallback if static files are missing
    DASHBOARD_HTML = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Fund Autopsy — Setup Error</title>
    <style>
        body {{ font-family: sans-serif; padding: 40px; background: #f5f5f5; }}
        .error {{ background: #fff; padding: 20px; border-radius: 8px;
                   border-left: 4px solid #ef4444; }}
        h1 {{ color: #ef4444; margin-top: 0; }}
        code {{ background: #f0f0f0; padding: 2px 6px; border-radius: 3px; }}
    </style>
</head>
<body>
    <div class="error">
        <h1>Dashboard Setup Error</h1>
        <p>Static files are missing. {e}</p>
        <p>Ensure the following files exist:</p>
        <ul>
            <li><code>fundautopsy/web/static/index.html</code></li>
            <li><code>fundautopsy/web/static/styles.css</code></li>
            <li><code>fundautopsy/web/static/app.js</code></li>
        </ul>
    </div>
</body>
</html>
    """

try:
    PORTFOLIO_HTML = get_portfolio_html()
except FileNotFoundError as e:
    PORTFOLIO_HTML = f"""
<!DOCTYPE html>
<html><head><title>Fund Autopsy — Portfolio TCO (setup error)</title></head>
<body style="font-family: sans-serif; padding: 40px;">
  <h1>Portfolio page not yet built</h1>
  <p>{e}</p>
</body></html>
    """
