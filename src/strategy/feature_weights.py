# ============================================================
# src/strategy/feature_weights.py — Trading Bot Trading Bot
#
# AMAÇ:
#   Bu dosya, botun bir pozisyona girmeden önce değerlendirdiği
#   tüm veri kaynaklarının (features) ve ağırlıklarının (weights)
#   tek yetkili kaynağıdır (Single Source of Truth).
#
# NASIL ÇALIŞIR:
#   Bot her potansiyel sinyal için tüm aktif metrikleri hesaplar,
#   her metriğin değerini 0.0–1.0 arasında normalize eder,
#   feature_weight ile çarpar ve toplar → Weighted Score üretir.
#   Sadece toplam skor ENTRY_THRESHOLD üzerindeyse pozisyon açılır.
#
# YENİ KURAL EKLEMEK:
#   1. Uygun kategoriye yeni bir FeatureConfig satırı ekle.
#   2. enabled=True yap.
#   3. TechnicalEngine veya DataCollector'a o metriği hesaplayan
#      metodu ekle (Faz 1b / 1c'de yapılacak).
#   4. Buraya not olarak tarihi ve mantığı yaz.
#
# DEĞİŞİKLİK GEÇMİŞİ:
#   2026-06-04 | v1.0 | İlk kural seti tanımlandı (kullanıcı input)
# ============================================================

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


# ─── Enumerasyonlar ───────────────────────────────────────────

class Category(str, Enum):
    """Metrik kategorisi — öncelik sıralaması için kullanılır."""
    PRICE_ACTION = "Fiyat Aksiyonu ve Hacim"       # En yüksek öncelik
    MACRO        = "Korelasyonlar ve Makro Veriler"
    MOMENTUM     = "Momentum ve Trend İndikatörleri"
    ONCHAIN      = "Zincir Üstü Veriler"            # Gelecek kural seti
    SENTIMENT    = "Duygu Analizi"                  # Faz 3 — şimdilik devre dışı


class DataSource(str, Enum):
    """Bu metriğin verisi nereden geliyor?"""
    CCXT_OHLCV   = "CCXT / Binance OHLCV"
    CCXT_FUTURES = "CCXT / Binance Futures"
    CALCULATED   = "Hesaplanmış (OHLCV'den türetilmiş)"
    EXTERNAL_API = "Harici API (Manuel / Faz 3)"
    NOT_IMPL     = "Henüz Implemente Edilmedi"


# ─── Metrik Tanım Nesnesi ─────────────────────────────────────

@dataclass(frozen=True)
class FeatureConfig:
    """Tek bir metriğin tüm özelliklerini tanımlar.

    Attributes:
        name: Metrik adı (kod içinde key olarak kullanılır).
        label: İnsan-okunur Türkçe etiketi.
        category: Hangi kategoriye ait.
        weight: Normal koşullarda ağırlık (0.0 – 1.0).
        conditional_weight: Özel koşullarda geçerli ağırlık (ör. divergence).
        conditional_note: Koşullu ağırlığın tetiklenme açıklaması.
        data_source: Verinin nereden geldiği.
        enabled: False ise sinyal hesaplamaya dahil edilmez.
        faz: Hangi geliştirme fazında aktifleşecek.
        notes: Geliştirici notu ve mantık açıklaması.
    """
    name: str
    label: str
    category: Category
    weight: float                          # 0.0 – 1.0
    data_source: DataSource
    enabled: bool = True
    faz: str = "1b"
    conditional_weight: Optional[float] = None
    conditional_note: Optional[str] = None
    notes: str = ""


# ─────────────────────────────────────────────────────────────
#  KATEGORİ 1: FİYAT AKSİYONU VE HACİM
#  Piyasanın gerçek zamanlı ayak izi. En yüksek öncelik.
# ─────────────────────────────────────────────────────────────

