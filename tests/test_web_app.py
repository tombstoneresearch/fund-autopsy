"""Tests for the web app module."""

from __future__ import annotations

from fundautopsy.web.app import (
    AssetMix,
    BrokerInfo,
    CostComponent,
    DollarImpact,
    FeeComponent,
    FundAnalysis,
    SecuritiesLendingInfo,
    ServiceProviders,
    app,
)


class TestCostComponent:
    """Tests for CostComponent model."""

    def test_create_with_fixed_value(self):
        """Should create CostComponent with fixed value."""
        comp = CostComponent(
            label="Brokerage Commissions",
            value="2.50 bps",
            tag="reported",
        )
        assert comp.label == "Brokerage Commissions"
        assert comp.value == "2.50 bps"
        assert comp.tag == "reported"

    def test_create_with_range(self):
        """Should create CostComponent with low/high range."""
        comp = CostComponent(
            label="Bid-Ask Spread",
            value=None,
            low=1.0,
            high=1.5,
            tag="estimated",
        )
        assert comp.low == 1.0
        assert comp.high == 1.5

    def test_create_with_note(self):
        """Should create CostComponent with note."""
        comp = CostComponent(
            label="Soft Dollars",
            value="ACTIVE",
            tag="not_disclosed",
            note="Amount not disclosed by fund",
        )
        assert comp.note == "Amount not disclosed by fund"


class TestFeeComponent:
    """Tests for FeeComponent model."""

    def test_create_fee_component(self):
        """Should create FeeComponent."""
        fee = FeeComponent(
            label="Management Fee",
            pct=0.50,
            bps=50.0,
        )
        assert fee.label == "Management Fee"
        assert fee.pct == 0.50
        assert fee.bps == 50.0

    def test_create_with_none_values(self):
        """Should create FeeComponent with None values."""
        fee = FeeComponent(
            label="12b-1 Fee",
            pct=None,
            bps=None,
        )
        assert fee.pct is None
        assert fee.bps is None


class TestAssetMix:
    """Tests for AssetMix model."""

    def test_create_asset_mix(self):
        """Should create AssetMix."""
        asset = AssetMix(
            category="EC",
            label="Equities",
            color="#4ade80",
            pct=70.0,
        )
        assert asset.category == "EC"
        assert asset.label == "Equities"
        assert asset.color == "#4ade80"
        assert asset.pct == 70.0


class TestBrokerInfo:
    """Tests for BrokerInfo model."""

    def test_create_broker_info(self):
        """Should create BrokerInfo."""
        broker = BrokerInfo(
            name="Goldman Sachs",
            commission=2.5,
            is_affiliated=True,
        )
        assert broker.name == "Goldman Sachs"
        assert broker.commission == 2.5
        assert broker.is_affiliated is True


class TestSecuritiesLendingInfo:
    """Tests for SecuritiesLendingInfo model."""

    def test_create_lending_active(self):
        """Should create SecuritiesLendingInfo when active."""
        lending = SecuritiesLendingInfo(
            is_lending=True,
            agent_name="Equilend",
            is_agent_affiliated=False,
            net_income=150_000,
            avg_value_on_loan=10_000_000,
        )
        assert lending.is_lending is True
        assert lending.agent_name == "Equilend"
        assert lending.net_income == 150_000

    def test_create_lending_inactive(self):
        """Should create SecuritiesLendingInfo when inactive."""
        lending = SecuritiesLendingInfo(is_lending=False)
        assert lending.is_lending is False
        assert lending.agent_name is None


class TestServiceProviders:
    """Tests for ServiceProviders model."""

    def test_create_service_providers(self):
        """Should create ServiceProviders."""
        providers = ServiceProviders(
            adviser="Vanguard",
            administrator="Vanguard",
            custodian="Vanguard",
            transfer_agent="Vanguard",
            auditor="Deloitte",
            is_admin_affiliated=True,
            is_transfer_agent_affiliated=True,
        )
        assert providers.adviser == "Vanguard"
        assert providers.is_admin_affiliated is True


