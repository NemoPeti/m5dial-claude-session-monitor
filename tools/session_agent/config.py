"""PC-oldali globalis nemitas/hangero konfig (terv 4.6).

Ez a modul csak a gepen (CPython 3.12) fut, az ugynok reszekent - NEM kerul a
Dialra, tehat modern Pythont hasznalhat.

A terv explicit ok: "egy elrontott fajl nem nemithatja el nemán a
rendszert" - ezert minden serult/hianyzo/ervenytelen mezo az alapertelmezesre
all vissza, es a javitott konfig azonnal visszairodik lemezre.
"""

import json
import os
import tempfile

# A hang alapbol KI van kapcsolva (2026-09-10, felhasznaloi keres): a kijelzo
# maga is ertesit, a csipogas viszont 5-10 parhuzamos session mellett zavaro.
# A `volume` ettol fuggetlenul ertelmes marad - a felhasznalo egy erintessel
# vagy `session-agent.ps1 -Unmute`-tal bekapcsolja, es nem kell hangerot allitani.
DEFAULT_CONFIG = {"mute": True, "volume": 2}


def _sanitize(raw):
    """Egy beolvasott (esetleg hianyos/hibas) objektumot alakit ervenyes
    konfigga, mezonkent az alapertelmezesre esve vissza. Visszaadja azt is,
    hogy kellett-e barmit javitani."""
    if not isinstance(raw, dict):
        return dict(DEFAULT_CONFIG), True

    repaired = False
    cfg = {}

    mute = raw.get("mute", DEFAULT_CONFIG["mute"])
    if isinstance(mute, bool):
        cfg["mute"] = mute
    else:
        cfg["mute"] = DEFAULT_CONFIG["mute"]
        repaired = True

    volume = raw.get("volume", DEFAULT_CONFIG["volume"])
    if isinstance(volume, int) and not isinstance(volume, bool) and 0 <= volume <= 3:
        cfg["volume"] = volume
    else:
        cfg["volume"] = DEFAULT_CONFIG["volume"]
        repaired = True

    if set(raw.keys()) != {"mute", "volume"}:
        repaired = True

    return cfg, repaired


def load_config(path):
    """Betolti a konfigot. Hianyzo fajl, olvasasi hiba, hibas JSON, nem-objektum
    JSON, tartomanyon kivuli vagy rossz tipusu ertek, hianyzo kulcs - mindegyik
    esetben az erintett mezo(k) az alapertelmezesre allnak, es a javitott
    konfig visszairodik a fajlba."""
    raw = None
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        raw = None

    cfg, repaired = _sanitize(raw) if raw is not None else (dict(DEFAULT_CONFIG), True)

    if repaired or not os.path.exists(path):
        save_config(path, cfg)

    return cfg


def save_config(path, cfg):
    """Elmenti a konfigot. A csonkulas elkerulesere ideiglenes fajlba ir a
    celkonyvtarban, majd atomi mozgatassal (os.replace) helyezi a vegleges
    helyere - igy egy megszakadt iras sem hagyhat felig irt fajlt hatra."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
