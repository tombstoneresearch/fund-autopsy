"""Tests for data retrieval modules."""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from fundautopsy.data.cache import DEFAULT_CACHE_DIR, FilingCache
from fundautopsy.data.edgar import (
    EDGAR_ARCHIVES_URL,
    EDGAR_MF_TICKERS_URL,
    EDGAR_SUBMISSIONS_URL,
    RATE_LIMIT_DELAY,
    FilingEntry,
    MutualFundIdentifier,
    _rate_limit,
    get_edgar_client,
    resolve_ticker,
)


class TestMutualFundIdentifier:
    """Test MutualFundIdentifier dataclass."""

    def test_identifier_construction(self):
        """MutualFundIdentifier should construct properly."""
        identifier = MutualFundIdentifier(
            ticker="VTSAX",
            cik=123456789,
            series_id="S000000001",
            class_id="C000000001",
        )
        assert identifier.ticker == "VTSAX"
        assert identifier.cik == 123456789
        assert identifier.series_id == "S000000001"
        assert identifier.class_id == "C000000001"

    def test_cik_padding(self):
        """CIK should be padded to 10 digits."""
        identifier = MutualFundIdentifier(
            ticker="TEST",
            cik=123,
            series_id="S000000001",
            class_id="C000000001",
        )
        assert identifier.cik_padded == "0000000123"
        assert len(identifier.cik_padded) == 10

    def test_cik_padding_already_10_digits(self):
        """CIK already 10 digits should not be padded further."""
        identifier = MutualFundIdentifier(
            ticker="TEST",
            cik=1234567890,
            series_id="S000000001",
            class_id="C000000001",
        )
        assert identifier.cik_padded == "1234567890"
        assert len(identifier.cik_padded) == 10


class TestFilingEntry:
    """Test FilingEntry dataclass."""

    def test_filing_entry_construction(self):
        """FilingEntry should construct with required fields."""
        entry = FilingEntry(
            form_type="N-CEN",
            filing_date="2025-03-15",
            accession_number="0000950140-25-001234",
            primary_document="form.htm",
        )
        assert entry.form_type == "N-CEN"
        assert entry.filing_date == "2025-03-15"
        assert entry.accession_number == "0000950140-25-001234"
        assert entry.primary_document == "form.htm"

    def test_filing_entry_optional_document(self):
        """Primary document should be optional."""
        entry = FilingEntry(
            form_type="N-PORT",
            filing_date="2025-03-15",
            accession_number="0000950140-25-001234",
        )
        assert entry.form_type == "N-PORT"
        assert entry.primary_document == ""


class TestEDGARClient:
    """Test EDGAR client creation."""

    def test_edgar_client_creation(self):
        """EDGAR client should be created."""
        client = get_edgar_client()
        assert client is not None
        assert hasattr(client, 'get')
        assert hasattr(client, 'close')

    def test_edgar_client_has_user_agent(self):
        """EDGAR client should have User-Agent header."""
        client = get_edgar_client()
        assert "User-Agent" in client.headers
        assert len(client.headers["User-Agent"]) > 0

    def test_edgar_client_user_agent_includes_email(self):
        """User-Agent should include contact email."""
        client = get_edgar_client()
        ua = client.headers["User-Agent"]
        assert "@" in ua or "open-source" in ua.lower()

    def test_edgar_client_timeout_set(self):
        """EDGAR client should have timeout."""
        client = get_edgar_client()
        assert client.timeout is not None
        # timeout can be a float or httpx.Timeout object; just verify it's set
        assert str(client.timeout) != "None"

    def test_edgar_client_closes_properly(self):
        """EDGAR client should close without error."""
        client = get_edgar_client()
        client.close()  # Should not raise


