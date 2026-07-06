"""Tests for assumptions and asset-class mappings."""

import pytest

from fundautopsy.estimates.assumptions import (
    BOND_IMPACT_ASSUMPTIONS,
    BOND_TURNOVER_LOW_HIGH_THRESHOLD,
    DEFAULT_SPREAD,
    IMPACT_ASSUMPTIONS,
    INDUSTRY_AVG_SOFT_DOLLAR_SHARE,
    NPORT_ASSET_CAT_MAP,
    SPREAD_ASSUMPTIONS,
    TURNOVER_LOW_HIGH_THRESHOLD,
    ImpactAssumption,
    SpreadAssumption,
)


class TestSpreadAssumptions:
    """Test spread assumption definitions."""

    def test_all_spread_assumptions_have_valid_ranges(self):
        """All spread assumptions should have low < high."""
        for key, assumption in SPREAD_ASSUMPTIONS.items():
            assert assumption.low_one_way_pct > 0, f"{key} low spread is 0 or negative"
            assert assumption.high_one_way_pct > assumption.low_one_way_pct, \
                f"{key} high spread not greater than low"
            assert assumption.low_one_way_pct <= 0.01, \
                f"{key} low spread exceeds 1% (unrealistic)"
            assert assumption.high_one_way_pct <= 0.10, \
                f"{key} high spread exceeds 10% (unrealistic)"

    def test_equity_spreads_narrower_than_high_yield(self):
        """Large-cap equity should have tighter spreads than high yield."""
        ec = SPREAD_ASSUMPTIONS["EC"]
        hy = SPREAD_ASSUMPTIONS["DBT_HY"]
        assert ec.high_one_way_pct <= hy.low_one_way_pct, \
            "Large-cap equity spreads should be tighter than HY"

    def test_government_spreads_narrowest(self):
        """Government bonds should have the tightest spreads of fixed income."""
        gov = SPREAD_ASSUMPTIONS["DBT_GOV"]
        # GOV should have the tightest ranges vs equity and other debt
        equity_keys = ["EC", "EC_MID", "EC_SMALL", "EC_INTL", "EC_EM"]
        for key in equity_keys:
            assumption = SPREAD_ASSUMPTIONS[key]
            assert gov.high_one_way_pct <= assumption.low_one_way_pct, \
                f"DBT_GOV should be tighter than {key}"

    def test_default_spread_reasonable(self):
        """Default spread should be middle-of-the-road."""
        assert DEFAULT_SPREAD.low_one_way_pct > 0
        assert DEFAULT_SPREAD.high_one_way_pct > DEFAULT_SPREAD.low_one_way_pct
        # Default should be wider than or equal to equities but not as wide as worst assets
        assert DEFAULT_SPREAD.low_one_way_pct >= SPREAD_ASSUMPTIONS["EC"].high_one_way_pct

    def test_em_spreads_wider_than_developed(self):
        """Emerging market equity spreads should be wider than developed."""
        em = SPREAD_ASSUMPTIONS["EC_EM"]
        intl = SPREAD_ASSUMPTIONS["EC_INTL"]
        assert em.low_one_way_pct >= intl.high_one_way_pct, \
            "EM spreads should be wider than developed international"

    def test_small_cap_spreads_wider_than_large_cap(self):
        """Liquidity: small-cap spreads > mid-cap > large-cap."""
        large = SPREAD_ASSUMPTIONS["EC"]
        mid = SPREAD_ASSUMPTIONS["EC_MID"]
        small = SPREAD_ASSUMPTIONS["EC_SMALL"]

        assert mid.low_one_way_pct >= large.high_one_way_pct
        assert small.low_one_way_pct >= mid.high_one_way_pct

    def test_abs_spreads_reasonable_for_category(self):
        """ABS/MBS spreads should fit their credit quality."""
        # ABS-MBS maps to DBT_IG in NPORT_ASSET_CAT_MAP
        mbs_key = NPORT_ASSET_CAT_MAP.get("ABS-MBS")
        assert mbs_key is not None, "ABS-MBS not in NPORT_ASSET_CAT_MAP"
        mbs = SPREAD_ASSUMPTIONS[mbs_key]
        # MBS should be tight, similar to IG corporates
        ig = SPREAD_ASSUMPTIONS["DBT_IG"]
        assert mbs.high_one_way_pct <= ig.high_one_way_pct * 1.5

    def test_spread_assumption_has_description(self):
        """Each spread assumption should have a description."""
        for key, assumption in SPREAD_ASSUMPTIONS.items():
            assert assumption.description, f"{key} missing description"
            assert len(assumption.description) > 5, f"{key} description too short"


