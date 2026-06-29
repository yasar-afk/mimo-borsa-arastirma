# ============================================================
# tests/test_ai_analyzer.py — Trading Bot Trading Bot Testleri
# ============================================================

from __future__ import annotations

import os
import tempfile
from unittest.mock import patch, MagicMock
import pytest

from src.utils.ai_analyzer import (
    generate_post_mortem_analysis,
    _generate_fallback_analysis,
    verify_signal_with_ai
)
from src.utils.generate_excel import create_analysis_excel
from src.config.settings import get_settings


def test_fallback_analysis_loss():
    """Zarar durumunda fallback analizini doğrular."""
    result_sl = _generate_fallback_analysis(
        pnl_usdt=-50.0,
        exit_price=10.0,
        stop_loss=10.0,
        take_profit=15.0
    )
    assert "ZARARLA KAPANDI" in result_sl
    assert "stop-loss" in result_sl.lower()

    result_manual = _generate_fallback_analysis(
        pnl_usdt=-50.0,
        exit_price=11.0,
        stop_loss=10.0,
        take_profit=15.0
    )
    assert "ZARARLA KAPANDI" in result_manual
    assert "Net Kayıp: $50.00" in result_manual


def test_fallback_analysis_profit():
    """Kâr durumunda fallback analizini doğrular."""
    result_tp = _generate_fallback_analysis(
        pnl_usdt=80.0,
        exit_price=15.0,
        stop_loss=10.0,
        take_profit=15.0
    )
    assert "KÂRLA KAPANDI" in result_tp
    assert "take-profit" in result_tp.lower()

    result_manual = _generate_fallback_analysis(
        pnl_usdt=80.0,
        exit_price=14.0,
        stop_loss=10.0,
        take_profit=15.0
    )
    assert "KÂRLA KAPANDI" in result_manual
    assert "Net Kazanım: $80.00" in result_manual


def test_ai_analyzer_missing_api_key():
    """API anahtarı eksik olduğunda fallback analizine düştüğünü doğrular."""
    with patch("src.utils.ai_analyzer.get_settings") as mock_settings:
        mock_instance = MagicMock()
        mock_instance.gemini_api_key = ""
        mock_instance.openrouter_api_key = ""
        mock_settings.return_value = mock_instance

        analysis = generate_post_mortem_analysis(
            symbol="BTC/USDT",
            side="LONG",
            entry_price=100.0,
            exit_price=90.0,
            stop_loss=90.0,
            take_profit=120.0,
            pnl_usdt=-100.0,
            pnl_pct=-0.10,
            reason="EMA Kırılımı"
        )
        assert "ZARARLA KAPANDI" in analysis
        assert "stop-loss" in analysis.lower()


@patch("urllib.request.urlopen")
def test_ai_analyzer_with_valid_response(mock_urlopen):
    """API geçerli bir yanıt döndüğünde analizin doğru alındığını doğrular."""
    # Mock response format of Gemini API
    mock_response = MagicMock()
    mock_json_response = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "İşlem başarıyla kârla sonuçlandı. EMA 200 seviyesi test edilerek güzel bir sıçrama yakalandı."}
                    ]
                }
            }
        ]
    }
    import json
    mock_response.read.return_value = json.dumps(mock_json_response).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_response

    with patch("src.utils.ai_analyzer.get_settings") as mock_settings:
        mock_instance = MagicMock()
        mock_instance.gemini_api_key = "fake_valid_key"
        mock_instance.openrouter_api_key = ""
        mock_settings.return_value = mock_instance

        analysis = generate_post_mortem_analysis(
            symbol="BTC/USDT",
            side="LONG",
            entry_price=100.0,
            exit_price=110.0,
            stop_loss=90.0,
            take_profit=110.0,
            pnl_usdt=100.0,
            pnl_pct=0.10,
            reason="Destek testi",
            indicator_summary={"RSI": "30"}
        )
        assert "İşlem başarıyla kârla sonuçlandı" in analysis


