# ============================================================
# tests/test_execution_engine.py — Trading Bot Trading Bot
#
# AMAÇ:
#   ExecutionEngine ve ilgili modeller için pytest birim testleri.
#
# ÇALIŞTIRMA:
#   pytest tests/test_execution_engine.py -v
# ============================================================

from __future__ import annotations

import os
from datetime import datetime
from unittest.mock import MagicMock, patch
import pytest

from src.config.settings import get_settings
from src.execution.engine import ExecutionEngine
from src.execution.models import MarketPosition, OrderStatus, OrderType, PositionSide, TradeOrder
from src.risk.engine import RiskAssessment, RiskEngine
from src.signal.models import SignalStrength, SignalType, TradeSignal


@pytest.fixture
def clean_state_file(tmp_path):
    """Her test için benzersiz ve temiz bir durum dosyası yolu."""
    return tmp_path / "test_portfolio_state.json"


@pytest.fixture
def risk_engine():
    cfg = get_settings()
    cfg.risk.max_position_pct = 0.02
    cfg.risk.min_risk_reward_ratio = 2.0
    return RiskEngine(settings=cfg, initial_balance=10000.0)


@pytest.fixture
def execution_engine(clean_state_file, risk_engine):
    cfg = get_settings()
    cfg.paper_trading.initial_balance_usdt = 10000.0
    cfg.paper_trading.commission_rate = 0.001  # %0.1
    cfg.execution.order_type = "market"
    engine = ExecutionEngine(
        settings=cfg,
        risk_engine=risk_engine,
        state_dir=str(clean_state_file.parent),
        state_file=clean_state_file.name
    )
    return engine


@pytest.fixture
def buy_signal():
    return TradeSignal(
        signal_type=SignalType.BUY,
        symbol="BTC/USDT",
        timeframe="4h",
        entry_price=30000.0,
        stop_loss=28500.0,  # %5 SL
        take_profit=33000.0,  # R/R = 2.0
        risk_reward_ratio=2.0,
        weighted_score=0.78,
        signal_strength=SignalStrength.STRONG,
        confidence=0.75,
        is_paper_trade=True,
        reasons=(),
        rejection_reasons=(),
    )


@pytest.fixture
def sell_signal():
    return TradeSignal(
        signal_type=SignalType.SELL,
        symbol="BTC/USDT",
        timeframe="4h",
        entry_price=31000.0,
        stop_loss=0.0,
        take_profit=0.0,
        risk_reward_ratio=0.0,
        weighted_score=0.32,
        signal_strength=SignalStrength.STRONG,
        confidence=0.70,
        is_paper_trade=True,
        reasons=(),
        rejection_reasons=(),
    )


