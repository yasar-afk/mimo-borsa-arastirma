# Trading Bot Algoritmik Ticaret Botu - Strateji Dokümanı (v2.0 & v2.1)

Bu doküman, Trading Bot Algo Trading Bot'un (v2.0 ve v2.1 sürümleri) işlem açma ve kapama kararlarını alırken kullandığı tüm matematiksel kuralları, indikatör ağırlıklarını, risk yönetimi prensiplerini ve son eklenen **Fibonacci & Formasyon (Pattern)** sistemlerini içermektedir.

---

## 1. Genel Karar Alma Mimarisi

Bot, tamamen **Ağırlıklı Puanlama Modeli (Weighted Scoring Model)** prensibiyle çalışır. Süreç şu şekilde işler:

1. **Veri Toplama (Data Collector):** Binance üzerinden belirlenen zaman dilimlerinde (örneğin 15m, 1h, 4h, 1d) 500 adet mum verisi çekilir.
2. **Teknik Analiz Motoru (Technical Engine):** Çekilen mum verileri kullanılarak matematiksel indikatörler, Fibonacci seviyeleri ve mum/grafik formasyonları hesaplanır.
3. **Puanlama (Scoring):** Aktif olan her teknik gösterge için `0.0` ile `1.0` arasında normalize edilmiş bir puan üretilir. Bu puan, göstergenin `feature_weights.py` içindeki ağırlığı ile çarpılır.
4. **Toplam Ağırlıklı Skor:** Tüm aktif göstergelerden elde edilen puanlar toplanarak normalize edilmiş bir **Toplam Ağırlıklı Skor** elde edilir.
5. **Eşik Kontrolü (Thresholds):**
   - **Giriş Eşiği (`ENTRY_THRESHOLD`):** **0.65**. Toplam skor bu seviyenin üzerindeyse bir pozisyon sinyali üretilir.
   - **Çıkış Eşiği (`EXIT_THRESHOLD`):** **0.40**. Açık olan bir pozisyondaki skor bu değerin altına düşerse pozisyon kapatılır (Trailing Exit).
6. **Süzgeçler (Filters):** Skor eşiği geçilse dahi;
   - *Hacim Filtresi:* Son mumdaki hacim, 20 periyotluk ortalama hacmin en az %80'i olmalıdır.
   - *Risk/Ödül Filtresi:* Pozisyonun potansiyel Risk/Ödül oranı (R/R) en az **2.0** olmalıdır.
7. **AI Doğrulama (AI Verification):** Üretilen sinyal, OpenRouter üzerinden AI (GPT-4o) modeline gönderilerek son risk süzgecinden geçirilir. AI onay vermezse işlem açılmaz.

---

## 2. İndikatör Ağırlıkları ve Kuralları

Göstergeler `src/strategy/feature_weights.py` dosyasında tanımlanmıştır. Aktif kategoriler: **Fiyat Aksiyonu**, **Makro/Korelasyon** ve **Momentum**'dur.

### Kategori 1: Fiyat Aksiyonu ve Hacim (En Yüksek Öncelik)

| Gösterge Adı | Kod Karşılığı | Ağırlık | Çalışma Mantığı / Kurallar |
| :--- | :--- | :---: | :--- |
| **Yatay Destek/Direnç** | `support_resistance` | **0.90** | Swing high/low noktalarına göre hesaplanan güçlü destek/direnç seviyeleri. Fiyat dirence yakınken SATIŞ, desteğe yakınken ALIŞ yönlü çalışır. |
| **İşlem Hacmi (Volume)** | `volume` | **0.85** | Fiyat hareketini onaylar. Fiyat yükselirken hacim 20 periyotluk ortalama hacmin 1.5 katını geçerse güçlü onay verilir. |
| **Trend Yapısı & Kanal** | `trend_structure` | **0.80** | Higher High + Higher Low = Yükseliş; Lower High + Lower Low = Düşüş. Trende ters işlem açılması engellenir. |
| **Fibonacci Seviyeleri** | `fibonacci` | **0.00** | *Doğrudan skora etki etmez.* Ancak Golden Pocket seviyelerine yakınlık durumunda sinyal güvenini artırır ve TP/SL hizalamasında kullanılır. |
| **Mum/Grafik Formasyonları** | `patterns` | **0.00** | *Doğrudan skora etki etmez.* Formasyon tespiti durumunda sinyal güven skorunu artırır (+0.10 ile +0.15 arası). |

### Kategori 2: Korelasyonlar ve Makro Veriler

