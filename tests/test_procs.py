"""A folyamat-begyujtes tiszta reszenek tesztjei — hardver es Win32 nelkul."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from session_agent import procs  # noqa: E402
from session_agent.procs import parse_name  # noqa: E402


class ParseName(unittest.TestCase):
    def test_kulonallo_ertek(self):
        cmd = r"C:\Users\k\.local\bin\claude.exe --name GIT_demo --remote-control x"
        self.assertEqual(parse_name(cmd), "GIT_demo")

    def test_egyenlosegjeles_alak(self):
        self.assertEqual(parse_name("claude.exe --name=ShopKit"), "ShopKit")

    def test_idezojelbe_tett_szokozos_ertek(self):
        cmd = 'claude.exe --name "ket szavas nev" --resume'
        self.assertEqual(parse_name(cmd), "ket szavas nev")

    def test_nincs_name_kapcsolo(self):
        cmd = r"C:\...\AnthropicClaude\app-1.49585.0\claude.exe --type=renderer"
        self.assertIsNone(parse_name(cmd), "a Desktop folyamatain nincs --name")

    def test_ures_es_hianyzo_parancssor(self):
        self.assertIsNone(parse_name(""))
        self.assertIsNone(parse_name(None))

    def test_name_a_sor_vegen_ertek_nelkul(self):
        self.assertIsNone(parse_name("claude.exe --name"))

    def test_name_utan_masik_kapcsolo_nem_ertek(self):
        self.assertIsNone(
            parse_name("claude.exe --name --resume"),
            "a kovetkezo kapcsolo nem lehet a nev",
        )

    def test_a_nevben_levo_pont_megmarad(self):
        self.assertEqual(parse_name("claude.exe --name cc-m5stack-dialv1.1"),
                         "cc-m5stack-dialv1.1")


class FeladasUtaniUjraprobalkozas(unittest.TestCase):
    """Egy atmeneti CIM-hiba nem teheti orokre lathatatlanna a sessionoket.

    Elesben merve 2026-09-10: az ugynok 15 percen at NULLA sessiont latott, majd
    tetlenseg miatt kilepett, kozben nyolc session futott. A `_load_details`
    egyszerre kerdezi le az OSSZES claude.exe-t, ezert harom hibas kor mindet
    megmergezte - veglegesen.
    """

    def setUp(self):
        procs._detail_cache.clear()
        procs._attempts.clear()
        self.table = {
            100: (10, "claude.exe"),
            10: (1, "pwsh.exe"),
        }
        self.calls = []

    def tearDown(self):
        procs._detail_cache.clear()
        procs._attempts.clear()

    def _run(self, details, now):
        """A `list_claude_processes` a mockolt folyamattablaval es CIM-mel."""
        import unittest.mock as mock

        def fake_details(powershell="pwsh"):
            self.calls.append(now)
            return details

        with mock.patch.object(procs, "process_table", return_value=self.table), \
             mock.patch.object(procs, "_load_details", side_effect=fake_details), \
             mock.patch.object(procs.time, "time", return_value=now):
            return procs.list_claude_processes()

    def test_sikeres_lekerdezes_utan_van_eleresi_ut(self):
        out = self._run({100: {"exe_path": "C:\\claude.exe", "name": "alfa"}}, 1000)
        self.assertEqual(out[0]["exe_path"], "C:\\claude.exe")

    def test_harom_hibas_kor_utan_feladjuk(self):
        for _ in range(3):
            out = self._run({}, 1000)
        self.assertEqual(out[0]["exe_path"], "")
        self.assertEqual(len(self.calls), 3, "nem probalkozunk a vegtelensegig")

    def test_a_feladas_utan_nem_probalkozunk_azonnal_ujra(self):
        for _ in range(3):
            self._run({}, 1000)
        self._run({}, 1000 + 5)
        self.assertEqual(len(self.calls), 3, "5 masodperc mulva meg nem")

    def test_a_hutesi_ido_utan_ujraprobaljuk_es_helyreall(self):
        for _ in range(3):
            self._run({}, 1000)
        out = self._run(
            {100: {"exe_path": "C:\\claude.exe", "name": "alfa"}},
            1000 + procs.DETAIL_RETRY_S + 1,
        )
        self.assertEqual(out[0]["exe_path"], "C:\\claude.exe")
        self.assertEqual(out[0]["name"], "alfa")
        self.assertEqual(len(self.calls), 4)


if __name__ == "__main__":
    unittest.main()
