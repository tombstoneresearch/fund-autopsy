"""Pytest configuration and fixtures for FundAutopsy tests."""

from pathlib import Path

import pytest


@pytest.fixture
def agthx_ncen_xml() -> bytes:
    """Load N-CEN fixture file for Growth Fund of America (AGTHX)."""
    fixture_path = Path(__file__).parent / "fixtures" / "agthx_ncen_2024.xml"
    with open(fixture_path, "rb") as f:
        return f.read()


@pytest.fixture
def agthx_nport_xml() -> bytes:
    """Load N-PORT fixture file for Growth Fund of America (AGTHX)."""
    fixture_path = Path(__file__).parent / "fixtures" / "agthx_nport_2024.xml"
    with open(fixture_path, "rb") as f:
        return f.read()


@pytest.fixture
def agthx_series_id() -> str:
    """Series ID for Growth Fund of America (AGTHX)."""
    return "S000009228"