| Gösterge Adı | Kod Karşılığı | Ağırlık | Çalışma Mantığı / Kurallar |
| :--- | :--- | :---: | :--- |
| **Fonlama Oranı** | `funding_rate` | **0.85** | Binance Vadeli İşlemlerden çekilir. Funding > +0.01% (Aşırı Long/Düşüş Riski), Funding < -0.01% (Aşırı Short/Sıkışma Riski) olarak yorumlanır. |
| **Açık Pozisyonlar (OI)** | `open_interest` | **0.80** | OI artışı + Fiyat artışı = Güçlü trend (Alış onayı). OI düşüşü = Kar alımları ve zayıflayan trend. |
| **ETH/BTC Paritesi** | `eth_btc_ratio` | **0.65** | Altcoin piyasasının ve genel risk iştahının durumunu ölçer. Parite yükseliyorsa risk iştahı yüksektir. |

### Kategori 3: Momentum ve Trend İndikatörleri

| Gösterge Adı | Kod Karşılığı | Ağırlık | Koşullu Ağırlık | Çalışma Mantığı / Kurallar |
| :--- | :--- | :---: | :---: | :--- |
| **RSI (14)** | `rsi` | **0.70** | **0.85** | Normalde <30 aşırı satım (Alış), >70 aşırı alım (Satış). Fiyat ile RSI arasında uyuşmazlık (Divergence) varsa ağırlığı 0.85'e yükselir. |
| **ADX (14)** | `adx` | **0.65** | **0.80** | Trend gücünü ölçer. ADX < 20 ise piyasa yataydır (işleme girilmez). ADX > 40 ise çok güçlü trenddir (ağırlık 0.80 olur). |
| **ATR (14)** | `atr` | **0.65** | - | Volatiliteyi ölçer. Sinyal üretmez, yalnızca Stop-Loss (Giriş - 2.0xATR) ve Take-Profit seviyelerini belirler. |
| **MACD** | `macd` | **0.60** | - | MACD çizgisinin sinyal çizgisini kesmesi (Golden/Death Cross) ve histogramın yönü değerlendirilir. |
| **EMA (20, 50, 200)** | `ema` | **0.55** | - | Fiyatın EMA200 üzerindeki konumu ve EMA50-200 kesişimleri (Golden/Death Cross) ile uzun vadeli trend yönünü onaylar. |
| **Bollinger Bands** | `bollinger_bands` | **0.50** | - | Bant daralması (Squeeze) volatilite patlaması uyarısı verir. Fiyatın alt/üst banda dokunuşları ortalamaya dönüş sinyalidir. |

---

## 3. Yeni Strateji Özellikleri (v2.1 Güncellemesi)

### A. Fibonacci Entegrasyonu
1. **Seviye Hesabı:** Geriye dönük son **500 mum** taranarak en yüksek tepe (Swing High) ve en düşük dip (Swing Low) noktaları belirlenir. Bu iki seviye arasına standart Fibonacci katsayıları uygulanır: **%23.6, %38.2, %50.0, %61.8, %78.6**.
2. **Altın Cephe (Golden Pocket) Güven Artışı:** Sinyal yönü BUY iken fiyatın %50.0, %61.8 veya %78.6 seviyelerine çok yakın olması (%1.5 tolerans ile) durumunda, sinyal güven skoru **+%10** artırılır.
3. **Dinamik TP/SL Hizalaması:** Normal koşullarda ATR bazlı hesaplanan Take-Profit (Kar Al) ve Stop-Loss (Zarar Durdur) seviyeleri, en yakın Fibonacci destek ve direnç seviyelerine doğru çekilerek optimize edilir:
   - Alış işlemlerinde: TP seviyesi en yakın Fibonacci direncinin hemen altına, SL seviyesi en yakın Fibonacci desteğinin hemen altına çekilir.
   - *Güvenlik Limiti:* Eğer bu hizalama sonucunda hedeflenen Risk/Ödül oranı (min R/R) **2.0** altına düşerse, hizalama iptal edilir ve orijinal güvenli ATR seviyeleri kullanılır.

### B. Mum ve Grafik Formasyonları (Patterns)
Teknik analiz motoruna anlık ve geçmiş mum yapılarını inceleyen matematiksel formasyon tarayıcıları entegre edilmiştir.

