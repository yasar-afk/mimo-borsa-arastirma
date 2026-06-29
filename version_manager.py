# -*- coding: utf-8 -*-
"""
version_manager.py — V7 Versiyon Yönetim Sistemi
Her parametre değişikliğinde versiyon artar.
Geçmiş versiyonlara geri dönebilirsin.
"""
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

VERSION_DIR = "versions"
CURRENT_VERSION_FILE = "logs/current_version.json"


class VersionManager:
    """V7 versiyonlarını yönetir."""

    def __init__(self):
        Path(VERSION_DIR).mkdir(exist_ok=True)
        Path("logs").mkdir(exist_ok=True)
        self.current = self._load_current()

    def _load_current(self) -> dict:
        try:
            if Path(CURRENT_VERSION_FILE).exists():
                with open(CURRENT_VERSION_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {"version": "v7.000", "params": {}, "created_at": datetime.now().isoformat()}

    def _save_current(self) -> None:
        with open(CURRENT_VERSION_FILE, "w", encoding="utf-8") as f:
            json.dump(self.current, f, indent=2, ensure_ascii=False)

    def save_snapshot(self, version: str, params: dict, changes: list) -> str:
        """Mevcut durumunun anlık kaydını al."""
        snapshot = {
            "version": version,
            "params": params,
            "changes": changes,
            "saved_at": datetime.now().isoformat(),
        }

        # Versions klasörüne kaydet
        filename = f"{version.replace('.', '_')}.json"
        filepath = os.path.join(VERSION_DIR, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)

        # State dosyasını da kopyala
        state_src = "logs/learning_state.json"
        if os.path.exists(state_src):
            state_dst = os.path.join(VERSION_DIR, f"{version.replace('.', '_')}_state.json")
            shutil.copy2(state_src, state_dst)

        # Mevcut versiyonu güncelle
        self.current = snapshot
        self._save_current()

        print(f"  ✓ Versiyon kaydedildi: {version}")
        return filepath

    def list_versions(self) -> list:
        """Tüm versiyonları listele."""
        versions = []
        for f in sorted(Path(VERSION_DIR).glob("v7_*.json")):
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                versions.append({
                    "version": data["version"],
                    "date": data["saved_at"],
                    "changes": data.get("changes", []),
                })
        return versions

    def restore_version(self, version: str) -> bool:
        """Belirli bir versiyona geri dön."""
        filename = f"{version.replace('.', '_')}.json"
        filepath = os.path.join(VERSION_DIR, filename)

        if not os.path.exists(filepath):
            print(f"  ✗ Versiyon bulunamadı: {version}")
            return False

        with open(filepath, "r", encoding="utf-8") as f:
            snapshot = json.load(f)

        # State dosyasını geri yükle
        state_src = os.path.join(VERSION_DIR, f"{version.replace('.', '_')}_state.json")
        if os.path.exists(state_src):
            shutil.copy2(state_src, "logs/learning_state.json")

        self.current = snapshot
        self._save_current()

        print(f"  ✓ Versiyona geri dönüldü: {version}")
        print(f"  Parametreler: {json.dumps(snapshot['params'], indent=2)}")
        return True

    def get_current_version(self) -> str:
        return self.current.get("version", "v7.000")

    def get_current_params(self) -> dict:
        return self.current.get("params", {})


if __name__ == "__main__":
    vm = VersionManager()
    print(f"Mevcut versiyon: {vm.get_current_version()}")
    print()
    print("Geçmiş versiyonlar:")
    for v in vm.list_versions():
        print(f"  {v['version']} — {v['date'][:10]} — {', '.join(v['changes'][:3])}")