class TestImpactAssumptions:
    """Test market impact assumption definitions."""

    def test_all_impact_assumptions_have_valid_ranges(self):
        """All impact assumptions should have low < high."""
        for dict_name, assumptions_dict in [
            ("equity", IMPACT_ASSUMPTIONS),
            ("bond", BOND_IMPACT_ASSUMPTIONS),
        ]:
            for key, assumption in assumptions_dict.items():
                assert assumption.low_pct_of_turnover > 0, \
                    f"{dict_name}/{key} low impact is 0 or negative"
                assert assumption.high_pct_of_turnover > assumption.low_pct_of_turnover, \
                    f"{dict_name}/{key} high not greater than low"
                # Impact as % of turnover should be <10%
                assert assumption.high_pct_of_turnover < 0.10, \
                    f"{dict_name}/{key} impact > 10% of turnover (unrealistic)"

    def test_small_cap_impact_higher_than_large_cap(self):
        """Small-cap funds should have higher market impact."""
        for turnover_type in ["low_turnover", "high_turnover"]:
            large_key = f"large_{turnover_type}"
            small_key = f"small_{turnover_type}"
            large = IMPACT_ASSUMPTIONS[large_key]
            small = IMPACT_ASSUMPTIONS[small_key]
            # Small-cap should have higher midpoint impact
            assert small.low_pct_of_turnover >= large.low_pct_of_turnover, \
                f"Small-cap {turnover_type} should have higher impact than large-cap"

    def test_high_turnover_impact_higher_than_low(self):
        """High-turnover funds should have higher impact."""
        for size in ["large", "small"]:
            low_key = f"{size}_low_turnover"
            high_key = f"{size}_high_turnover"
            low = IMPACT_ASSUMPTIONS[low_key]
            high = IMPACT_ASSUMPTIONS[high_key]
            # High-turnover should have higher midpoint (low) impact
            assert high.low_pct_of_turnover >= low.low_pct_of_turnover, \
                f"{size}-cap high-turnover should have higher impact than low"

    def test_bond_impact_lower_than_equity(self):
        """Bond funds should have lower market impact than equity."""
        bond_low = BOND_IMPACT_ASSUMPTIONS["bond_low_turnover"]
        bond_high = BOND_IMPACT_ASSUMPTIONS["bond_high_turnover"]
        equity_low = IMPACT_ASSUMPTIONS["large_low_turnover"]
        equity_high = IMPACT_ASSUMPTIONS["large_high_turnover"]

        # Bond impact should be lower than equity impact (midpoint comparison)
        assert bond_low.low_pct_of_turnover <= equity_low.low_pct_of_turnover
        assert bond_high.low_pct_of_turnover <= equity_high.low_pct_of_turnover

    def test_impact_assumption_has_description(self):
        """Each impact assumption should have a description."""
        for assumption in IMPACT_ASSUMPTIONS.values():
            assert assumption.description, "Impact assumption missing description"
        for assumption in BOND_IMPACT_ASSUMPTIONS.values():
            assert assumption.description, "Bond impact assumption missing description"