#### 1. Mum Formasyonları:
- **Çekiç (Hammer) [Boğa]:** Düşen bir trend sonrasında oluşur. Mum gövdesi küçük, alt gölgesi (kuyruğu) gövde boyunun en az 2 katı, üst gölgesi ise yok denecek kadar azdır.
- **Kayan Yıldız (Shooting Star) [Ayı]:** Yükselen bir trend sonrasında oluşur. Mum gövdesi küçük, üst gölgesi gövde boyunun en az 2 katı, alt gölgesi ise yok denecek kadar azdır.
- **Yutan Boğa (Bullish Engulfing) [Boğa]:** Son mum yeşildir ve gövdesi bir önceki kırmızı mumun gövdesini tamamen içine alır (yutar).
- **Yutan Ayı (Bearish Engulfing) [Ayı]:** Son mum kırmızıdır ve gövdesi bir önceki yeşil mumun gövdesini tamamen içine alır.

#### 2. Grafik Formasyonları:
- **İkili Dip (Double Bottom) [Boğa]:** Son 150 mum içerisinde en düşük iki dip (Swing Low) noktası tespit edilir. Bu iki dip seviyesi arasındaki fiyat farkı %1.5'ten az olmalı ve fiyat bu diplerden yukarı doğru sekmiş (ortalama dipten en fazla %4 yukarıda) olmalıdır. Flat (yatay) piyasalardaki hatalı sinyalleri engellemek için dip noktalarının komşu mumlara kıyasla kesinlikle daha düşük olması (Swing Low şartı) zorunludur.
- **İkili Tepe (Double Top) [Ayı]:** Son 150 mum içerisinde en yüksek iki tepe (Swing High) noktası tespit edilir. Bu iki tepe seviyesi arasındaki fiyat farkı %1.5'ten az olmalı ve fiyat tepelerden aşağı yönlü hareket etmeye başlamış olmalıdır.

#### 3. Sinyal Güven Skoru Katkıları:
Formasyonlar algılandığında sinyal skoru doğrudan yükseltilir:
- **İkili Dip / İkili Tepe** tespiti sinyal güvenini **+0.15** artırır.
- **Yutan Boğa / Yutan Ayı** tespiti sinyal güvenini **+0.10** artırır.
- **Çekiç / Kayan Yıldız** tespiti sinyal güvenini **+0.10** artırır.

---

## 4. AI Sinyal Doğrulama (GPT-4o) Prompt Yapısı

Skor eşiğini geçen ve filtrelerden başarıyla sıyrılan tüm sinyaller, OpenRouter aracılığıyla AI analizine tabi tutulur. AI'a gönderilen sistem promptunda şu veriler bulunur:
- **Genel Bilgiler:** Sembol, zaman dilimi, anlık fiyat ve sinyal yönü.
- **Teknik Özet:** RSI bölgesi, ADX trend gücü, EMA dizilimi, MACD durumu ve Bollinger Bandı konumu.
- **Fibonacci Bilgisi (Yeni):** Son 500 mumun zirve ve dip değerleri ile Golden Pocket seviyeleri. Anlık fiyatın bu seviyelere olan yüzde uzaklığı.
- **Aktif Formasyonlar (Yeni):** Grafik ve mum bazında tespit edilen tüm formasyonlar (örn: *Yutan Boğa (Bullish Engulfing)*).
- **Risk Raporu:** Hedef R/R oranı, planlanan TP/SL seviyeleri ve cüzdan marjin yükü.

AI modeli, bu yapısal veriyi kullanarak Türkçe dilinde profesyonel bir risk yöneticisi tonunda analizi gerçekleştirir ve nihai **ONAY (APPROVED)** veya **RED (REJECTED)** kararını verir.

---

## 5. Sürüm Farklılıkları ve Çalıştırma Yöntemleri

### v2.0 Stratejisi (`main.py` & `config.yaml`)
- **İşlem Yönü:** Yalnızca **LONG (Alış)** yönünde işlem açar.
- **Alt Yapı:** Spot veya Vadeli İşlemlerde (Futures) çalışabilir.
- **Hizmet:** Klasik al-tut ve trend takip stratejilerini barındırır.

### v2.1 Stratejisi (`main_v21.py` & `config_v21.yaml`)
- **İşlem Yönü:** Çift Yönlüdür; hem **LONG** hem de **SHORT (Açığa Satış)** işlemleri açabilir.
- **Alt Yapı:** Vadeli İşlemler (Futures) zorunludur.
- **Çalıştırma Komutu:**
  ```powershell
  .\venv\Scripts\python main_v21.py --config config_v21.yaml
  ```

---
*Not: Bu strateji belgesi botun en güncel v2.1 kod yapısıyla %100 uyumludur ve kod içerisindeki tüm matematiksel eşikler bu dokümanda birebir yansıtılmıştır.*
