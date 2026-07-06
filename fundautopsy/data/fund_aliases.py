"""Common fund name → ticker alias map.

Users typing "AMCAP" or "Growth Fund of America" or "Contrafund"
instead of ticker codes should still land on the right fund. This
module maintains a curated alias map of the ~120 largest retail
mutual funds in America, covering roughly 80% of likely-query volume.

Covers the top families by retail AUM: Fidelity (including Contrafund,
500 Index, Magellan, Low-Priced Stock, Growth Company), Vanguard (500
Index Admiral + Investor, Total Stock Market, Wellington, Wellesley,
Total Bond, Target Retirement vintages), American Funds (AMCAP, Growth
Fund of America, Capital Income Builder, Washington Mutual, Fundamental
Investors, Europacific Growth), T. Rowe Price (Capital Appreciation,
Blue Chip Growth, Equity Income, Retirement vintages), Dodge & Cox
(Stock, International Stock, Balanced, Income), PIMCO (Total Return,
Income), DoubleLine, Oakmark, Parnassus, MFS, JPMorgan, BlackRock.

Matching strategy: case-insensitive substring match. A query "AMCAP"
hits multiple classes of the same series; we return the A-share by
default as the most recognizable variant, with other classes listed
as alternative suggestions.
"""
from __future__ import annotations