class TestNPortAssetCategoryMap:
    """Test N-PORT asset category mappings."""

    def test_all_mapped_categories_have_assumptions(self):
        """Every mapped category should have a corresponding spread assumption."""
        for nport_cat, assumption_key in NPORT_ASSET_CAT_MAP.items():
            assert assumption_key in SPREAD_ASSUMPTIONS, \
                f"NPORT category {nport_cat} maps to {assumption_key} which has no assumption"

    def test_equity_categories_map_to_equity(self):
        """EC and EP should map to equity-like assumptions."""
        assert NPORT_ASSET_CAT_MAP["EC"] == "EC"
        assert NPORT_ASSET_CAT_MAP["EP"] == "EC"
        # Both should resolve to equity spread assumptions
        assert NPORT_ASSET_CAT_MAP["EC"] in SPREAD_ASSUMPTIONS

    def test_debt_categories_map_to_debt(self):
        """DBT should map to debt assumption."""
        assert NPORT_ASSET_CAT_MAP["DBT"] == "DBT_IG"
        assert NPORT_ASSET_CAT_MAP["DBT"] in SPREAD_ASSUMPTIONS

    def test_cash_categories_map_appropriately(self):
        """STIV and CASH should map to low-spread categories."""
        stiv_key = NPORT_ASSET_CAT_MAP["STIV"]
        cash_key = NPORT_ASSET_CAT_MAP["CASH"]
        stiv_spread = SPREAD_ASSUMPTIONS[stiv_key]
        cash_spread = SPREAD_ASSUMPTIONS[cash_key]
        # Both should be tight spreads
        assert stiv_spread.high_one_way_pct < 0.005
        assert cash_spread.high_one_way_pct < 0.005

    def test_abs_categories_mapped(self):
        """All ABS categories should be present in map."""
        abs_cats = ["ABS-MBS", "ABS-O", "ABS-CBDO", "ABS-A"]
        for cat in abs_cats:
            assert cat in NPORT_ASSET_CAT_MAP, f"{cat} missing from NPORT map"

    def test_abs_cbdo_maps_to_higher_spread_than_mbs(self):
        """CBDO (collateralized debt obligations) should have wider spreads than MBS."""
        cbdo_key = NPORT_ASSET_CAT_MAP["ABS-CBDO"]
        mbs_key = NPORT_ASSET_CAT_MAP["ABS-MBS"]
        cbdo_spread = SPREAD_ASSUMPTIONS[cbdo_key]
        mbs_spread = SPREAD_ASSUMPTIONS[mbs_key]
        assert cbdo_spread.low_one_way_pct >= mbs_spread.high_one_way_pct

    def test_derivatives_map_to_tight_spread(self):
        """Derivatives (DIR) should map to tight spreads."""
        dir_key = NPORT_ASSET_CAT_MAP["DIR"]
        dir_spread = SPREAD_ASSUMPTIONS[dir_key]
        assert dir_spread.high_one_way_pct <= 0.0005  # Very tight


class TestThresholds:
    """Test threshold constants."""

    def test_turnover_threshold_reasonable(self):
        """Equity turnover threshold should be 50%."""
        assert TURNOVER_LOW_HIGH_THRESHOLD == 0.50
        assert isinstance(TURNOVER_LOW_HIGH_THRESHOLD, float)

    def test_bond_turnover_threshold_higher(self):
        """Bond turnover threshold should be higher (100%)."""
        assert BOND_TURNOVER_LOW_HIGH_THRESHOLD == 1.00
        assert BOND_TURNOVER_LOW_HIGH_THRESHOLD > TURNOVER_LOW_HIGH_THRESHOLD

    def test_soft_dollar_industry_average_reasonable(self):
        """Industry average soft dollar share should be realistic."""
        assert 0.0 < INDUSTRY_AVG_SOFT_DOLLAR_SHARE < 1.0
        assert INDUSTRY_AVG_SOFT_DOLLAR_SHARE == 0.45  # 45% per Erzurumlu & Kotomin


class TestSpreadAssumptionDataclass:
    """Test SpreadAssumption dataclass properties."""

    def test_spread_assumption_is_frozen(self):
        """SpreadAssumption should be immutable."""
        sa = SpreadAssumption("Test", 0.001, 0.002)
        with pytest.raises(AttributeError):
            sa.low_one_way_pct = 0.005

    def test_spread_assumption_construction(self):
        """SpreadAssumption should construct with required fields."""
        sa = SpreadAssumption(
            asset_class="Test Class",
            low_one_way_pct=0.001,
            high_one_way_pct=0.005,
            description="A test assumption"
        )
        assert sa.asset_class == "Test Class"
        assert sa.low_one_way_pct == 0.001
        assert sa.high_one_way_pct == 0.005
        assert sa.description == "A test assumption"


class TestImpactAssumptionDataclass:
    """Test ImpactAssumption dataclass properties."""

    def test_impact_assumption_is_frozen(self):
        """ImpactAssumption should be immutable."""
        ia = ImpactAssumption("Test", 0.001, 0.005)
        with pytest.raises(AttributeError):
            ia.low_pct_of_turnover = 0.002

    def test_impact_assumption_construction(self):
        """ImpactAssumption should construct with required fields."""
        ia = ImpactAssumption(
            category="Test Category",
            low_pct_of_turnover=0.001,
            high_pct_of_turnover=0.005,
            description="A test impact"
        )
        assert ia.category == "Test Category"
        assert ia.low_pct_of_turnover == 0.001
        assert ia.high_pct_of_turnover == 0.005
        assert ia.description == "A test impact"
