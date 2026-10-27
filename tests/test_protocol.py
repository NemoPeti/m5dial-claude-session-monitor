"""A soronkenti JSON vezetekprotokoll tesztjei -- asztali Pythonon futnak, hardver nelkul."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from session_agent.protocol import (  # noqa: E402
    LineReader,
    decode_line,
    encode_event,
    encode_snapshot,
)


class EncodeSnapshot(unittest.TestCase):
    def test_alap_alak_megfelel_a_specnek(self):
        cfg = {"mute": False, "volume": 2}
        sessions = [{"id": "2cd028e8", "n": "cc-m5stack-dialv1.1", "st": "waiting"}]
        line = encode_snapshot(41, cfg, sessions)
        decoded = decode_line(line)
        self.assertEqual(decoded["t"], "s")
        self.assertEqual(decoded["seq"], 41)
        self.assertEqual(decoded["cfg"], cfg)
        self.assertEqual(decoded["sessions"], sessions)

    def test_egy_sor_egy_lezaro_ujsorral_vegzodik(self):
        line = encode_snapshot(1, {"mute": False, "volume": 2}, [])
        self.assertTrue(line.endswith("\n"))
        self.assertEqual(line.count("\n"), 1)

    def test_ures_session_lista(self):
        line = encode_snapshot(7, {"mute": True, "volume": 0}, [])
        decoded = decode_line(line)
        self.assertEqual(decoded["sessions"], [])

    def test_ekezetes_session_nev_tulel_egy_kort(self):
        sessions = [{"id": "abc123", "n": "árvíztűrő tükörfúrógép", "st": "busy"}]
        line = encode_snapshot(2, {"mute": False, "volume": 3}, sessions)
        decoded = decode_line(line)
        self.assertEqual(decoded["sessions"][0]["n"], "árvíztűrő tükörfúrógép")


    def test_a_zar_jelzes_kimarad_ha_nincs_zar(self):
        line = encode_snapshot(3, {"mute": False, "volume": 2}, [], lock=None)
        self.assertNotIn("lk", decode_line(line))

    def test_a_zar_jelzes_alapbol_kimarad(self):
        line = encode_snapshot(3, {"mute": False, "volume": 2}, [])
        self.assertNotIn("lk", decode_line(line))

    def test_a_zar_oka_atmegy_a_vezeteken(self):
        line = encode_snapshot(4, {"mute": False, "volume": 2}, [], lock="lock")
        self.assertEqual(decode_line(line)["lk"], "lock")

    def test_a_kepernyovedo_oka_is_atmegy(self):
        line = encode_snapshot(5, {"mute": False, "volume": 2}, [], lock="saver")
        self.assertEqual(decode_line(line)["lk"], "saver")

    def test_az_aktiv_tab_alapbol_kimarad(self):
        line = encode_snapshot(6, {"mute": False, "volume": 2}, [])
        self.assertNotIn("act", decode_line(line))

    def test_az_aktiv_tab_kimarad_ha_nincs(self):
        line = encode_snapshot(6, {"mute": False, "volume": 2}, [], active=None)
        self.assertNotIn("act", decode_line(line))

    def test_az_aktiv_tab_azonositoja_atmegy(self):
        sessions = [{"id": "2cd028e8", "n": "alfa", "st": "idle"}]
        line = encode_snapshot(7, {"mute": False, "volume": 2}, sessions,
                               active="2cd028e8")
        self.assertEqual(decode_line(line)["act"], "2cd028e8")

    def test_az_aktiv_tab_mezo_rovid_marad(self):
        """A Dial koronkent ~1024 bajtot olvas: a mezo csak az azonositot hozza."""
        sid = "0123456789abcdef0123456789abcdef"
        base = encode_snapshot(8, {"mute": False, "volume": 2}, [])
        with_act = encode_snapshot(8, {"mute": False, "volume": 2}, [], active=sid)
        self.assertLessEqual(len(with_act) - len(base), len(sid) + 12)


class EncodeEvent(unittest.TestCase):
    def test_ack_esemeny(self):
        line = encode_event("ack", id="2cd028e8")
        decoded = decode_line(line)
        self.assertEqual(decoded, {"t": "ack", "id": "2cd028e8"})

    def test_focus_esemeny_mezo_nelkul(self):
        line = encode_event("focus")
        decoded = decode_line(line)
        self.assertEqual(decoded, {"t": "focus"})

    def test_vol_esemeny_nemitassal(self):
        line = encode_event("vol", v=2, m=1)
        self.assertEqual(decode_line(line), {"t": "vol", "v": 2, "m": 1})

    def test_vol_esemeny(self):
        line = encode_event("vol", v=2)
        decoded = decode_line(line)
        self.assertEqual(decoded, {"t": "vol", "v": 2})

    def test_egy_sor_egy_lezaro_ujsorral_vegzodik(self):
        line = encode_event("focus")
        self.assertTrue(line.endswith("\n"))
        self.assertEqual(line.count("\n"), 1)


class DecodeLine(unittest.TestCase):
    def test_ures_sor_none(self):
        self.assertIsNone(decode_line(""))
        self.assertIsNone(decode_line("\n"))
        self.assertIsNone(decode_line("   \n"))

    def test_ertelmezhetetlen_json_none(self):
        self.assertIsNone(decode_line("{nem json"))
        self.assertIsNone(decode_line("ez sima szoveg"))

    def test_ervenyes_json_de_nem_objektum_none(self):
        self.assertIsNone(decode_line("[1, 2, 3]"))
        self.assertIsNone(decode_line("42"))
        self.assertIsNone(decode_line('"szoveg"'))

    def test_objektum_t_kulcs_nelkul_none(self):
        self.assertIsNone(decode_line('{"foo": "bar"}'))

    def test_normal_sor_dekodolasa(self):
        decoded = decode_line('{"t":"ack","id":"xyz"}\n')
        self.assertEqual(decoded, {"t": "ack", "id": "xyz"})


class LineReaderFeed(unittest.TestCase):
    def test_tobb_teljes_sor_egy_chunkban(self):
        reader = LineReader()
        chunk = '{"t":"ack","id":"a"}\n{"t":"focus"}\n'
        messages = reader.feed(chunk)
        self.assertEqual(messages, [{"t": "ack", "id": "a"}, {"t": "focus"}])

    def test_felbevagott_sor_pufferelodik(self):
        reader = LineReader()
        first = reader.feed('{"t":"ack",')
        self.assertEqual(first, [])
        second = reader.feed('"id":"a"}\n')
        self.assertEqual(second, [{"t": "ack", "id": "a"}])

    def test_ures_chunk(self):
        reader = LineReader()
        self.assertEqual(reader.feed(""), [])
        self.assertEqual(reader.feed(b""), [])

    def test_csak_ujsor_chunk(self):
        reader = LineReader()
        self.assertEqual(reader.feed("\n"), [])

    def test_szemet_sorok_a_jok_kozott_eldobodnak(self):
        reader = LineReader()
        chunk = 'garbage\n{"t":"focus"}\n{nem json\n{"t":"vol","v":1}\n'
        messages = reader.feed(chunk)
        self.assertEqual(messages, [{"t": "focus"}, {"t": "vol", "v": 1}])

    def test_bytes_bemenet_is_mukodik(self):
        reader = LineReader()
        messages = reader.feed(b'{"t":"focus"}\n')
        self.assertEqual(messages, [{"t": "focus"}])

    def test_bytes_es_str_chunk_keveredhet(self):
        reader = LineReader()
        first = reader.feed(b'{"t":"ack",')
        self.assertEqual(first, [])
        second = reader.feed('"id":"a"}\n')
        self.assertEqual(second, [{"t": "ack", "id": "a"}])

    def test_tul_hosszu_sor_ujsor_nelkul_eldobodik(self):
        reader = LineReader()
        huge = "x" * 5000
        messages = reader.feed(huge)
        self.assertEqual(messages, [])
        # a puffernek most ki kell urulnie, kulonben vegtelenul none
        messages = reader.feed('{"t":"focus"}\n')
        self.assertEqual(messages, [{"t": "focus"}])


class RoundTrip(unittest.TestCase):
    def test_snapshot_oda_vissza(self):
        cfg = {"mute": False, "volume": 1}
        sessions = [
            {"id": "aaa", "n": "proj-one", "st": "idle"},
            {"id": "bbb", "n": "proj-two", "st": "blocked"},
        ]
        line = encode_snapshot(99, cfg, sessions)
        reader = LineReader()
        messages = reader.feed(line)
        self.assertEqual(len(messages), 1)
        decoded = messages[0]
        self.assertEqual(decoded["t"], "s")
        self.assertEqual(decoded["seq"], 99)
        self.assertEqual(decoded["cfg"], cfg)
        self.assertEqual(decoded["sessions"], sessions)

    def test_event_oda_vissza(self):
        line = encode_event("vol", v=3)
        reader = LineReader()
        messages = reader.feed(line)
        self.assertEqual(messages, [{"t": "vol", "v": 3}])


if __name__ == "__main__":
    unittest.main(verbosity=2)
