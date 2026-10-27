"""PC-oldali idojaras-lekerdezes es -gyorsitotarazas (terv 4.4/4.6 - a
pillanatkep resze).

Ez a modul csak a gepen (CPython 3.12) fut, az ugynok reszekent - NEM kerul a
Dialra, tehat modern Pythont hasznalhat.

A gyorsitotar formaja megegyezik a `config.py` filozofiajaval: "egy elrontott
fajl nem nemithatja el nemán a rendszert" - egy serult/hianyzo/ervenytelen
gyorsitotar-fajl ugy szamit, mintha nem lenne cache, sosem dob kivetelt, es az
uj ertek atomi irassal kerul lemezre.

A `c` mezo (rovid magyar cimke) ASCII-only: bitmap fontra es soros vonalra
megy, ekezetet nem tud megjeleniteni/atvinni.
"""

import json
import os
import tempfile
import time
import urllib.request

DEFAULT_LAT = 47.4979  # Budapest
DEFAULT_LON = 19.0402
TTL_S = 3600

# WMO weather_code -> rovid, ekezet nelkuli magyar cimke.
WMO_LABELS = {
    0: "napos",
    1: "felhos",
    2: "felhos",
    3: "felhos",
    45: "kodos",
    48: "kodos",
    51: "esos",
    53: "esos",
    55: "esos",
    56: "esos",
    57: "esos",
    61: "esos",
    63: "esos",
    65: "esos",
    66: "esos",
    67: "esos",
    80: "esos",
    81: "esos",
    82: "esos",
    71: "havas",
    73: "havas",
    75: "havas",
    77: "havas",
    85: "havas",
    86: "havas",
    95: "zivatar",
    96: "zivatar",
    99: "zivatar",
}

_UNKNOWN_LABEL = "ismeretlen"


def _label_for(weather_code):
    return WMO_LABELS.get(weather_code, _UNKNOWN_LABEL)


def parse_open_meteo(payload):
    """Az Open-Meteo valaszabol {"t": int, "c": str}, vagy None.

    Soha nem dob kivetelt - barmilyen varatlan alak (hianyzo mezo, rossz
    tipus, nem-dict valasz) None-t eredmenyez."""
    if not isinstance(payload, dict):
        return None

    current = payload.get("current")
    if not isinstance(current, dict):
        return None

    temperature = current.get("temperature_2m")
    if not isinstance(temperature, (int, float)) or isinstance(temperature, bool):
        return None

    weather_code = current.get("weather_code")
    if not isinstance(weather_code, (int, float)) or isinstance(weather_code, bool):
        return None

    return {"t": round(temperature), "c": _label_for(int(weather_code))}


def is_fresh(cache, now_ts, ttl_s=TTL_S):
    """Igaz, ha a gyorsitotarazott adat meg ervenyes.

    Hianyzo/szemetes/hianyzo `ts` mindig elavultnak szamit - sosem kezeljuk
    ismeretlen korut frissnek."""
    if not isinstance(cache, dict):
        return False

    ts = cache.get("ts")
    if not isinstance(ts, (int, float)) or isinstance(ts, bool):
        return False

    return (now_ts - ts) < ttl_s


def load_cache(path):
    """Betolti a gyorsitotarat. Hianyzo fajl, olvasasi hiba vagy hibas JSON
    eseten None - ugy kezelendo, mintha nem lenne cache."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return None

    if not isinstance(raw, dict):
        return None

    return raw


def save_cache(path, data):
    """Elmenti a gyorsitotarat. A csonkulas elkerulesere ideiglenes fajlba ir
    a celkonyvtarban, majd atomi mozgatassal (os.replace) helyezi a vegleges
    helyere - igy egy megszakadt iras sem hagyhat felig irt fajlt hatra."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(prefix=".weather-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def fetch_open_meteo(lat, lon, timeout=5):
    """A halozati hivas - EZ AZ EGYETLEN tisztatalan fuggveny.

    Nyers, mar json.loads-olt valaszt ad vissza (vagy dob, ha a halozat/JSON
    hibazik - a hivo (get_weather) gondoskodik a kivetelbiztonsagrol)."""
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}&current=temperature_2m,weather_code"
    )
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def get_weather(path, lat=DEFAULT_LAT, lon=DEFAULT_LON, now_ts=None, fetcher=fetch_open_meteo):
    """A gyorsitotarbol, vagy frissen. Soha nem dob kivetelt, hiba eseten
    None.

    Ha a cache friss, azt adja vissza a fetcher hivasa nelkul. Ha elavult
    vagy hianyzik, meghivja a fetchert; ha az sikerrel jar, elmenti es azt
    adja vissza; ha a fetcher dob vagy None-t ad, a regi (esetleg elavult)
    cache-ertekre esik vissza, vagy None-ra, ha nincs mibol visszaesni."""
    if now_ts is None:
        now_ts = int(time.time())

    cache = load_cache(path)

    if is_fresh(cache, now_ts):
        return {"t": cache["t"], "c": cache["c"]}

    try:
        payload = fetcher(lat, lon)
        parsed = parse_open_meteo(payload)
    except Exception:
        parsed = None

    if parsed is not None:
        record = {"ts": now_ts, "t": parsed["t"], "c": parsed["c"]}
        try:
            save_cache(path, record)
        except OSError:
            pass
        return {"t": parsed["t"], "c": parsed["c"]}

    if isinstance(cache, dict) and "t" in cache and "c" in cache:
        return {"t": cache["t"], "c": cache["c"]}

    return None