class TestRateLimit:
    """Test rate limiting."""

    def test_rate_limit_constant_positive(self):
        """Rate limit delay should be positive."""
        assert RATE_LIMIT_DELAY > 0
        assert RATE_LIMIT_DELAY <= 0.2

    def test_rate_limit_enforced(self):
        """Rate limiting should enforce minimum delay."""
        import time
        start = time.time()
        _rate_limit()
        _rate_limit()
        elapsed = time.time() - start
        # Should have enforced at least one delay period
        assert elapsed >= RATE_LIMIT_DELAY * 0.8  # Allow some margin


class TestEDGARURLs:
    """Test EDGAR endpoint URLs."""

    def test_submissions_url_valid(self):
        """Submissions URL should be valid."""
        assert EDGAR_SUBMISSIONS_URL is not None
        assert "sec.gov" in EDGAR_SUBMISSIONS_URL
        assert "submissions" in EDGAR_SUBMISSIONS_URL
        assert EDGAR_SUBMISSIONS_URL == "https://data.sec.gov/submissions"

    def test_archives_url_valid(self):
        """Archives URL should be valid."""
        assert EDGAR_ARCHIVES_URL is not None
        assert "sec.gov" in EDGAR_ARCHIVES_URL
        assert "edgar" in EDGAR_ARCHIVES_URL
        assert EDGAR_ARCHIVES_URL == "https://www.sec.gov/Archives/edgar/data"

    def test_mf_tickers_url_valid(self):
        """Mutual fund tickers URL should be valid."""
        assert EDGAR_MF_TICKERS_URL is not None
        assert "sec.gov" in EDGAR_MF_TICKERS_URL
        assert "tickers_mf.json" in EDGAR_MF_TICKERS_URL
        assert EDGAR_MF_TICKERS_URL == "https://www.sec.gov/files/company_tickers_mf.json"


class TestFilingCache:
    """Test filing cache."""

    def test_cache_initialization(self):
        """Cache should initialize with directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = FilingCache(cache_dir=Path(tmpdir))
            assert cache.cache_dir is not None
            assert cache.cache_dir.exists()

    def test_cache_creates_directory(self):
        """Cache should create directory if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "new_cache"
            assert not cache_path.exists()
            FilingCache(cache_dir=cache_path)
            assert cache_path.exists()

    def test_cache_xml_subdirectory_created(self):
        """Cache should create xml subdirectory on init."""
        with tempfile.TemporaryDirectory() as tmpdir:
            FilingCache(cache_dir=Path(tmpdir))
            assert (Path(tmpdir) / "xml").exists()

    def test_default_cache_dir_in_home(self):
        """Default cache dir should be in home directory."""
        assert DEFAULT_CACHE_DIR.is_absolute()
        assert ".fundautopsy" in str(DEFAULT_CACHE_DIR)

    def test_cache_put_and_get_xml(self):
        """Cache should store and retrieve XML bytes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = FilingCache(cache_dir=Path(tmpdir))
            test_data = b"<xml>test filing data</xml>"
            cache.put_xml(123456, "0001145549-24-069034", "primary_doc.xml", test_data)
            result = cache.get_xml(123456, "0001145549-24-069034", "primary_doc.xml")
            assert result == test_data

    def test_cache_miss_returns_none(self):
        """Cache miss should return None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = FilingCache(cache_dir=Path(tmpdir))
            result = cache.get_xml(999999, "0000000000-00-000000", "missing.xml")
            assert result is None

    def test_cache_disabled_returns_none(self):
        """Disabled cache should always return None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = FilingCache(cache_dir=Path(tmpdir), enabled=False)
            cache.put_xml(123456, "0001145549-24-069034", "doc.xml", b"<xml/>")
            result = cache.get_xml(123456, "0001145549-24-069034", "doc.xml")
            assert result is None

    def test_cache_clear_removes_files(self):
        """Cache clear should remove all cached files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = FilingCache(cache_dir=Path(tmpdir))
            cache.put_xml(123456, "0001145549-24-069034", "doc.xml", b"<xml/>")
            cache.clear()
            result = cache.get_xml(123456, "0001145549-24-069034", "doc.xml")
            assert result is None