PRICE_ACTION_FEATURES: List[FeatureConfig] = [

    FeatureConfig(
        name="support_resistance",
        label="Yatay Destek ve Direnç Seviyeleri",
        category=Category.PRICE_ACTION,
        weight=0.90,
        data_source=DataSource.CALCULATED,
        faz="1c",
        notes=(
            "Fiyatın geçmişte güçlü tepki verdiği ana likidite bölgeleri. "
            "Swing high/low noktaları baz alınarak hesaplanır. "
            "Fiyat bir direnç altındaysa SATIŞ ağırlığı, destek üstündeyse "
            "ALIŞ ağırlığı bu faktörden beslenir. "
            "Minimum 3 dokunuş = güvenilir seviye kuralı uygulanır."
        ),
    ),

    FeatureConfig(
        name="volume",
        label="İşlem Hacmi (Volume)",
        category=Category.PRICE_ACTION,
        weight=0.85,
        data_source=DataSource.CCXT_OHLCV,
        faz="1b",
        notes=(
            "Fiyat hareketinin gücünü ve gerçekliğini onaylar. "
            "KURAL: Fiyat yükselirken hacim de artmalı (onay). "
            "Fiyat yükselirken hacim düşüyorsa → Sahte kırılım uyarısı. "
            "20 periyotluk ortalama hacim baz alınır. "
            "Anlık hacim / Ort. hacim > 1.5 → güçlü onay sinyali."
        ),
    ),

    FeatureConfig(
        name="trend_structure",
        label="Trend Çizgileri ve Kanal Yapıları",
        category=Category.PRICE_ACTION,
        weight=0.80,
        data_source=DataSource.CALCULATED,
        faz="1c",
        notes=(
            "Yükselen/Düşen trendin ana yönünü belirler. "
            "Higher High + Higher Low = Yükseliş trendi. "
            "Lower High + Lower Low = Düşüş trendi. "
            "Trende karşı pozisyon açmak yasak (bu katsayı negatif çarpan olur). "
            "Çoklu timeframe uyumu (4h + 1d aynı yön) → katsayı 0.80 → 0.90."
        ),
    ),
    FeatureConfig(
        name="fibonacci",
        label="Fibonacci Düzeltme Seviyeleri (Retracement)",
        category=Category.PRICE_ACTION,
        weight=0.0,
        data_source=DataSource.CALCULATED,
        faz="2.1",
        notes=(
            "Son 500 mumun Swing High/Low tepe ve dip seviyelerine göre hesaplanır. "
            "Skor hesaplamasına doğrudan ağırlık katmaz (weight=0.0), ancak "
            "destek/direnç olarak TP/SL hizalamasında ve AI onay promptlarında "
            "aktif olarak kullanılır. Fiyatın Golden Pocket seviyelerine (%50, %61.8, %78.6) "
            "yakınlığı sinyal güvenini (+%10) doğrudan etkiler."
        ),
    ),
    FeatureConfig(
        name="patterns",
        label="Mum ve Grafik Formasyonları (Patterns)",
        category=Category.PRICE_ACTION,
        weight=0.0,
        data_source=DataSource.CALCULATED,
        faz="2.1",
        notes=(
            "Hem 1-3 mumluk dönüş formasyonlarını (Çekiç, Kayan Yıldız, Yutan Boğa/Ayı) "
            "hem de geometrik grafik yapılarını (İkili Dip, İkili Tepe) tespit eder. "
            "Ağırlıklı skora doğrudan katılmaz (weight=0.0), fakat formasyon onayları "
            "durumunda sinyal güvenini yükseltir ve AI değerlendirme promptuna "
            "yapısal bilgi olarak aktarılır."
        ),
    ),
]


# ─────────────────────────────────────────────────────────────
#  KATEGORİ 2: KORELASYONLAR VE MAKRO VERİLER
#  BTC hiçbir zaman tek başına hareket etmez.
# ─────────────────────────────────────────────────────────────