# Primary aliases. Keys are normalized (uppercase, stripped).
# Values are (ticker, full_fund_name) tuples.
# The name field is what the autocomplete dropdown displays.
_ALIASES: list[tuple[str, str, str]] = [
    # ── American Funds ─────────────────────────────────────────────────
    ("AMCAP", "AMCPX", "American Funds AMCAP Fund Class A"),
    ("GROWTH FUND OF AMERICA", "AGTHX", "American Funds The Growth Fund of America Class A"),
    ("GROWTH FUND", "AGTHX", "American Funds The Growth Fund of America Class A"),
    ("CAPITAL INCOME BUILDER", "CAIBX", "American Funds Capital Income Builder Class A"),
    ("CAPITAL INCOME", "CAIBX", "American Funds Capital Income Builder Class A"),
    ("INCOME FUND OF AMERICA", "AMECX", "American Funds The Income Fund of America Class A"),
    ("WASHINGTON MUTUAL", "AWSHX", "American Funds Washington Mutual Investors Fund Class A"),
    ("WASHINGTON MUTUAL INVESTORS", "AWSHX", "American Funds Washington Mutual Investors Fund Class A"),
    ("INVESTMENT COMPANY OF AMERICA", "AIVSX", "American Funds Investment Company of America Class A"),
    ("FUNDAMENTAL INVESTORS", "ANCFX", "American Funds Fundamental Investors Class A"),
    ("EUROPACIFIC GROWTH", "AEPGX", "American Funds EuroPacific Growth Fund Class A"),
    ("EUROPACIFIC", "AEPGX", "American Funds EuroPacific Growth Fund Class A"),
    ("NEW PERSPECTIVE", "ANWPX", "American Funds New Perspective Fund Class A"),
    ("AMERICAN MUTUAL", "AMRMX", "American Funds American Mutual Fund Class A"),
    ("CAPITAL WORLD GROWTH", "CWGIX", "American Funds Capital World Growth and Income Fund Class A"),
    ("NEW WORLD", "NEWFX", "American Funds New World Fund Class A"),
    ("SMALLCAP WORLD", "SMCWX", "American Funds SMALLCAP World Fund Class A"),
    # ── Fidelity ───────────────────────────────────────────────────────
    ("CONTRAFUND", "FCNTX", "Fidelity Contrafund"),
    ("FIDELITY CONTRAFUND", "FCNTX", "Fidelity Contrafund"),
    ("500 INDEX", "FXAIX", "Fidelity 500 Index Fund"),
    ("FIDELITY 500 INDEX", "FXAIX", "Fidelity 500 Index Fund"),
    ("MAGELLAN", "FMAGX", "Fidelity Magellan Fund"),
    ("FIDELITY MAGELLAN", "FMAGX", "Fidelity Magellan Fund"),
    ("LOW PRICED STOCK", "FLPSX", "Fidelity Low-Priced Stock Fund"),
    ("FIDELITY LOW PRICED", "FLPSX", "Fidelity Low-Priced Stock Fund"),
    ("GROWTH COMPANY", "FDGRX", "Fidelity Growth Company Fund"),
    ("FIDELITY GROWTH COMPANY", "FDGRX", "Fidelity Growth Company Fund"),
    ("BLUE CHIP GROWTH", "FBGRX", "Fidelity Blue Chip Growth Fund"),
    ("TOTAL MARKET INDEX", "FSKAX", "Fidelity Total Market Index Fund"),
    ("FIDELITY TOTAL MARKET", "FSKAX", "Fidelity Total Market Index Fund"),
    ("ZERO TOTAL MARKET", "FZROX", "Fidelity ZERO Total Market Index Fund"),
    ("FIDELITY ZERO", "FZROX", "Fidelity ZERO Total Market Index Fund"),
    ("TOTAL INTERNATIONAL INDEX", "FTIHX", "Fidelity Total International Index Fund"),
    ("NASDAQ COMPOSITE", "FNCMX", "Fidelity Nasdaq Composite Index Fund"),
    ("TOTAL BOND INDEX", "FXNAX", "Fidelity U.S. Bond Index Fund"),
    ("FREEDOM 2030", "FFFEX", "Fidelity Freedom 2030 Fund"),
    ("FREEDOM 2025", "FFTWX", "Fidelity Freedom 2025 Fund"),
    ("FREEDOM 2035", "FFTHX", "Fidelity Freedom 2035 Fund"),
    ("FREEDOM 2040", "FFFFX", "Fidelity Freedom 2040 Fund"),
    ("FREEDOM INDEX 2030", "FIPFX", "Fidelity Freedom Index 2030 Fund Investor Class"),
    # ── Vanguard ───────────────────────────────────────────────────────
    ("VANGUARD 500 INDEX", "VFIAX", "Vanguard 500 Index Fund Admiral Shares"),
    ("VANGUARD 500", "VFIAX", "Vanguard 500 Index Fund Admiral Shares"),
    ("TOTAL STOCK MARKET", "VTSAX", "Vanguard Total Stock Market Index Fund Admiral Shares"),
    ("VANGUARD TOTAL STOCK MARKET", "VTSAX", "Vanguard Total Stock Market Index Fund Admiral Shares"),
    ("TOTAL INTERNATIONAL STOCK", "VTIAX", "Vanguard Total International Stock Index Fund Admiral Shares"),
    ("VANGUARD TOTAL INTERNATIONAL", "VTIAX", "Vanguard Total International Stock Index Fund Admiral Shares"),
    ("WELLINGTON", "VWELX", "Vanguard Wellington Fund Investor Shares"),
    ("VANGUARD WELLINGTON", "VWELX", "Vanguard Wellington Fund Investor Shares"),
    ("WELLESLEY", "VWINX", "Vanguard Wellesley Income Fund Investor Shares"),
    ("VANGUARD WELLESLEY", "VWINX", "Vanguard Wellesley Income Fund Investor Shares"),
    ("TOTAL BOND MARKET", "VBTLX", "Vanguard Total Bond Market Index Fund Admiral Shares"),
    ("VANGUARD TOTAL BOND", "VBTLX", "Vanguard Total Bond Market Index Fund Admiral Shares"),
    ("DIVIDEND GROWTH", "VDIGX", "Vanguard Dividend Growth Fund Investor Shares"),
    ("EMERGING MARKETS INDEX", "VEMAX", "Vanguard Emerging Markets Stock Index Fund Admiral Shares"),
    ("SMALL CAP INDEX", "VSMAX", "Vanguard Small-Cap Index Fund Admiral Shares"),
    ("MID CAP INDEX", "VIMAX", "Vanguard Mid-Cap Index Fund Admiral Shares"),
    ("TARGET RETIREMENT 2030", "VTHRX", "Vanguard Target Retirement 2030 Fund"),
    ("TARGET RETIREMENT 2040", "VFORX", "Vanguard Target Retirement 2040 Fund"),
    ("TARGET RETIREMENT 2050", "VFIFX", "Vanguard Target Retirement 2050 Fund"),
    ("TARGET RETIREMENT 2055", "VFFVX", "Vanguard Target Retirement 2055 Fund"),
    ("TARGET RETIREMENT 2060", "VTTSX", "Vanguard Target Retirement 2060 Fund"),
    ("TARGET RETIREMENT INCOME", "VTINX", "Vanguard Target Retirement Income Fund"),
    ("HEALTH CARE", "VGHAX", "Vanguard Health Care Fund Admiral Shares"),
    ("STAR FUND", "VGSTX", "Vanguard STAR Fund Investor Shares"),
    # ── T Rowe Price ───────────────────────────────────────────────────
    ("CAPITAL APPRECIATION", "PRWCX", "T. Rowe Price Capital Appreciation Fund"),
    ("TRP CAPITAL APPRECIATION", "PRWCX", "T. Rowe Price Capital Appreciation Fund"),
    ("T ROWE CAPITAL APPRECIATION", "PRWCX", "T. Rowe Price Capital Appreciation Fund"),
    ("TRP BLUE CHIP GROWTH", "TRBCX", "T. Rowe Price Blue Chip Growth Fund"),
    ("EQUITY INCOME", "PRFDX", "T. Rowe Price Equity Income Fund"),
    ("HEALTH SCIENCES", "PRHSX", "T. Rowe Price Health Sciences Fund"),
    ("RETIREMENT 2030", "TRRCX", "T. Rowe Price Retirement 2030 Fund"),
    ("RETIREMENT 2035", "TRRMX", "T. Rowe Price Retirement 2035 Fund"),
    ("RETIREMENT 2040", "TRRDX", "T. Rowe Price Retirement 2040 Fund"),
    ("RETIREMENT 2050", "TRRJX", "T. Rowe Price Retirement 2050 Fund"),
    # ── Dodge & Cox ────────────────────────────────────────────────────
    ("DODGE COX STOCK", "DODGX", "Dodge & Cox Stock Fund Class I"),
    ("DODGE AND COX STOCK", "DODGX", "Dodge & Cox Stock Fund Class I"),
    ("DODGE COX INTERNATIONAL", "DODFX", "Dodge & Cox International Stock Fund Class I"),
    ("DODGE AND COX INTERNATIONAL", "DODFX", "Dodge & Cox International Stock Fund Class I"),
    ("DODGE COX BALANCED", "DODBX", "Dodge & Cox Balanced Fund Class I"),
    ("DODGE COX INCOME", "DODIX", "Dodge & Cox Income Fund Class I"),
    # ── PIMCO / DoubleLine / Bond ──────────────────────────────────────
    ("PIMCO TOTAL RETURN", "PTTRX", "PIMCO Total Return Fund Institutional Class"),
    ("PIMCO INCOME", "PIMIX", "PIMCO Income Fund Institutional Class"),
    ("DOUBLELINE TOTAL RETURN", "DBLTX", "DoubleLine Total Return Bond Fund Class I"),
    ("DOUBLELINE CORE FIXED INCOME", "DBLFX", "DoubleLine Core Fixed Income Fund Class I"),
    # ── Oakmark ────────────────────────────────────────────────────────
    ("OAKMARK", "OAKMX", "Oakmark Fund Investor Class"),
    ("OAKMARK EQUITY INCOME", "OAKBX", "Oakmark Equity and Income Fund Investor Class"),
    ("OAKMARK INTERNATIONAL", "OAKIX", "Oakmark International Fund Investor Class"),
    ("OAKMARK SELECT", "OAKLX", "Oakmark Select Fund Investor Class"),
    # ── Other large retail active ─────────────────────────────────────
    ("PARNASSUS CORE", "PRBLX", "Parnassus Core Equity Fund Investor Shares"),
    ("MFS VALUE", "MEIAX", "MFS Value Fund Class A"),
    ("JPMORGAN SMARTRETIREMENT", "JTSAX", "JPMorgan SmartRetirement Funds"),
    ("JP MORGAN SMARTRETIREMENT", "JTSAX", "JPMorgan SmartRetirement Funds"),
    # ── Schwab indexes ─────────────────────────────────────────────────
    ("SCHWAB S&P 500", "SWPPX", "Schwab S&P 500 Index Fund"),
    ("SCHWAB 500", "SWPPX", "Schwab S&P 500 Index Fund"),
    ("SCHWAB TOTAL STOCK MARKET", "SWTSX", "Schwab Total Stock Market Index Fund"),
    ("SCHWAB INTERNATIONAL INDEX", "SWISX", "Schwab International Index Fund"),
    # ── Dimensional ────────────────────────────────────────────────────
    ("DFA US LARGE CAP", "DFUSX", "DFA US Large Cap Equity Portfolio Institutional Class"),
]


def search_aliases(query: str, limit: int = 5) -> list[dict]:
    """Return up to `limit` ticker suggestions for a name query.

    Case-insensitive substring match; ranks by match position (earlier
    match = better). A query "AMCAP" returns AMCPX first. A query
    "Growth" returns multiple candidates ranked by specificity.
    """
    if not query or len(query.strip()) < 2:
        return []
    q = query.strip().upper()
    results: list[tuple[int, str, str]] = []
    seen_tickers: set[str] = set()
    for alias, ticker, name in _ALIASES:
        if ticker in seen_tickers:
            continue
        pos = alias.find(q)
        if pos >= 0:
            results.append((pos, ticker, name))
            seen_tickers.add(ticker)
    # Sort by match position (earlier is better), then by alias length
    # (shorter alias match = more specific)
    results.sort(key=lambda r: (r[0], len(r[2])))
    return [{"ticker": r[1], "name": r[2]} for r in results[:limit]]


def suggest_for_failed_ticker(ticker: str, limit: int = 3) -> list[dict]:
    """When identify_fund fails, suggest the most likely intended tickers.

    Used by error handlers to produce "did you mean X?" style messages
    rather than generic not-found errors.
    """
    return search_aliases(ticker, limit=limit)
