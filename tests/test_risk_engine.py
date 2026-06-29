# ============================================================
# tests/test_risk_engine.py — Trading Bot Trading Bot
#
# AMAÇ:
#   RiskEngine ve RiskAssessment birim testleri.
#
# ÇALIŞTIRMA:
#   pytest tests/test_risk_engine.py -v
# ============================================================

from __future__ import annotations

import pytest
from datetime import datetime

from src.risk.engine import RiskEngine, RiskAssessment
from src.signal.models import SignalStrength, SignalType, TradeSignal
from src.config.settings import get_settings


@pytest.fixture
def risk_engine() -> RiskEngine:
    cfg = get_settings()
    cfg.risk.max_position_pct = 0.02  # %2 risk per trade
    cfg.risk.max_daily_drawdown_pct = 0.05  # %5 max drawdown
    cfg.risk.min_risk_reward_ratio = 2.0
    cfg.risk.normal_risk_pct = 0.10
    cfg.risk.high_risk_pct = 0.20
    cfg.execution.leverage = 1
    cfg.exchange.default_type = "spot"
    return RiskEngine(settings=cfg, initial_balance=10000.0)


@pytest.fixture
def actionable_buy_signal() -> TradeSignal:
    return TradeSignal(
        signal_type=SignalType.BUY,
        symbol="BTC/USDT",
        timeframe="4h",
        entry_price=30000.0,
        stop_loss=28500.0,  # %5 stop-loss mesafe
        take_profit=33000.0,  # %10 kâr hedefi (R/R = 2.0)
        risk_reward_ratio=2.0,
        weighted_score=0.75,
        signal_strength=SignalStrength.STRONG,
        confidence=0.70,
        is_paper_trade=True,
        reasons=("Test",),
        rejection_reasons=(),
    )