MACRO_FEATURES: List[FeatureConfig] = [

    FeatureConfig(
        name="funding_rate",
        label="Fonlama Oranı (Funding Rate)",
        category=Category.MACRO,
        weight=0.85,
        data_source=DataSource.CCXT_FUTURES,
        faz="2a",
        notes=(
            "Vadeli işlemlerde long/short baskısını gösterir. "
            "Kripto için en hayati verilerden biri. "
            "KURAL: Funding Rate > +0.01% → Aşırı long, düzeltme riski yüksek. "
            "Funding Rate < -0.01% → Aşırı short, sıkışma (squeeze) riski. "
            "Negatif funding + fiyat düşüşü = shortların yorulması sinyali. "
            "8 saatte bir Binance Futures API'den çekilir."
        ),
    ),

    FeatureConfig(
        name="open_interest",
        label="Açık Pozisyonlar (Open Interest)",
        category=Category.MACRO,
        weight=0.80,
        data_source=DataSource.CCXT_FUTURES,
        faz="2a",
        notes=(
            "Piyasaya giren yeni para miktarını gösterir. "
            "KURAL: OI artıyor + fiyat yükseliyor → Güçlü trend (ALIŞ onayı). "
            "OI artıyor + fiyat düşüyor → Kısa baskısı artıyor (DİKKAT). "
            "OI düşüyor + fiyat hareket ediyor → Pozisyon kapanması (güvenilmez sinyal). "
            "Binance /fapi/v1/openInterest endpoint'inden alınır."
        ),
    ),

    FeatureConfig(
        name="dxy_correlation",
        label="DXY (Dolar Endeksi) Korelasyonu",
        category=Category.MACRO,
        weight=0.75,
        data_source=DataSource.EXTERNAL_API,
        enabled=False,               # Faz 3'te etkinleştirilecek
        faz="3d",
        notes=(
            "Dolar endeksi BTC ile ters korelasyon içindedir. "
            "DXY yükseliyor → Dolar güçlenıyor → BTC baskı altında. "
            "DXY düşüyor → Risk iştahı artıyor → BTC için pozitif. "
            "Şu an devre dışı: Harici API (Alpha Vantage / Yahoo Finance) gerektirir. "
            "Faz 3'te otomatik veri çekimi eklenecek."
        ),
    ),

    FeatureConfig(
        name="btc_dominance",
        label="BTC Dominance (BTC.D)",
        category=Category.MACRO,
        weight=0.70,
        data_source=DataSource.EXTERNAL_API,
        enabled=False,               # Faz 3'te etkinleştirilecek
        faz="3d",
        notes=(
            "Paranın BTC'de mi yoksa Altcoin'lerde mi olduğunu belirler. "
            "BTC.D artıyor → Para BTC'ye akıyor (altcoinler düşer). "
            "BTC.D düşüyor → Risk iştahı yüksek, altcoin sezonu. "
            "BTC/USDT için: Yüksek dominance = daha güvenilir trend. "
            "CoinMarketCap API'den alınır — şimdilik manuel input."
        ),
    ),

    FeatureConfig(
        name="eth_btc_ratio",
        label="ETH/BTC Paritesi",
        category=Category.MACRO,
        weight=0.65,
        data_source=DataSource.CCXT_OHLCV,
        faz="2c",
        notes=(
            "Altcoin piyasasının genel sağlığı ve risk iştahı öncüsü. "
            "ETH/BTC yükseliyor → Risk iştahı yüksek, piyasa sağlıklı. "
            "ETH/BTC düşüyor → BTC'ye sığınma başlıyor, dikkatli ol. "
            "CCXT ile doğrudan çekilebilir: fetch_ohlcv('ETH/BTC', '4h')."
        ),
    ),

    FeatureConfig(
        name="sp500_correlation",
        label="S&P 500 / NASDAQ Korelasyonu",
        category=Category.MACRO,
        weight=0.60,
        data_source=DataSource.EXTERNAL_API,
        enabled=False,               # Faz 3'te etkinleştirilecek
        faz="3d",
        notes=(
            "Geleneksel borsalarla pozitif korelasyon durumu. "
            "S&P 500 düşüyorsa BTC de genellikle düşer (risk-off ortam). "
            "Korelasyon dinamik: Kriz dönemlerinde 0.8'e çıkar, "
            "boğa sezonunda 0.3'e düşebilir. "
            "Rolling 30 günlük korelasyon katsayısı hesaplanacak."
        ),
    ),

]


# ─────────────────────────────────────────────────────────────
#  KATEGORİ 3: MOMENTUM VE TREND İNDİKATÖRLERİ
#  Gecikmeli ama teyit edici matematiksel formüller.
# ─────────────────────────────────────────────────────────────