class TestResolveTickerFunction:
    """Test ticker resolution (mocked to avoid actual SEC calls)."""

    @patch('fundautopsy.data.edgar._request_with_retry')
    @patch('fundautopsy.data.edgar.get_edgar_client')
    def test_resolve_ticker_returns_identifier(self, mock_get_client, mock_request):
        """Resolve ticker should return MutualFundIdentifier."""
        mock_resp = Mock()
        mock_resp.json.return_value = {
            "fields": ["cik", "seriesId", "classId", "symbol"],
            "data": [
                [1234567, "S000000001", "C000000001", "VTSAX"]
            ]
        }
        mock_request.return_value = mock_resp
        mock_get_client.return_value = Mock()

        result = resolve_ticker("VTSAX")

        assert result is not None
        assert result.ticker == "VTSAX"
        assert result.cik == 1234567

    @patch('fundautopsy.data.edgar._request_with_retry')
    @patch('fundautopsy.data.edgar.get_edgar_client')
    def test_resolve_ticker_case_insensitive(self, mock_get_client, mock_request):
        """Resolve ticker should be case-insensitive."""
        mock_resp = Mock()
        mock_resp.json.return_value = {
            "fields": ["cik", "seriesId", "classId", "symbol"],
            "data": [
                [1234567, "S000000001", "C000000001", "VTSAX"]
            ]
        }
        mock_request.return_value = mock_resp
        mock_get_client.return_value = Mock()

        result = resolve_ticker("vtsax")

        assert result is not None
        assert result.ticker == "VTSAX"

    @patch('fundautopsy.data.edgar._request_with_retry')
    @patch('fundautopsy.data.edgar.get_edgar_client')
    def test_resolve_ticker_not_found_returns_none(self, mock_get_client, mock_request):
        """Resolve ticker should return None if not found."""
        mock_resp = Mock()
        mock_resp.json.return_value = {
            "fields": ["cik", "seriesId", "classId", "symbol"],
            "data": []
        }
        mock_request.return_value = mock_resp
        mock_get_client.return_value = Mock()

        result = resolve_ticker("NOTREAL")

        assert result is None

    @patch('fundautopsy.data.edgar._request_with_retry')
    @patch('fundautopsy.data.edgar.get_edgar_client')
    def test_resolve_ticker_with_provided_client(self, mock_get_client, mock_request):
        """Resolve ticker should use provided client."""
        mock_resp = Mock()
        mock_resp.json.return_value = {
            "fields": ["cik", "seriesId", "classId", "symbol"],
            "data": [
                [1234567, "S000000001", "C000000001", "AGTHX"]
            ]
        }
        mock_request.return_value = mock_resp
        mock_client = Mock()

        result = resolve_ticker("AGTHX", client=mock_client)

        assert result is not None
        # Should not call get_edgar_client since we provided one
        mock_get_client.assert_not_called()


class TestEDGARConfiguration:
    """Test EDGAR configuration consistency."""

    def test_user_agent_string_well_formed(self):
        """User-Agent string should be well-formed per SEC guidelines."""
        client = get_edgar_client()
        ua = client.headers["User-Agent"]

        # Should have format: project/version (email; description)
        assert "/" in ua  # Version separator
        assert "(" in ua and ")" in ua  # Contact info
        assert "@" in ua or ";" in ua  # Email or separator

    def test_rate_limit_respects_sec_limits(self):
        """Rate limit should be at least 100ms (10 requests/sec)."""
        assert RATE_LIMIT_DELAY >= 0.10

    def test_all_endpoints_https(self):
        """All SEC endpoints should use HTTPS."""
        assert EDGAR_SUBMISSIONS_URL.startswith("https://")
        assert EDGAR_ARCHIVES_URL.startswith("https://")
        assert EDGAR_MF_TICKERS_URL.startswith("https://")
