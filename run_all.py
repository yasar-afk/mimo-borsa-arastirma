# ============================================================
# run_all.py — Trading Bot Multi-Version Launcher
#
# AMAÇ:
#   V2.1, V3 ve V4 stratejilerini aynı anda background process
#   olarak başlatır. Her versiyon kendi log dizine yazar.
#
# KULLANIM:
#   python run_all.py             # 3 versiyonu başlat
#   python run_all.py --top-50    # Her versiyona top-50 geçir
#   python run_all.py --single-run  # Tek seferlik tarama (test)
#
# DURDURMAK İÇİN:
#   Ctrl+C — tüm alt süreçler temizce kapatılır.
# ============================================================

from __future__ import annotations

import argparse
import subprocess
import sys
import os
import re
import time
from pathlib import Path

# Windows stdout encoding fix
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).parent

# Her versiyon için: (etiket, main script, extra_args, log_dir)
VERSIONS = [
    {
        "label":    "V2.1",
        "script":   "main_v21.py",
        "extra":    [],
        "log_dir":  "logs_v21",
    },
    {
        "label":    "V3",
        "script":   "main_v3.py",
        "extra":    [],
        "log_dir":  "logs_v3",
    },
    {
        "label":    "V4",
        "script":   "main_v4.py",
        "extra":    [],
        "log_dir":  "logs_v4",
    },
    {
        "label":    "V5",
        "script":   "main_v5.py",
        "extra":    [],
        "log_dir":  "logs_v5",
    },
]


def get_last_coin_from_log(log_path: str) -> str:
    """Belirtilen log dosyasinin son kisimlarini okuyup taranan son sembolu dondurur."""
    if not os.path.exists(log_path):
        return "Hazirlaniyor..."
    try:
        with open(log_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            filesize = f.tell()
            offset = min(4096, filesize)
            if offset == 0:
                return "Beklemede..."
            f.seek(-offset, os.SEEK_END)
            lines = f.readlines()
            
        for line in reversed(lines):
            try:
                decoded = line.decode("utf-8", errors="ignore")
                # Hem Türkçe hem İngilizce karakterlerle Zamanlayıcı Durumu ve Portföy Durum Raporu'nu kontrol et
                if (any(x in decoded for x in ["Zamanlayıcı", "Zamanlayici"]) and "Durumu" in decoded) or \
                   (any(x in decoded for x in ["PORTFÖY", "PORTFOY"]) and "DURUM RAPORU" in decoded):
                    return "Beklemede..."
                match = re.search(r"\[([A-Z0-9]+/[A-Z0-9]+(?:@[a-z0-9]+)?)\]", decoded)
                if match:
                    return match.group(1)
            except Exception:
                continue
        return "Hazirlik..."
    except Exception:
        return "Okunuyor..."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Trading Bot Multi-Version Launcher — V2.1 + V3 + V4 aynı anda"
    )
    parser.add_argument(
        "--top-50", action="store_true",
        help="Her versiyona --top-50 argümanı geçirir"
    )
    parser.add_argument(
        "--top-100", action="store_true",
        help="Her versiyona --top-100 argümanı geçirir"
    )
    parser.add_argument(
        "--top", type=int, default=None,
        help="Her versiyona --top N argümanı geçirir"
    )
    parser.add_argument(
        "--single-run", action="store_true",
        help="Her versiyona --single-run argümanı geçirir (test modu)"
    )
    return parser.parse_args()


def build_command(ver: dict, args: argparse.Namespace) -> list[str]:
    """Versiyon için subprocess komutunu oluşturur."""
    python = str(PROJECT_ROOT / "venv" / "Scripts" / "python.exe")
    if not Path(python).exists():
        python = sys.executable  # Fallback: mevcut python

    cmd = [python, str(PROJECT_ROOT / ver["script"])]

    # Versiyon özel argümanlar
    cmd.extend(ver.get("extra", []))

    if args.top_50:
        cmd.append("--top-50")
    if args.top_100:
        cmd.append("--top-100")
    if args.top is not None:
        cmd.extend(["--top", str(args.top)])
    if args.single_run:
        cmd.append("--single-run")

    return cmd


def main() -> None:
    args = parse_args()

    print("=" * 65)
    print("[*] Trading Bot MULTI-VERSION LAUNCHER")
    print("=" * 65)
    print("  V2.1 -> main_v21.py       (Long + SHORT strateji)")
    print("  V3   -> main_v3.py        (Price Action / SMC strateji)")
    print("  V4   -> main_v4.py        (Price Action / SMC V4 - Optimize)")
    print("  V5   -> main_v5.py        (Price Action / SMC V5 - Ultimate)")
    print("=" * 65)
    print("  [!] Durdurmak icin Ctrl+C kullanin")
    print()

    processes = []
    try:
        for ver in VERSIONS:
            # Log dizinini oluştur
            log_dir = PROJECT_ROOT / ver["log_dir"]
            log_dir.mkdir(parents=True, exist_ok=True)

            cmd = build_command(ver, args)

            log_file = log_dir / "run_all_output.log"

            print(f"[>] Baslatiliyor {ver['label']:5s}: {' '.join(cmd[-2:])}")
            print(f"    Log: {log_file}")

            with open(log_file, "w", encoding="utf-8") as log_f:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(PROJECT_ROOT),
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                )

            processes.append((ver["label"], proc, str(log_file)))
            time.sleep(2)  # Baslatmalar arasi kisa bekleme


        print()
        print("[OK] Tum versiyonlar arka planda baslatildi!")
        print("[!] UYARI: Lutfen bu terminal ekranini kapatmayin! Kapatirsaniz botlar duracaktir.")
        print("[>] Canli portfolyo durumunu izlemek icin YENI bir terminal acip sunu calistirin:")
        print("    python watch.py")
        print()
        print("[*] Surecler izleniyor... (Canli coin tarama durumu asagida gorulecektir)")
        print()

        # Surecleri izle
        while True:
            time.sleep(3)   # 3 saniyede bir kontrol et
            alive = []
            status_lines = []
            for label, proc, log_path in processes:
                ret = proc.poll()
                if ret is None:
                    alive.append(label)
                    coin = get_last_coin_from_log(log_path)
                    # En fazla 10 karakter goster (ornek: BTC/USDT) sigmasi icin
                    clean_coin = coin.replace("Tarama Basliyor...", "Basliyor..").replace("Hazirlaniyor...", "Hazirlik..")
                    status_lines.append(f"{label}: {clean_coin[:12]}")
                else:
                    status_lines.append(f"{label}: DURDU")

            if not alive:
                print(f"\n[-] Tum surecler durdu.")
                break

            status_text = " | ".join(status_lines)
            # Terminal satirini ustune yaz (sigmamasi durumunda scroll olmamasi icin kisa tuttuk)
            print(f"\r\033[K[{time.strftime('%H:%M:%S')}] {status_text}", end="", flush=True)

    except KeyboardInterrupt:
        print("\n\n[STOP] Ctrl+C algilandi -- tum versiyonlar kapatiliyor...")
    finally:
        for label, proc, _ in processes:
            if proc.poll() is None:
                proc.terminate()
                print(f"   [OK] {label} durduruldu")
        print("[OK] Tum surecler temizlendi.")


if __name__ == "__main__":
    main()