MOMENTUM_FEATURES: List[FeatureConfig] = [

    FeatureConfig(
        name="rsi",
        label="RSI (Relative Strength Index)",
        category=Category.MOMENTUM,
        weight=0.70,
        conditional_weight=0.85,
        conditional_note=(
            "Divergence tespit edildiğinde (fiyat yeni dip/zirve yaparken "
            "RSI yapmıyorsa) katsayı 0.85'e çıkar — en güçlü RSI sinyalidir."
        ),
        data_source=DataSource.CALCULATED,
        faz="1b",
        notes=(
            "Periyot: 14 (standart). Aşırı Alım: >70, Aşırı Satım: <30. "
            "KURAL 1 (Normal): RSI 30 altı → Potansiyel ALIŞ bölgesi. "
            "KURAL 2 (Normal): RSI 70 üstü → Potansiyel SATIŞ bölgesi. "
            "KURAL 3 (Güçlü): Bullish Divergence (fiyat düşüyor, RSI yükseliyor) "
            "→ Katsayı 0.85'e çıkar, güçlü dip sinyali. "
            "KURAL 4 (Güçlü): Bearish Divergence (fiyat yükseliyor, RSI düşüyor) "
            "→ Katsayı 0.85'e çıkar, güçlü zirve sinyali."
        ),
    ),

    FeatureConfig(
        name="atr",
        label="ATR (Average True Range)",
        category=Category.MOMENTUM,
        weight=0.65,
        data_source=DataSource.CALCULATED,
        faz="1b",
        notes=(
            "Periyot: 14. Sinyal üretmez; yalnızca volatilite ölçer. "
            "KULLANIM: Stop-Loss = Giriş Fiyatı - (ATR × 2.0) [config'de ayarlanır]. "
            "ATR yüksekse → Piyasa oynak, stop daha geniş tutulur. "
            "ATR düşükse → Piyasa sıkışık, büyük hareket gelebilir (BB squeeze ile birleşir). "
            "Risk/Ödül hesabında da kullanılır: Hedef = ATR × 4.0 (min 1:2 oranı için)."
        ),
    ),

    FeatureConfig(
        name="macd",
        label="MACD (Moving Average Convergence Divergence)",
        category=Category.MOMENTUM,
        weight=0.60,
        data_source=DataSource.CALCULATED,
        faz="1b",
        notes=(
            "Parametreler: Fast=12, Slow=26, Signal=9 (standart). "
            "KURAL 1: MACD çizgisi sinyal çizgisini yukarı keserse → Bullish (ALIŞ teyidi). "
            "KURAL 2: MACD çizgisi sinyal çizgisini aşağı keserse → Bearish (SATIŞ teyidi). "
            "KURAL 3: Histogram sıfır çizgisini geçerse momentum değişimi. "
            "DİKKAT: Tek başına zayıf sinyal; RSI ve hacimle birlikte kullanılmalı. "
            "Trend olmayan (ranging) piyasada çok fazla yanlış sinyal üretir."
        ),
    ),

    FeatureConfig(
        name="ema",
        label="EMA (Üstel Hareketli Ortalamalar: 20, 50, 200)",
        category=Category.MOMENTUM,
        weight=0.55,
        data_source=DataSource.CALCULATED,
        faz="1b",
        notes=(
            "Üç EMA birlikte kullanılır: EMA20 (kısa), EMA50 (orta), EMA200 (uzun). "
            "KURAL 1 (Golden Cross): EMA50, EMA200'ü yukarı keser → Güçlü boğa sinyali. "
            "KURAL 2 (Death Cross): EMA50, EMA200'ü aşağı keser → Güçlü ayı sinyali. "
            "KURAL 3: Fiyat > EMA200 → Uzun vadeli trend yukarı (ALIŞ lehine +puan). "
            "KURAL 4: EMA20 dinamik destek/direnç olarak kullanılır. "
            "Sıralama: EMA20 > EMA50 > EMA200 → Tam boğa dizilimi."
        ),
    ),

    FeatureConfig(
        name="bollinger_bands",
        label="Bollinger Bantları (BB)",
        category=Category.MOMENTUM,
        weight=0.50,
        data_source=DataSource.CALCULATED,
        faz="1b",
        notes=(
            "Parametreler: Periyot=20, Standart Sapma=2.0. "
            "KURAL 1 (Squeeze): Bantlar daralıyor → Sert hareket geliyor (yön belirsiz). "
            "KURAL 2: Fiyat alt banda dokunuyor + hacim düşük → Potansiyel dip. "
            "KURAL 3: Fiyat üst banda dokunuyor + hacim yüksek → Trend devam edebilir. "
            "KURAL 4: Fiyat bandın DIŞINA çıkarsa → Aşırılık uyarısı (ortalamaya dönüş). "
            "Bant genişliği = (Üst - Alt) / Orta. %B göstergesi ile normalize edilir."
        ),
    ),

    FeatureConfig(
        name="adx",
        label="ADX (Average Directional Index)",
        category=Category.MOMENTUM,
        weight=0.65,
        conditional_weight=0.80,
        conditional_note="ADX > 40 olduğunda trendin gücü arttığı için katsayı 0.80'e çıkar.",
        data_source=DataSource.CALCULATED,
        faz="1b",
        notes="ADX < 20 ise piyasa yönsüzdür ve işlem açılmaz. ADX > 40 ise çok güçlü trenddir.",
    ),

]


