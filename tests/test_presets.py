import pytest

from babayaga.agents.mean_reversion import MeanReversionAgent
from babayaga.agents.presets import strategy_preset
from babayaga.agents.regime_switch import RegimeSwitchAgent
from babayaga.agents.technical import TechnicalAgent
from babayaga.integration.market_data import typical_price, typical_spread


def test_meanrev_preset():
    risk, specs = strategy_preset("meanrev")
    assert risk.min_trend_strength == 0.0
    # Signal-driven exit: no take-profit, wide catastrophic stop only.
    assert risk.atr_target_mult == 0.0
    assert risk.atr_stop_mult >= 4.0
    assert len(specs) == 1 and isinstance(specs[0], MeanReversionAgent)


def test_trend_preset():
    risk, specs = strategy_preset("trend")
    assert risk.min_trend_strength == 1.0
    assert risk.atr_target_mult == 6.0
    assert any(isinstance(s, TechnicalAgent) for s in specs)


def test_regime_preset():
    risk, specs = strategy_preset("regime")
    assert risk.min_trend_strength == 0.0  # the agent decides regime itself
    assert risk.atr_target_mult == 0.0     # signal-driven exit, winners run
    assert risk.atr_stop_mult >= 4.0       # wide catastrophic backstop only
    assert len(specs) == 1 and isinstance(specs[0], RegimeSwitchAgent)


def test_regime_preset_aliases():
    for alias in ("regime", "regime-switch", "REGIME", "regimeswitch"):
        _risk, specs = strategy_preset(alias)
        assert isinstance(specs[0], RegimeSwitchAgent)


def test_ensemble_preset_runs_all_strategies_together():
    risk, specs = strategy_preset("ensemble")
    assert risk.min_trend_strength == 0.0
    kinds = {type(s) for s in specs}
    assert RegimeSwitchAgent in kinds and MeanReversionAgent in kinds
    # Aliases resolve to the same committee.
    for alias in ("portfolio", "combo", "all", "ENSEMBLE"):
        _r, s = strategy_preset(alias)
        assert {type(x) for x in s} == kinds


def test_unknown_preset_raises():
    with pytest.raises(ValueError):
        strategy_preset("hodl")


def test_new_instruments_have_realistic_quotes():
    assert typical_price("GBP/JPY") == 190.0
    assert typical_spread("GBP/JPY") > typical_spread("EUR/USD")  # cross is wider
    assert typical_price("NAS100/USD") == 20000.0
    assert typical_spread("NAS100/USD") == 3.0


def test_backtest_symbol_mapping_for_new_files():
    from babayaga.backtest import symbol_from_filename

    assert symbol_from_filename("data/gbpjpy_d.csv") == "GBP/JPY"
    assert symbol_from_filename("data/nas100usd_d.csv") == "NAS100/USD"
