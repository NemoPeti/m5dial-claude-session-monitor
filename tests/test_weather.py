"""Az idojaras-lekerdezes (weather.py) tesztjei. Mindig fake fetcher-t hasznalnak,
soha nem eri el a valodi Open-Meteo API-t, es mindig tempfile-t hasznalnak a
gyorsitotarnak - soha nem nyulnak a valodi ~/.claude/session-status/-hoz."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from session_agent.weather import (  # noqa: E402
    TTL_S,
    WMO_LABELS,
    get_weather,
    is_fresh,
    load_cache,
    parse_open_meteo,
    save_cache,
)


class WeatherTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmpdir.name, "weather.json")

    def tearDown(self):
        self.tmpdir.cleanup()

    def write_raw(self, content):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(content)


class ParseOpenMeteo(unittest.TestCase):
    def test_valos_alaku_valasz_kerekitett_homerseklettel_es_cimkevel(self):
        payload = {"current": {"temperature_2m": 12.4, "weather_code": 3}}
        result = parse_open_meteo(payload)
        self.assertEqual(result, {"t": 12, "c": "felhos"})

    def test_kerekites_felfele(self):
        payload = {"current": {"temperature_2m": 12.6, "weather_code": 0}}
        result = parse_open_meteo(payload)
        self.assertEqual(result["t"], 13)

    def test_none_bemenetre_none(self):
        self.assertIsNone(parse_open_meteo(None))

    def test_nem_dict_bemenetre_none(self):
        self.assertIsNone(parse_open_meteo([1, 2, 3]))
        self.assertIsNone(parse_open_meteo("nem dict"))

    def test_hianyzo_current_kulcsra_none(self):
        self.assertIsNone(parse_open_meteo({}))

    def test_hianyzo_homerseklet_kulcsra_none(self):
        self.assertIsNone(parse_open_meteo({"current": {"weather_code": 0}}))

    def test_nem_szamszeru_homerseklet_none(self):
        payload = {"current": {"temperature_2m": "meleg", "weather_code": 0}}
        self.assertIsNone(parse_open_meteo(payload))

    def test_hianyzo_weather_code_none(self):
        self.assertIsNone(parse_open_meteo({"current": {"temperature_2m": 10}}))

    def test_nem_szamszeru_weather_code_none(self):
        payload = {"current": {"temperature_2m": 10, "weather_code": "sok"}}
        self.assertIsNone(parse_open_meteo(payload))

    def test_minden_cimke_csak_ascii(self):
        """A c mezo bitmap fontra es soros vonalra megy - sosem lehet ekezetes."""
        for code, label in WMO_LABELS.items():
            self.assertTrue(label.isascii(), f"{code} -> {label!r} nem ASCII")
        self.assertTrue("ismeretlen".isascii())

    def test_ismeretlen_kod_ismeretlen_cimkere(self):
        payload = {"current": {"temperature_2m": 5, "weather_code": 12345}}
        result = parse_open_meteo(payload)
        self.assertEqual(result["c"], "ismeretlen")

    def test_nehany_kod_leterheleses(self):
        cases = {
            0: "napos",
            1: "felhos",
            45: "kodos",
            61: "esos",
            71: "havas",
            95: "zivatar",
        }
        for code, expected in cases.items():
            payload = {"current": {"temperature_2m": 1, "weather_code": code}}
            self.assertEqual(parse_open_meteo(payload)["c"], expected)


class IsFresh(unittest.TestCase):
    def test_ttl_n_belul_friss(self):
        cache = {"ts": 1000}
        self.assertTrue(is_fresh(cache, now_ts=1000 + TTL_S - 1))

    def test_ttl_n_tul_elavult(self):
        cache = {"ts": 1000}
        self.assertFalse(is_fresh(cache, now_ts=1000 + TTL_S + 1))

    def test_hianyzo_ts_elavultnak_szamit(self):
        self.assertFalse(is_fresh({}, now_ts=1000))

    def test_szemetes_ts_elavultnak_szamit(self):
        self.assertFalse(is_fresh({"ts": "nem szam"}, now_ts=1000))

    def test_hianyzo_cache_elavultnak_szamit(self):
        self.assertFalse(is_fresh(None, now_ts=1000))


class LoadSaveCache(WeatherTestCase):
    def test_hianyzo_fajlbol_none(self):
        self.assertIsNone(load_cache(self.path))

    def test_hibas_json_none(self):
        self.write_raw("{ez nem json")
        self.assertIsNone(load_cache(self.path))

    def test_save_utan_load_visszaadja_a_tartalmat(self):
        data = {"ts": 1234, "t": 10, "c": "napos"}
        save_cache(self.path, data)
        self.assertEqual(load_cache(self.path), data)

    def test_save_atomi_nincs_ideiglenes_fajl_a_konyvtarban(self):
        save_cache(self.path, {"ts": 1, "t": 1, "c": "napos"})
        entries = os.listdir(self.tmpdir.name)
        self.assertEqual(entries, ["weather.json"], "csak a vegleges fajl maradhat")


class GetWeather(WeatherTestCase):
    def test_friss_cache_eseten_nem_hivja_a_fetchert(self):
        save_cache(self.path, {"ts": 1000, "t": 20, "c": "napos"})

        def fetcher(lat, lon):
            raise AssertionError("nem szabadott volna meghivni a fetchert")

        result = get_weather(self.path, now_ts=1000 + 10, fetcher=fetcher)
        self.assertEqual(result, {"t": 20, "c": "napos"})

    def test_hianyzo_cache_eseten_hivja_a_fetchert_es_ment(self):
        calls = []

        def fetcher(lat, lon):
            calls.append((lat, lon))
            return {"current": {"temperature_2m": 15.0, "weather_code": 1}}

        result = get_weather(self.path, now_ts=1000, fetcher=fetcher)
        self.assertEqual(result, {"t": 15, "c": "felhos"})
        self.assertEqual(len(calls), 1)

        cached = load_cache(self.path)
        self.assertEqual(cached["t"], 15)
        self.assertEqual(cached["c"], "felhos")
        self.assertEqual(cached["ts"], 1000)

    def test_elavult_cache_eseten_hivja_a_fetchert_es_ment(self):
        save_cache(self.path, {"ts": 1000, "t": 20, "c": "napos"})

        def fetcher(lat, lon):
            return {"current": {"temperature_2m": 5.0, "weather_code": 71}}

        result = get_weather(self.path, now_ts=1000 + TTL_S + 1, fetcher=fetcher)
        self.assertEqual(result, {"t": 5, "c": "havas"})

    def test_elavult_cache_es_hibazo_fetcher_a_regi_erteket_adja(self):
        save_cache(self.path, {"ts": 1000, "t": 20, "c": "napos"})

        def fetcher(lat, lon):
            raise RuntimeError("halozati hiba")

        result = get_weather(self.path, now_ts=1000 + TTL_S + 1, fetcher=fetcher)
        self.assertEqual(result, {"t": 20, "c": "napos"})

    def test_nincs_cache_es_hibazo_fetcher_none(self):
        def fetcher(lat, lon):
            raise RuntimeError("halozati hiba")

        result = get_weather(self.path, now_ts=1000, fetcher=fetcher)
        self.assertIsNone(result)

    def test_nincs_cache_es_none_ertekkel_tero_fetcher_none(self):
        def fetcher(lat, lon):
            return None

        result = get_weather(self.path, now_ts=1000, fetcher=fetcher)
        self.assertIsNone(result)

    def test_elavult_cache_es_none_ertekkel_tero_fetcher_regi_erteket_adja(self):
        save_cache(self.path, {"ts": 1000, "t": 8, "c": "esos"})

        def fetcher(lat, lon):
            return None

        result = get_weather(self.path, now_ts=1000 + TTL_S + 1, fetcher=fetcher)
        self.assertEqual(result, {"t": 8, "c": "esos"})

    def test_fetcher_barmilyen_kivetelere_sosem_dob(self):
        def fetcher(lat, lon):
            raise ValueError("valami vaklarma")

        try:
            result = get_weather(self.path, now_ts=1000, fetcher=fetcher)
        except Exception as exc:  # pragma: no cover - ez a teszt lenyege
            self.fail(f"get_weather nem dobhat kivetelt, de dobott: {exc!r}")
        self.assertIsNone(result)

    def test_serult_cache_fajl_ugy_kezelendo_mint_ha_nem_lenne_cache(self):
        self.write_raw("{ez nem json")

        def fetcher(lat, lon):
            return {"current": {"temperature_2m": 9.0, "weather_code": 0}}

        result = get_weather(self.path, now_ts=1000, fetcher=fetcher)
        self.assertEqual(result, {"t": 9, "c": "napos"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