# ─────────────────────────────────────────────────────────────
#  KATEGORİ 4: ZİNCİR ÜSTÜ VERİLER (ONCHAIN)
#  Faz 3'te eklenecek kural seti — şimdi placeholder.
# ─────────────────────────────────────────────────────────────

ONCHAIN_FEATURES: List[FeatureConfig] = [

    FeatureConfig(
        name="exchange_netflow",
        label="Borsa Net Akışı (Exchange Netflow)",
        category=Category.ONCHAIN,
        weight=0.75,
        data_source=DataSource.NOT_IMPL,
        enabled=False,
        faz="3d",
        notes=(
            "Borsalara giren/çıkan BTC miktarı. "
            "Net çıkış (withdrawal) → Uzun vadeli tutma, boğa sinyali. "
            "Net giriş (deposit) → Satış baskısı hazırlığı, dikkat. "
            "Glassnode veya CryptoQuant API ile alınır."
        ),
    ),

    FeatureConfig(
        name="whale_transactions",
        label="Balina İşlemleri (Whale Transactions > 1M USD)",
        category=Category.ONCHAIN,
        weight=0.70,
        data_source=DataSource.NOT_IMPL,
        enabled=False,
        faz="3d",
        notes=(
            "1M USD üzeri transfer sayısı. "
            "Büyük transferler piyasa yönünü önceden gösterebilir. "
            "Whale Alert API ile takip edilir."
        ),
    ),

]


# ─────────────────────────────────────────────────────────────
#  SİSTEM KONFİGÜRASYONU: AĞIRLIKLI PUANLAMA MODELİ
# ─────────────────────────────────────────────────────────────

class DynamicScoringConfig(dict):
    def get(self, key, default=None):
        from src.config.settings import get_settings
        try:
            settings = get_settings()
            if key == "MAX_CONCURRENT_POSITIONS":
                return settings.strategy.max_concurrent_positions
            elif key == "ENTRY_THRESHOLD":
                return settings.strategy.entry_threshold
            elif key == "EXIT_THRESHOLD":
                return settings.strategy.exit_threshold
        except Exception:
            pass
        return super().get(key, default)

    def __getitem__(self, key):
        from src.config.settings import get_settings
        try:
            settings = get_settings()
            if key == "MAX_CONCURRENT_POSITIONS":
                return settings.strategy.max_concurrent_positions
            elif key == "ENTRY_THRESHOLD":
                return settings.strategy.entry_threshold
            elif key == "EXIT_THRESHOLD":
                return settings.strategy.exit_threshold
        except Exception:
            pass
        return super().__getitem__(key)


SCORING_CONFIG = DynamicScoringConfig({

    # Pozisyon açmak için gereken minimum toplam ağırlıklı skor
    # 0.0 → 1.0 arasında. 0.65 = toplam puanın %65'i karşılanmalı.
    "ENTRY_THRESHOLD": 0.65,

    # Yalnızca bu kategoriler puanlamaya dahil edilir
    # (enabled=True olan metrikler)
    "ACTIVE_CATEGORIES": [
        Category.PRICE_ACTION,
        Category.MACRO,
        Category.MOMENTUM,
    ],

    # Bu puanın altına düşerse açık pozisyon kapatılır (trailing exit)
    "EXIT_THRESHOLD": 0.40,

    # Maksimum aktif pozisyon sayısı (aynı anda)
    "MAX_CONCURRENT_POSITIONS": 1,   # Başlangıçta muhafazakâr: tek pozisyon

    # Puanlama sırasında ağırlığın %X'i sinyal gücü (0.0-1.0) ile çarpılır
    # Kalan %X sabit ağırlık olarak sayılır
    # 1.0 = tamamen dinamik, 0.0 = sadece enabled/disabled binary
    "SIGNAL_MULTIPLIER_RATIO": 1.0,
})