class TestExecutionEngine:
    """ExecutionEngine işlevsel birim testleri."""

    def test_initialization(self, execution_engine):
        """Başlatma ayarları kontrolü."""
        assert execution_engine.usdt_balance == 10000.0
        assert len(execution_engine.open_positions) == 0
        assert len(execution_engine.orders) == 0
        assert execution_engine.is_paper_trade is True

    def test_execute_approved_buy_signal(self, execution_engine, buy_signal):
        """Onaylı bir alış sinyali pozisyon açmalı ve bakiyeyi düşürmeli."""
        # Risk değerlendirmesi
        assessment = RiskAssessment(
            is_approved=True,
            position_size_usdt=4000.0,
            risk_pct=0.02,
            stop_loss_pct=0.05
        )

        order = execution_engine.execute_signal(buy_signal, assessment)
        
        # Sipariş doğrulama
        assert order is not None
        assert order.status == OrderStatus.FILLED
        assert order.side == "buy"
        assert order.price == 30000.0
        assert order.amount == 4000.0 / 30000.0
        assert order.fee_usdt == 4.0  # 4000 * 0.001 = 4.0 USDT

        # Bakiye ve pozisyon kontrolü
        # Bakiye = 10000 - (4000 + 4) = 5996
        assert execution_engine.usdt_balance == 5996.0
        assert "BTC/USDT" in execution_engine.open_positions
        
        pos = execution_engine.open_positions["BTC/USDT"]
        assert pos.entry_price == 30000.0
        assert pos.amount == 4000.0 / 30000.0
        assert pos.stop_loss == 28500.0
        assert pos.take_profit == 33000.0

    def test_insufficient_balance_for_buy(self, execution_engine, buy_signal):
        """Bakiye yetersizse sipariş başarısız olmalı ve pozisyon açılmamalı."""
        assessment = RiskAssessment(
            is_approved=True,
            position_size_usdt=11000.0,  # Bakiye 10,000'den büyük
            risk_pct=0.02,
            stop_loss_pct=0.05
        )
        
        order = execution_engine.execute_signal(buy_signal, assessment)
        assert order is not None
        assert order.status == OrderStatus.FAILED
        assert order.error_message == "Insufficient balance"
        assert len(execution_engine.open_positions) == 0
        assert execution_engine.usdt_balance == 10000.0

    def test_execute_sell_closes_position(self, execution_engine, buy_signal, sell_signal):
        """Satış sinyali açık olan pozisyonu kapatmalı ve bakiyeyi güncelleştirmeli."""
        # 1. Pozisyon aç
        assessment = RiskAssessment(
            is_approved=True,
            position_size_usdt=3000.0,
            risk_pct=0.02,
            stop_loss_pct=0.05
        )
        execution_engine.execute_signal(buy_signal, assessment)
        assert "BTC/USDT" in execution_engine.open_positions

        # 2. Satış yap (Fiyat: 31000.0)
        # Miktar: 3000 / 30000 = 0.1 BTC
        # Gelir: 0.1 * 31000 = 3100 USDT
        # Komisyon: 3100 * 0.001 = 3.1 USDT
        # Net Gelir: 3100 - 3.1 = 3096.9 USDT
        # Bakiye = (10000 - 3003) + 3096.9 = 6997 + 3096.9 = 10093.9 USDT
        # Kar: 3096.9 - 3000 = 96.9 USDT
        order = execution_engine.execute_signal(sell_signal, None)
        
        assert order is not None
        assert order.status == OrderStatus.FILLED
        assert order.side == "sell"
        assert order.price == 31000.0
        assert order.fee_usdt == 3.1
        
        assert "BTC/USDT" not in execution_engine.open_positions
        assert abs(execution_engine.usdt_balance - 10093.9) < 0.01

    def test_monitor_positions_stop_loss(self, execution_engine, buy_signal):
        """Fiyat stop-loss sınırına geldiğinde pozisyon otomatik kapanmalı."""
        assessment = RiskAssessment(
            is_approved=True,
            position_size_usdt=3000.0,
            risk_pct=0.02,
            stop_loss_pct=0.05
        )
        execution_engine.execute_signal(buy_signal, assessment)

        # Fiyatı stop seviyesine (28500 veya altı) çek
        current_prices = {"BTC/USDT": 28400.0}
        closed_orders = execution_engine.monitor_positions(current_prices)
        
        assert len(closed_orders) == 1
        assert closed_orders[0].side == "sell"
        assert closed_orders[0].price == 28400.0
        assert "BTC/USDT" not in execution_engine.open_positions

    def test_monitor_positions_take_profit(self, execution_engine, buy_signal):
        """Fiyat take-profit sınırına geldiğinde pozisyon otomatik kapanmalı."""
        assessment = RiskAssessment(
            is_approved=True,
            position_size_usdt=3000.0,
            risk_pct=0.02,
            stop_loss_pct=0.05
        )
        execution_engine.execute_signal(buy_signal, assessment)

        # Fiyatı kâr al seviyesine (33000 veya üstü) çek
        current_prices = {"BTC/USDT": 33100.0}
        closed_orders = execution_engine.monitor_positions(current_prices)
        
        assert len(closed_orders) == 1
        assert closed_orders[0].side == "sell"
        assert closed_orders[0].price == 33100.0
        assert "BTC/USDT" not in execution_engine.open_positions

    def test_persistence_save_and_load(self, execution_engine, buy_signal):
        """Durum dosyası başarıyla kaydedilmeli ve yüklenebilmeli."""
        assessment = RiskAssessment(
            is_approved=True,
            position_size_usdt=3000.0,
            risk_pct=0.02,
            stop_loss_pct=0.05
        )
        execution_engine.execute_signal(buy_signal, assessment)
        
        # Dosya yazıldı mı?
        assert execution_engine.state_path.exists()
        
        # Yeni bir motor oluştur ve yükle
        cfg = get_settings()
        risk = RiskEngine(settings=cfg, initial_balance=10000.0)
        new_engine = ExecutionEngine(
            settings=cfg,
            risk_engine=risk,
            state_dir=str(execution_engine.state_path.parent),
            state_file=execution_engine.state_path.name
        )
        
        assert new_engine.usdt_balance == execution_engine.usdt_balance
        assert "BTC/USDT" in new_engine.open_positions
        assert len(new_engine.orders) == 1
        assert new_engine.open_positions["BTC/USDT"].cost_usdt == 3000.0

    def test_execute_buy_sends_oco_in_live_mode(self, clean_state_file, risk_engine, buy_signal):
        """Canlı modda pozisyon açılırken borsaya OCO emri gönderilmeli."""
        cfg = get_settings()
        cfg.trading_mode = "live"  # Canlı mod
        cfg.paper_trading.enabled = False
        cfg.execution.order_type = "market"
        cfg.exchange.default_type = "spot"
        
        # Mock Exchange
        mock_exchange = MagicMock()
        mock_exchange.amount_to_precision.return_value = "0.1"
        mock_exchange.price_to_precision.side_effect = lambda sym, price: str(price)
        
        # Market buy mock response
        mock_exchange.create_order.return_value = {
            "id": "market_buy_123",
            "average": 30000.0,
            "filled": 0.1,
            "fee": {"cost": 4.0}
        }
        
        # OCO mock response
        mock_exchange.privatePostOrderOco.return_value = {
            "orderListId": "oco_list_999",
            "orders": [
                {"orderId": "limit_111", "type": "LIMIT_MAKER"},
                {"orderId": "stop_222", "type": "STOP_LOSS_LIMIT"}
            ]
        }
        
        engine = ExecutionEngine(
            settings=cfg,
            risk_engine=risk_engine,
            exchange=mock_exchange,
            state_dir=str(clean_state_file.parent),
            state_file=clean_state_file.name
        )
        
        assessment = RiskAssessment(
            is_approved=True,
            position_size_usdt=3000.0,
            risk_pct=0.02,
            stop_loss_pct=0.05
        )
        
        order = engine.execute_signal(buy_signal, assessment)
        
        assert order is not None
        assert order.status == OrderStatus.FILLED
        
        # OCO alanlarını doğrula
        pos = engine.open_positions["BTC/USDT"]
        assert pos.oco_order_list_id == "oco_list_999"
        assert pos.oco_limit_order_id == "limit_111"
        assert pos.oco_stop_order_id == "stop_222"
        
        # Mock çağrılarını doğrula
        mock_exchange.privatePostOrderOco.assert_called_once()

    def test_close_position_cancels_oco_in_live_mode(self, clean_state_file, risk_engine, buy_signal, sell_signal):
        """Canlı modda pozisyon erken kapatılırsa OCO emri iptal edilmeli."""
        cfg = get_settings()
        cfg.trading_mode = "live"
        cfg.paper_trading.enabled = False
        cfg.execution.order_type = "market"
        cfg.exchange.default_type = "spot"
        
        mock_exchange = MagicMock()
        mock_exchange.amount_to_precision.return_value = "0.1"
        mock_exchange.price_to_precision.side_effect = lambda sym, price: str(price)
        
        # Setup position
        pos = MarketPosition(
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            entry_price=30000.0,
            amount=0.1,
            cost_usdt=3000.0,
            stop_loss=28500.0,
            take_profit=33000.0,
            oco_order_list_id="oco_list_999",
            oco_limit_order_id="limit_111",
            oco_stop_order_id="stop_222"
        )
        
        engine = ExecutionEngine(
            settings=cfg,
            risk_engine=risk_engine,
            exchange=mock_exchange,
            state_dir=str(clean_state_file.parent),
            state_file=clean_state_file.name
        )
        engine.open_positions["BTC/USDT"] = pos
        
        # Mock sell responses
        mock_exchange.create_order.return_value = {
            "id": "market_sell_456",
            "average": 31000.0,
            "filled": 0.1,
            "fee": {"cost": 3.1}
        }
        
        engine.execute_signal(sell_signal, None)
        
        # OCO iptal çağrısını doğrula
        mock_exchange.privateDeleteOrderList.assert_called_once_with({
            'symbol': 'BTCUSDT',
            'orderListId': 'oco_list_999'
        })
        assert "BTC/USDT" not in engine.open_positions

    def test_monitor_positions_closes_locally_on_oco_fill(self, clean_state_file, risk_engine):
        """Canlı modda OCO emirlerinden biri dolarsa, pozisyon lokalde kapatılmalı."""
        cfg = get_settings()
        cfg.trading_mode = "live"
        cfg.paper_trading.enabled = False
        cfg.execution.order_type = "market"
        cfg.exchange.default_type = "spot"
        
        mock_exchange = MagicMock()
        
        # Setup position
        pos = MarketPosition(
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            entry_price=30000.0,
            amount=0.1,
            cost_usdt=3000.0,
            stop_loss=28500.0,
            take_profit=33000.0,
            oco_order_list_id="oco_list_999",
            oco_limit_order_id="limit_111",
            oco_stop_order_id="stop_222"
        )
        
        engine = ExecutionEngine(
            settings=cfg,
            risk_engine=risk_engine,
            exchange=mock_exchange,
            state_dir=str(clean_state_file.parent),
            state_file=clean_state_file.name
        )
        engine.open_positions["BTC/USDT"] = pos
        
        # Limit emri 'closed' döndürelim (Take Profit gerçekleşti)
        mock_exchange.fetch_order.side_effect = lambda order_id, symbol: {
            "id": order_id,
            "status": "closed",
            "price": 33000.0
        }
        
        closed_orders = engine.monitor_positions({})
        
        assert len(closed_orders) == 1
        assert closed_orders[0].side == "sell"
        assert closed_orders[0].close_reason == "TAKE PROFIT TRIGGERED"
        assert "BTC/USDT" not in engine.open_positions

    def test_limit_buy_creates_pending_position(self, clean_state_file, risk_engine, buy_signal):
        """Limit alım emrinin beklemede (pending) pozisyon oluşturmasını doğrula."""
        cfg = get_settings()
        cfg.trading_mode = "paper"
        cfg.paper_trading.enabled = True
        cfg.execution.order_type = "limit"  # Limit mod

        engine = ExecutionEngine(
            settings=cfg,
            risk_engine=risk_engine,
            state_dir=str(clean_state_file.parent),
            state_file=clean_state_file.name
        )

        assessment = RiskAssessment(
            is_approved=True,
            position_size_usdt=3000.0,
            risk_pct=0.02,
            stop_loss_pct=0.05
        )

        order = engine.execute_signal(buy_signal, assessment)

        assert order is not None
        assert order.status == OrderStatus.PENDING
        assert order.order_type == OrderType.LIMIT

        # Pozisyon open_positions içinde olmalı ama beklemede (pending) olmalı
        assert "BTC/USDT" in engine.open_positions
        pos = engine.open_positions["BTC/USDT"]
        assert pos.status == "pending"
        assert pos.limit_order_id == order.order_id

        # USDT bakiyesi düşmüş olmalı (kilitlenmiş)
        # 10000 - 3003 = 6997
        assert engine.usdt_balance == 6997.0

    def test_monitor_positions_fills_limit_buy_in_paper(self, clean_state_file, risk_engine, buy_signal):
        """Paper modda fiyat limit fiyatına veya altına indiğinde limit alımın gerçekleşmesini doğrula."""
        cfg = get_settings()
        cfg.trading_mode = "paper"
        cfg.paper_trading.enabled = True
        cfg.execution.order_type = "limit"

        engine = ExecutionEngine(
            settings=cfg,
            risk_engine=risk_engine,
            state_dir=str(clean_state_file.parent),
            state_file=clean_state_file.name
        )

        assessment = RiskAssessment(
            is_approved=True,
            position_size_usdt=3000.0,
            risk_pct=0.02,
            stop_loss_pct=0.05
        )

        engine.execute_signal(buy_signal, assessment)
        assert engine.open_positions["BTC/USDT"].status == "pending"

        # Fiyat limit fiyatından (30000.0) yüksekse dolmamalı
        engine.monitor_positions({"BTC/USDT": 30500.0})
        assert engine.open_positions["BTC/USDT"].status == "pending"

        # Fiyat limit fiyatına eşit veya düşükse dolmalı
        engine.monitor_positions({"BTC/USDT": 29900.0})
        assert engine.open_positions["BTC/USDT"].status == "active"
        assert engine.orders[0].status == OrderStatus.FILLED

    def test_monitor_positions_limit_buy_timeout_cancels(self, clean_state_file, risk_engine, buy_signal):
        """Zaman aşımına uğrayan limit alım emrinin iptal edilip bakiyenin iade edilmesini doğrula."""
        cfg = get_settings()
        cfg.trading_mode = "paper"
        cfg.paper_trading.enabled = True
        cfg.execution.order_type = "limit"
        cfg.execution.limit_timeout_minutes = 10

        engine = ExecutionEngine(
            settings=cfg,
            risk_engine=risk_engine,
            state_dir=str(clean_state_file.parent),
            state_file=clean_state_file.name
        )

        assessment = RiskAssessment(
            is_approved=True,
            position_size_usdt=3000.0,
            risk_pct=0.02,
            stop_loss_pct=0.05
        )

        engine.execute_signal(buy_signal, assessment)
        pos = engine.open_positions["BTC/USDT"]
        
        # Süreyi yapay olarak 11 dakika geri çekelim
        from datetime import timedelta
        pos.opened_at = datetime.utcnow() - timedelta(minutes=11)

        # monitor_positions zaman aşımını tetiklemeli ve iptal etmeli
        engine.monitor_positions({"BTC/USDT": 30500.0})

        assert "BTC/USDT" not in engine.open_positions
        assert engine.orders[0].status == OrderStatus.CANCELLED
        # Bakiye iade edilmiş olmalı (10000.0)
        assert abs(engine.usdt_balance - 10000.0) < 0.01

    def test_monitor_positions_fills_limit_buy_in_live(self, clean_state_file, risk_engine, buy_signal):
        """Canlı modda limit emri borsada closed olunca pozisyonun aktifleşmesini ve OCO kurulmasını doğrula."""
        cfg = get_settings()
        cfg.trading_mode = "live"
        cfg.paper_trading.enabled = False
        cfg.execution.order_type = "limit"
        cfg.exchange.default_type = "spot"

        mock_exchange = MagicMock()
        mock_exchange.amount_to_precision.return_value = "0.1"
        mock_exchange.price_to_precision.side_effect = lambda sym, price: str(price)

        mock_exchange.create_order.return_value = {
            "id": "limit_buy_789",
            "status": "open",
            "price": 30000.0,
            "amount": 0.1
        }

        # OCO mock response
        mock_exchange.privatePostOrderOco.return_value = {
            "orderListId": "oco_list_live",
            "orders": [
                {"orderId": "limit_tp", "type": "LIMIT_MAKER"},
                {"orderId": "stop_sl", "type": "STOP_LOSS_LIMIT"}
            ]
        }

        engine = ExecutionEngine(
            settings=cfg,
            risk_engine=risk_engine,
            exchange=mock_exchange,
            state_dir=str(clean_state_file.parent),
            state_file=clean_state_file.name
        )

        assessment = RiskAssessment(
            is_approved=True,
            position_size_usdt=3000.0,
            risk_pct=0.02,
            stop_loss_pct=0.05
        )

        engine.execute_signal(buy_signal, assessment)
        pos = engine.open_positions["BTC/USDT"]
        assert pos.status == "pending"

        # Borsayı sorguladığında open dönsün -> pozisyon beklemede kalmalı
        mock_exchange.fetch_order.return_value = {"status": "open"}
        engine.monitor_positions({})
        assert pos.status == "pending"

        # Borsayı sorguladığında closed dönsün -> pozisyon active olmalı ve OCO kurulmalı
        mock_exchange.fetch_order.return_value = {"status": "closed"}
        engine.monitor_positions({})

        assert pos.status == "active"
        assert pos.oco_order_list_id == "oco_list_live"
        mock_exchange.privatePostOrderOco.assert_called_once()

    def test_futures_isolated_long_pnl_with_leverage(self):
        """LONG yönlü kaldıraçlı futures pozisyonunda PnL ve likidasyon hesaplamalarını doğrula."""
        pos = MarketPosition(
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            entry_price=30000.0,
            amount=0.1,
            cost_usdt=3000.0,
            stop_loss=28500.0,
            take_profit=33000.0,
        )
        
        # 1. PnL hesaplaması
        pos.update_pnl(31000.0)
        # PnL = (31000 - 30000) * 0.1 = 100 USDT
        assert pos.pnl_usdt == 100.0
        assert abs(pos.pnl_pct - (1000.0 / 30000.0)) < 1e-6
        
        # 2. Likidasyon Fiyatı (leverage = 5x)
        # Liq = 30000 * (1 - 1/5) = 24000.0
        liq_price = pos.get_liquidation_price(leverage=5.0)
        assert liq_price == 24000.0
        
        # 3. Trailing Stop Level
        pos.trailing_stop_active = True
        pos.trailing_stop_pct = 0.02
        pos.highest_price = 32000.0
        # new_sl = 32000 * (1 - 0.02) = 31360.0
        # max(31360, 28500) = 31360.0
        assert pos.get_trailing_stop_level() == 31360.0

    def test_futures_isolated_short_pnl_with_leverage(self):
        """SHORT yönlü kaldıraçlı futures pozisyonunda PnL ve likidasyon hesaplamalarını doğrula."""
        pos = MarketPosition(
            symbol="BTC/USDT",
            side=PositionSide.SHORT,
            entry_price=30000.0,
            amount=0.1,
            cost_usdt=3000.0,
            stop_loss=31500.0,
            take_profit=27000.0,
        )
        
        # 1. PnL hesaplaması
        pos.update_pnl(29000.0)
        # PnL = (30000 - 29000) * 0.1 = 100 USDT
        assert pos.pnl_usdt == 100.0
        
        # 2. Likidasyon Fiyatı (leverage = 5x)
        # Liq = 30000 * (1 + 1/5) = 36000.0
        liq_price = pos.get_liquidation_price(leverage=5.0)
        assert liq_price == 36000.0
        
        # 3. Trailing Stop Level
        pos.trailing_stop_active = True
        pos.trailing_stop_pct = 0.02
        pos.highest_price = 28000.0
        # new_sl = 28000 * (1 + 0.02) = 28560.0
        # min(28560, 31500) = 28560.0
        assert pos.get_trailing_stop_level() == 28560.0

    def test_futures_close_position_sends_reduce_only(self, clean_state_file, risk_engine):
        """Futures modunda pozisyon kapatılırken reduceOnly=True parametresi iletilmeli ve koruma emirleri iptal edilmeli."""
        cfg = get_settings()
        cfg.trading_mode = "live"
        cfg.paper_trading.enabled = False
        cfg.exchange.default_type = "future"
        
        mock_exchange = MagicMock()
        mock_exchange.amount_to_precision.return_value = "0.1"
        
        # Setup position
        pos = MarketPosition(
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            entry_price=30000.0,
            amount=0.1,
            cost_usdt=3000.0,
            stop_loss=28500.0,
            take_profit=33000.0,
            oco_limit_order_id="tp_123",
            oco_stop_order_id="sl_456"
        )
        
        engine = ExecutionEngine(
            settings=cfg,
            risk_engine=risk_engine,
            exchange=mock_exchange,
            state_dir=str(clean_state_file.parent),
            state_file=clean_state_file.name
        )
        engine.open_positions["BTC/USDT"] = pos
        
        # Mock ccxt create_order response
        mock_exchange.create_order.return_value = {
            "id": "close_order_999",
            "average": 31000.0,
            "filled": 0.1,
            "fee": {"cost": 3.1}
        }
        
        engine._close_position(pos, 31000.0, "STRATEGY EXIT")
        
        # 1. create_order çağrısını ve reduceOnly parametresini doğrula
        mock_exchange.create_order.assert_called_once_with(
            symbol="BTC/USDT",
            type="market",
            side="sell",
            amount=0.1,
            price=None,
            params={"reduceOnly": True}
        )
        
        # 2. Koruma emirlerinin iptal edildiğini doğrula
        assert mock_exchange.cancel_order.call_count == 2
        mock_exchange.cancel_order.assert_any_call("tp_123", "BTC/USDT")
        mock_exchange.cancel_order.assert_any_call("sl_456", "BTC/USDT")