class TestDollarImpact:
    """Tests for DollarImpact model."""

    def test_create_dollar_impact(self):
        """Should create DollarImpact."""
        impact = DollarImpact(
            investment=100_000,
            horizon_years=20,
            assumed_return_pct=7.0,
            expense_ratio_only_cost=5_000,
            true_cost_low=6_250,
            true_cost_high=7_500,
            hidden_cost_low=1_250,
            hidden_cost_high=2_500,
            final_value_er_only=380_000,
            final_value_true_low=357_500,
            final_value_true_high=340_000,
        )
        assert impact.investment == 100_000
        assert impact.horizon_years == 20
        assert impact.assumed_return_pct == 7.0


class TestFundAnalysis:
    """Tests for FundAnalysis model."""

    def test_create_fund_analysis_minimal(self):
        """Should create FundAnalysis with required fields."""
        analysis = FundAnalysis(
            ticker="VTSAX",
            name="Vanguard Total Stock Market",
            family="Vanguard",
            net_assets=500_000_000_000,
            net_assets_display="$500.0B",
            holdings_count=3000,
            period_end="2024-12-31",
            is_fund_of_funds=False,
            costs=[],
            total_hidden_low=10.0,
            total_hidden_high=15.0,
            asset_mix=[],
            data_notes=[],
            generated="2024-01-15",
        )
        assert analysis.ticker == "VTSAX"
        assert analysis.name == "Vanguard Total Stock Market"
        assert analysis.family == "Vanguard"

    def test_create_fund_analysis_full(self):
        """Should create FundAnalysis with optional fields."""
        analysis = FundAnalysis(
            ticker="VTSAX",
            name="Vanguard Total Stock Market",
            family="Vanguard",
            share_class="Investor Shares",
            net_assets=500_000_000_000,
            net_assets_display="$500.0B",
            holdings_count=3000,
            period_end="2024-12-31",
            is_fund_of_funds=False,
            costs=[],
            total_hidden_low=10.0,
            total_hidden_high=15.0,
            asset_mix=[],
            data_notes=[],
            generated="2024-01-15",
        )
        assert analysis.share_class == "Investor Shares"


class TestFastAPIApp:
    """Tests for the FastAPI app configuration."""

    def test_app_is_fastapi_instance(self):
        """App should be a FastAPI instance."""
        from fastapi import FastAPI

        assert isinstance(app, FastAPI)

    def test_app_has_title(self):
        """App should have a title."""
        assert app.title == "Fund Autopsy"

    def test_app_has_version(self):
        """App should have a version."""
        assert app.version == "0.1.0"

    def test_cors_middleware_configured(self):
        """App should have middleware configured."""
        # Check that middleware list exists
        assert len(app.user_middleware) > 0

    def test_has_analyze_route(self):
        """App should have /api/analyze/{ticker} route."""
        routes = [route.path for route in app.routes]
        assert "/api/analyze/{ticker}" in routes

    def test_has_sai_route(self):
        """App should have /api/sai/{ticker} route."""
        routes = [route.path for route in app.routes]
        assert "/api/sai/{ticker}" in routes

    def test_has_compare_route(self):
        """App should have /api/compare route."""
        routes = [route.path for route in app.routes]
        assert "/api/compare" in routes

    def test_has_root_route(self):
        """App should have / (root) route."""
        routes = [route.path for route in app.routes]
        assert "/" in routes


class TestRouteConfiguration:
    """Tests for route configuration."""

    def test_analyze_route_is_get(self):
        """Analyze route should use GET method."""
        for route in app.routes:
            if route.path == "/api/analyze/{ticker}":
                assert "GET" in route.methods

    def test_sai_route_is_get(self):
        """SAI route should use GET method."""
        for route in app.routes:
            if route.path == "/api/sai/{ticker}":
                assert "GET" in route.methods

    def test_compare_route_is_get(self):
        """Compare route should use GET method."""
        for route in app.routes:
            if route.path == "/api/compare":
                assert "GET" in route.methods

    def test_root_route_is_get(self):
        """Root route should use GET method."""
        for route in app.routes:
            if route.path == "/":
                assert "GET" in route.methods


class TestStaticFilesConfiguration:
    """Tests for static files configuration."""

    def test_static_files_mounted(self):
        """App should attempt to mount static files."""
        # This test verifies the app initialization doesn't crash
        # when static files don't exist (which is expected in tests)
        assert app is not None