class TestRiskEngine:
    """RiskEngine birim testleri."""

    def test_initialization(self, risk_engine):
        """RiskEngine doğru şekilde başlatılmalı."""
        assert risk_engine._current_balance == 10000.0
        assert risk_engine.get_daily_drawdown_pct() == 0.0

    def test_non_actionable_signal_rejected(self, risk_engine):
        """HOLD veya NO_SIGNAL gibi işlemleşebilir olmayan sinyaller reddedilmeli."""
        hold_signal = TradeSignal(
            signal_type=SignalType.HOLD,
            symbol="BTC/USDT",
            timeframe="4h",
            entry_price=30000.0,
            stop_loss=28500.0,
            take_profit=33000.0,
            risk_reward_ratio=2.0,
            weighted_score=0.50,
            signal_strength=SignalStrength.WEAK,
            confidence=0.50,
            is_paper_trade=True,
            reasons=(),
            rejection_reasons=(),
        )
        assessment = risk_engine.assess(hold_signal)
        assert assessment.is_approved is False
        assert "işlemleşebilir" in assessment.rejection_reasons[0]

    def test_low_risk_reward_ratio_rejected(self, risk_engine, actionable_buy_signal):
        """Min limitin altındaki Risk/Ödül oranına sahip sinyaller reddedilmeli."""
        bad_rr_signal = TradeSignal(
            signal_type=SignalType.BUY,
            symbol="BTC/USDT",
            timeframe="4h",
            entry_price=30000.0,
            stop_loss=28500.0,
            take_profit=31500.0,  # R/R = 1.0 (Limit: 2.0)
            risk_reward_ratio=1.0,
            weighted_score=0.75,
            signal_strength=SignalStrength.STRONG,
            confidence=0.70,
            is_paper_trade=True,
            reasons=(),
            rejection_reasons=(),
        )
        assessment = risk_engine.assess(bad_rr_signal)
        assert assessment.is_approved is False
        assert any("Düşük Risk/Ödül" in r for r in assessment.rejection_reasons)

    def test_position_sizing_calculation(self, risk_engine, actionable_buy_signal):
        """Dinamik risk yüzdesiyle pozisyon boyutu doğru hesaplanmalı.
        Hesaplama:
          Bakiye = 10000
          Signal = STRONG -> risk_pct = high_risk_pct = 0.20 (Zarar bütçesi = 2000 USDT)
          SL = 30000 -> 28500 (SL mesafe = %5 = 0.05)
          Pozisyon boyutu = 2000 / 0.05 = 40000 USDT.
          Gereken kaldıraç = 40000 / 10000 = 4. Dolayısıyla leverage >= 4 olmalı.
        """
        risk_engine.settings.execution.leverage = 5  # Kaldıraç limiti 5x (max size = 50000)
        assessment = risk_engine.assess(actionable_buy_signal)
        assert assessment.is_approved is True
        assert assessment.position_size_usdt == 40000.0
        assert assessment.risk_pct == 0.20
        assert assessment.stop_loss_pct == 0.05

        # Normal sinyal testi (SignalStrength.MODERATE -> normal_risk_pct = 0.10)
        from dataclasses import replace
        moderate_signal = replace(actionable_buy_signal, signal_strength=SignalStrength.MODERATE)
        assessment_mod = risk_engine.assess(moderate_signal)
        # Bakiye = 10000, risk_pct = 0.10 (Zarar bütçesi = 1000 USDT)
        # SL = 5% -> Pozisyon boyutu = 1000 / 0.05 = 20000.0
        assert assessment_mod.is_approved is True
        assert assessment_mod.position_size_usdt == 20000.0
        assert assessment_mod.risk_pct == 0.10

    def test_position_size_capped_at_balance(self, risk_engine):
        """Hesaplanan pozisyon boyutu mevcut bakiyeyi aşamaz."""
        # SL mesafesi çok dar olsun (%0.1)
        # Bakiye = 10000, leverage = 1
        # Signal = STRONG -> high_risk_pct = 0.20 -> Risk bütçesi = 2000 USDT
        # Pozisyon boyutu = 2000 / 0.001 = 2,000,000 USDT
        # Capped at balance * leverage = 10,000 USDT
        dar_signal = TradeSignal(
            signal_type=SignalType.BUY,
            symbol="BTC/USDT",
            timeframe="4h",
            entry_price=30000.0,
            stop_loss=29970.0,  # %0.1
            take_profit=30600.0,  # R/R = 2.0
            risk_reward_ratio=2.0,
            weighted_score=0.75,
            signal_strength=SignalStrength.STRONG,
            confidence=0.70,
            is_paper_trade=True,
            reasons=(),
            rejection_reasons=(),
        )
        risk_engine.settings.execution.leverage = 1
        assessment = risk_engine.assess(dar_signal)
        assert assessment.is_approved is True
        assert assessment.position_size_usdt == 10000.0  # Bakiye ile sınırlandı!

    def test_kelly_position_sizing(self, risk_engine, actionable_buy_signal):
        """Kelly kriteri ile pozisyon boyutu hesaplanmalı."""
        # confidence=0.70, RR=2.0
        # kelly_fraction = p - q/b = 0.70 - 0.30/2.0 = 0.55
        # Half-Kelly = 0.55 / 2 = 0.275
        # Capped at risk_pct (0.20 for STRONG) -> Dolayısıyla risk_pct 0.20 olur.
        # Bakiye = 10000, leverage = 5
        risk_engine.settings.execution.leverage = 5
        assessment = risk_engine.assess(actionable_buy_signal, use_kelly=True)
        assert assessment.is_approved is True
        assert assessment.position_size_usdt == 40000.0

        # Başka bir senaryo: confidence = 0.45, RR = 2.0
        # kelly_fraction = 0.45 - 0.55/2 = 0.45 - 0.275 = 0.175
        # Half-Kelly = 0.0875
        # Kelly: risk_pct = Half-Kelly = 0.0875 (çünkü min(0.20, 0.0875) = 0.0875)
        # Pozisyon boyutu = (10000 * 0.0875) / 0.05 = 875 / 0.05 = 17500.0
        low_confidence_signal = TradeSignal(
            signal_type=SignalType.BUY,
            symbol="BTC/USDT",
            timeframe="4h",
            entry_price=30000.0,
            stop_loss=28500.0,  # %5 SL
            take_profit=33000.0,
            risk_reward_ratio=2.0,
            weighted_score=0.75,
            signal_strength=SignalStrength.STRONG,
            confidence=0.45,  # Düşük güven
            is_paper_trade=True,
            reasons=(),
            rejection_reasons=(),
        )
        assessment = risk_engine.assess(low_confidence_signal, use_kelly=True)
        assert assessment.is_approved is True
        assert assessment.position_size_usdt == 17500.0

    def test_daily_drawdown_limit(self, risk_engine, actionable_buy_signal):
        """Zarar limiti aşıldığında yeni işlemlere onay verilmemeli."""
        assert risk_engine.get_daily_drawdown_pct() == 0.0
        
        # 600 USDT zarar kaydet (Mevcut bakiye: 10000, drawdown: 600 / 10600 = %5.66 > Limit: %5.0)
        risk_engine.record_loss(600.0)
        assert risk_engine.get_daily_drawdown_pct() > 0.05
        
        assessment = risk_engine.assess(actionable_buy_signal)
        assert assessment.is_approved is False
        assert any("drawdown" in r.lower() for r in assessment.rejection_reasons)

    def test_invalid_prices_rejected(self, risk_engine):
        """Giriş fiyatı veya stop-loss sıfır veya negatif ise reddedilmeli."""
        invalid_signal = TradeSignal(
            signal_type=SignalType.BUY,
            symbol="BTC/USDT",
            timeframe="4h",
            entry_price=-10.0,  # Negatif
            stop_loss=28500.0,
            take_profit=33000.0,
            risk_reward_ratio=2.0,
            weighted_score=0.75,
            signal_strength=SignalStrength.STRONG,
            confidence=0.70,
            is_paper_trade=True,
            reasons=(),
            rejection_reasons=(),
        )
        assessment = risk_engine.assess(invalid_signal)
        assert assessment.is_approved is False
        assert any("Hatalı Fiyat Seviyeleri" in r for r in assessment.rejection_reasons)
