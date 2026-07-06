# Fund Autopsy Data Sources

## Primary: SEC EDGAR

### Form N-CEN (Annual Report for Registered Investment Companies)
- **Filing frequency:** Annual
- **Available from:** 2018 to present (replaced N-SAR)
- **Format:** XML (structured, machine-readable)
- **Key fields:** Brokerage commissions (C.6.a), soft dollar commissions (C.6.b), soft dollar transaction volume (C.6.c), portfolio turnover (C.7), total net assets (B.1)
- **Access:** EDGAR full-text search API or direct filing download

### Form N-PORT (Monthly Portfolio Holdings Report)
- **Filing frequency:** Monthly; full public disclosure quarterly (60 days after fiscal quarter end)
- **Available from:** 2019 to present
- **Format:** XML
- **Key fields:** Complete holdings list, market values, asset category, issuer category, percentage of net assets
- **Access:** EDGAR full-text search API or direct filing download

### Fund Prospectus / N-CSR
- **Purpose:** Expense ratio, fee table, fund objective
- **Access:** EDGAR full-text search; HTML parsing for fee tables

## Supplementary

### Yahoo Finance
- Current fund pricing, NAV, basic metadata
- Free tier access
- Used as fallback for expense ratio and category data

### CRSP Mutual Fund Database
- Academic/institutional use only
- Historical validation and backtesting
- Not required for core functionality

## Data Freshness

| Source | Update Frequency | Max Staleness |
|--------|-----------------|---------------|
| N-CEN | Annual | Up to 12 months |
| N-PORT | Quarterly (public) | Up to ~5 months |
| Prospectus | As amended | Variable |
| Yahoo Finance | Daily | 1 day |