@patch("urllib.request.urlopen")
def test_ai_analyzer_with_openrouter(mock_urlopen):
    """OpenRouter API geçerli bir yanıt döndüğünde analizin doğru alındığını doğrular."""
    # Mock response format of OpenRouter API
    mock_response = MagicMock()
    mock_json_response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "OpenRouter ile işlem başarıyla analiz edildi."
                }
            }
        ]
    }
    import json
    mock_response.read.return_value = json.dumps(mock_json_response).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_response

    with patch("src.utils.ai_analyzer.get_settings") as mock_settings:
        mock_instance = MagicMock()
        mock_instance.openrouter_api_key = "fake_openrouter_key"
        mock_instance.openrouter_model = "google/gemma-4-31b-it:free"
        mock_instance.gemini_api_key = ""
        mock_settings.return_value = mock_instance

        analysis = generate_post_mortem_analysis(
            symbol="BTC/USDT",
            side="LONG",
            entry_price=100.0,
            exit_price=110.0,
            stop_loss=90.0,
            take_profit=110.0,
            pnl_usdt=100.0,
            pnl_pct=0.10,
            reason="Destek testi",
            indicator_summary={"RSI": "30"}
        )
        assert "OpenRouter ile işlem başarıyla analiz edildi" in analysis


def test_excel_generation_creates_file():
    """Excel oluşturma işleminin hata vermeden dosyayı oluşturduğunu doğrular."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_excel_path = os.path.join(temp_dir, "test_islem_analiz_raporu.xlsx")
        
        # settings mocks to avoid live API key requests
        with patch("src.utils.ai_analyzer.get_settings") as mock_settings:
            mock_instance = MagicMock()
            mock_instance.gemini_api_key = ""
            mock_instance.openrouter_api_key = ""
            mock_settings.return_value = mock_instance
            
            # Excel oluştur
            create_analysis_excel(output_path=temp_excel_path)
            
            # Dosya oluştu mu kontrol et
            assert os.path.exists(temp_excel_path)
            assert os.path.getsize(temp_excel_path) > 0


@patch("urllib.request.urlopen")
def test_verify_signal_with_ai_approved(mock_urlopen):
    """AI sinyal doğrulamasının onaylandığı durumu test eder."""
    mock_response = MagicMock()
    mock_json_response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": '{\n  "approved": true,\n  "reason": "Teknik göstergeler alım için uygun."\n}'
                }
            }
        ]
    }
    import json
    mock_response.read.return_value = json.dumps(mock_json_response).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_response

    with patch("src.utils.ai_analyzer.get_settings") as mock_settings:
        mock_instance = MagicMock()
        mock_instance.openrouter_api_key = "fake_key"
        mock_instance.openrouter_model = "google/gemma-4-31b-it:free"
        mock_instance.gemini_api_key = ""
        mock_settings.return_value = mock_instance

        approved, reason = verify_signal_with_ai(
            symbol="BTC/USDT",
            signal_type="BUY",
            entry_price=60000.0,
            stop_loss=59000.0,
            take_profit=62000.0,
            indicator_summary={"RSI": "32"},
            reasons=["RSI oversold"]
        )
        assert approved is True
        assert "Teknik göstergeler" in reason


@patch("urllib.request.urlopen")
def test_verify_signal_with_ai_rejected(mock_urlopen):
    """AI sinyal doğrulamasının reddedildiği durumu test eder."""
    mock_response = MagicMock()
    mock_json_response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": '{\n  "approved": false,\n  "reason": "Piyasa aşırı volatil ve hacim çok düşük."\n}'
                }
            }
        ]
    }
    import json
    mock_response.read.return_value = json.dumps(mock_json_response).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_response

    with patch("src.utils.ai_analyzer.get_settings") as mock_settings:
        mock_instance = MagicMock()
        mock_instance.openrouter_api_key = "fake_key"
        mock_instance.openrouter_model = "google/gemma-4-31b-it:free"
        mock_instance.gemini_api_key = ""
        mock_settings.return_value = mock_instance

        approved, reason = verify_signal_with_ai(
            symbol="BTC/USDT",
            signal_type="BUY",
            entry_price=60000.0,
            stop_loss=59000.0,
            take_profit=62000.0,
            indicator_summary={"RSI": "32"},
            reasons=["RSI oversold"]
        )
        assert approved is False
        assert "volatil" in reason
