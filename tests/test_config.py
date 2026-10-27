"""A PC-oldali konfig-kezeles (4.6) tesztjei. Mindig tempfile-t hasznalnak,
soha nem nyulnak a valodi ~/.claude/session-status/config.json-hoz."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from session_agent.config import load_config, save_config, DEFAULT_CONFIG  # noqa: E402


class ConfigTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmpdir.name, "config.json")

    def tearDown(self):
        self.tmpdir.cleanup()

    def write_raw(self, content):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(content)


class LoadConfig(ConfigTestCase):
    def test_hianyzo_fajl_alapertelmezesre_all(self):
        cfg = load_config(self.path)
        self.assertEqual(cfg, DEFAULT_CONFIG)
        self.assertTrue(os.path.exists(self.path), "hianyzo fajlbol ujra kell irni")

    def test_hibas_json_alapertelmezesre_all_es_ujraír(self):
        self.write_raw("{ez nem json")
        cfg = load_config(self.path)
        self.assertEqual(cfg, DEFAULT_CONFIG)
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), DEFAULT_CONFIG)

    def test_ervenyes_json_de_nem_objektum_alapertelmezesre_all(self):
        self.write_raw("[1, 2, 3]")
        cfg = load_config(self.path)
        self.assertEqual(cfg, DEFAULT_CONFIG)

    def test_tartomanyon_kivuli_volume_javitva(self):
        self.write_raw(json.dumps({"mute": False, "volume": 99}))
        cfg = load_config(self.path)
        self.assertEqual(cfg["volume"], DEFAULT_CONFIG["volume"])
        self.assertEqual(cfg["mute"], False)

    def test_negativ_volume_javitva(self):
        self.write_raw(json.dumps({"mute": True, "volume": -1}))
        cfg = load_config(self.path)
        self.assertEqual(cfg["volume"], DEFAULT_CONFIG["volume"])
        self.assertEqual(cfg["mute"], True)

    def test_rossz_tipusu_volume_javitva(self):
        self.write_raw(json.dumps({"mute": False, "volume": "kettes"}))
        cfg = load_config(self.path)
        self.assertEqual(cfg["volume"], DEFAULT_CONFIG["volume"])

    def test_rossz_tipusu_mute_javitva(self):
        self.write_raw(json.dumps({"mute": "igen", "volume": 1}))
        cfg = load_config(self.path)
        self.assertEqual(cfg["mute"], DEFAULT_CONFIG["mute"])
        self.assertEqual(cfg["volume"], 1)

    def test_hianyzo_kulcs_javitva(self):
        self.write_raw(json.dumps({"mute": True}))
        cfg = load_config(self.path)
        self.assertEqual(cfg["mute"], True)
        self.assertEqual(cfg["volume"], DEFAULT_CONFIG["volume"])

    def test_ervenyes_konfig_valtozatlanul_visszaadva(self):
        self.write_raw(json.dumps({"mute": True, "volume": 3}))
        cfg = load_config(self.path)
        self.assertEqual(cfg, {"mute": True, "volume": 3})

    def test_olvashatatlan_fajl_alapertelmezesre_all(self):
        """Windows-on a chmod nem tiltja le megbizhatoan a tulajdonos sajat
        olvasasat, ezert ezt open()-t mockolva szimulaljuk: barmilyen OSError
        (jogosultsag, zarolt fajl, stb.) olvasas kozben alapertelmezesre
        essen vissza, es ne szalljon el."""
        self.write_raw(json.dumps({"mute": True, "volume": 1}))
        real_open = open

        def failing_open(path, *args, **kwargs):
            mode = args[0] if args else kwargs.get("mode", "r")
            if os.path.abspath(str(path)) == os.path.abspath(self.path) and "r" in mode:
                raise PermissionError("szimulalt jogosultsagi hiba")
            return real_open(path, *args, **kwargs)

        import unittest.mock as mock

        with mock.patch("builtins.open", side_effect=failing_open):
            cfg = load_config(self.path)
        self.assertEqual(cfg, DEFAULT_CONFIG)


class SaveConfig(ConfigTestCase):
    def test_tartalom_visszaolvashato(self):
        save_config(self.path, {"mute": True, "volume": 1})
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"mute": True, "volume": 1})

    def test_load_utan_save_kor_konzisztens(self):
        cfg = load_config(self.path)
        cfg["volume"] = 3
        save_config(self.path, cfg)
        # Az alapertelmezes 2026-09-10 ota nema (DEFAULT_CONFIG), a kor viszont
        # attol meg konzisztens: amit kiirtunk, azt olvassuk vissza.
        self.assertEqual(
            load_config(self.path), {"mute": DEFAULT_CONFIG["mute"], "volume": 3}
        )

    def test_ideiglenes_fajl_nem_marad_a_konyvtarban(self):
        save_config(self.path, {"mute": False, "volume": 2})
        entries = os.listdir(self.tmpdir.name)
        self.assertEqual(entries, ["config.json"], "csak a vegleges fajl maradhat")

    def test_felulirja_a_korabbi_tartalmat(self):
        save_config(self.path, {"mute": False, "volume": 0})
        save_config(self.path, {"mute": True, "volume": 3})
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"mute": True, "volume": 3})


class AlapertelmezettNemitas(unittest.TestCase):
    """2026-09-10, felhasznaloi keres: a szolgaltatas nemán induljon."""

    def test_az_alapertelmezes_nema(self):
        self.assertTrue(DEFAULT_CONFIG["mute"])

    def test_a_hangero_ettol_meg_ertelmes(self):
        """Nem 0 a hangero - egy Unmute utan azonnal hallhato legyen."""
        self.assertEqual(DEFAULT_CONFIG["volume"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