# ─────────────────────────────────────────────────────────────
#  TÜM METRİKLERİN TOPLU ERİŞİMİ
# ─────────────────────────────────────────────────────────────

ALL_FEATURES: List[FeatureConfig] = (
    PRICE_ACTION_FEATURES
    + MACRO_FEATURES
    + MOMENTUM_FEATURES
    + ONCHAIN_FEATURES
)

def get_active_features() -> List[FeatureConfig]:
    """Aktif strateji versiyonuna göre feature listesini döner."""
    from src.config.settings import get_settings
    try:
        version = get_settings().strategy.version
    except Exception:
        version = "v2"

    active = []
    for f in ALL_FEATURES:
        if not f.enabled:
            continue
        if version == "v1" and f.name == "adx":
            continue
        active.append(f)
    return active


# Yalnızca aktif (enabled=True) metrikler
ACTIVE_FEATURES: List[FeatureConfig] = [
    f for f in ALL_FEATURES if f.enabled
]

# İsme göre hızlı erişim sözlüğü
FEATURE_MAP: Dict[str, FeatureConfig] = {
    f.name: f for f in ALL_FEATURES
}


# ─────────────────────────────────────────────────────────────
#  YARDIMCI FONKSİYONLAR
# ─────────────────────────────────────────────────────────────

def get_feature(name: str) -> Optional[FeatureConfig]:
    """İsme göre metrik tanımını döner."""
    return FEATURE_MAP.get(name)


def get_effective_weight(name: str, condition_met: bool = False) -> float:
    """Bir metriğin efektif ağırlığını döner."""
    from src.config.settings import get_settings
    try:
        version = get_settings().strategy.version
    except Exception:
        version = "v2"

    if version == "v1" and name == "adx":
        return 0.0

    feature = get_feature(name)
    if feature is None or not feature.enabled:
        return 0.0
    if condition_met and feature.conditional_weight is not None:
        return feature.conditional_weight
    return feature.weight


def get_max_possible_score() -> float:
    """Teorik maksimum ağırlıklı puanı hesaplar."""
    total = 0.0
    for f in get_active_features():
        max_w = max(
            f.weight,
            f.conditional_weight if f.conditional_weight else 0.0
        )
        total += max_w
    return total


def print_feature_summary() -> None:
    """Tüm metriklerin özetini konsola basar (debug için)."""
    print("\n" + "=" * 70)
    print("Trading Bot -- Agirlikli Puanlama Modeli: Metrik Listesi")
    print("=" * 70)

    for cat in Category:
        cat_features = [f for f in get_active_features() if f.category == cat]
        if not cat_features:
            continue

        print(f"\n[KATEGORI] {cat.value}")
        print("-" * 60)

        for f in cat_features:
            status = "[AKTIF]" if f.enabled else f"[FAZ {f.faz}]"
            cond = f" [Kosullu: {f.conditional_weight}]" if f.conditional_weight else ""
            print(
                f"  {status:<12} | {f.label:<42} | "
                f"Agirlik: {f.weight:.2f}{cond}"
            )

    print(f"\n{'─' * 70}")
    print(f"  Aktif Metrik Sayisi  : {len(get_active_features())}")
    print(f"  Toplam Metrik Sayisi : {len(ALL_FEATURES)}")
    print(f"  Maks. Teorik Puan   : {get_max_possible_score():.2f}")
    print(f"  Giris Esigi         : {SCORING_CONFIG['ENTRY_THRESHOLD']}")
    print(f"  Cikis Esigi         : {SCORING_CONFIG['EXIT_THRESHOLD']}")
    print("=" * 70 + "\n")


# ─────────────────────────────────────────────────────────────
#  HIZLI TEST (doğrudan çalıştırıldığında)
#  python src/strategy/feature_weights.py
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print_feature_summary()

    # Efektif ağırlık örneği
    print("RSI normal ağırlık    :", get_effective_weight("rsi"))
    print("RSI divergence ağırlık:", get_effective_weight("rsi", condition_met=True))
