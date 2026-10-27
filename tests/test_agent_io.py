"""Az ügynök fájl-olvasásának tesztjei — soros port és hardver nélkül.

Ez a réteg élesben bukott meg: a `weather.json` ugyanabban a mappában ül, mint
az állapotfájlok, és állapotfájlként értelmezve `KeyError: 'state'`-tel
megállította az egész kört. Ezek a tesztek ezt tartják zárva.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from session_agent import agent as agent_module  # noqa: E402
from session_agent.agent import read_status_files  # noqa: E402
from session_agent.snapshot import build_snapshot  # noqa: E402


def write(directory, name, data):
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    return path


class ReadStatusFiles(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_beolvassa_az_allapotfajlokat(self):
        write(self.dir, "abc123.json", {"state": "waiting", "ts": 1, "pid": 5})
        files = read_status_files(self.dir)
        self.assertEqual(list(files), ["abc123"])
        self.assertEqual(files["abc123"]["state"], "waiting")

    def test_a_weather_json_nem_allapotfajl(self):
        write(self.dir, "weather.json", {"t": 20, "c": "felhos", "ts": 1})
        self.assertEqual(read_status_files(self.dir), {})

    def test_a_config_json_nem_allapotfajl(self):
        write(self.dir, "config.json", {"mute": False, "volume": 2})
        self.assertEqual(read_status_files(self.dir), {})

    def test_state_nelkuli_fajl_kimarad(self):
        write(self.dir, "valami.json", {"ts": 1, "pid": 5})
        self.assertEqual(
            read_status_files(self.dir), {}, "az ismertetojel a state mezo"
        )

    def test_nem_sztring_state_kimarad(self):
        write(self.dir, "valami.json", {"state": 42})
        self.assertEqual(read_status_files(self.dir), {})

    def test_serult_json_nem_allitja_meg(self):
        with open(os.path.join(self.dir, "romlott.json"), "w", encoding="utf-8") as h:
            h.write("{ ez nem json")
        write(self.dir, "jo.json", {"state": "idle", "ts": 1, "pid": 5})
        self.assertEqual(list(read_status_files(self.dir)), ["jo"])

    def test_nem_json_kiterjesztes_kimarad(self):
        with open(os.path.join(self.dir, ".release"), "w", encoding="utf-8") as h:
            h.write("")
        self.assertEqual(read_status_files(self.dir), {})

    def test_nem_letezo_mappa_ures_eredmeny(self):
        self.assertEqual(read_status_files(os.path.join(self.dir, "nincs")), {})


class BuildSnapshotRobusztussag(unittest.TestCase):
    """Ha egy hibás rekord mégis átcsúszik, a pillanatkép nem eshet szét."""

    def test_state_nelkuli_rekord_unknown_lesz_nem_kivetel(self):
        procs = [
            {
                "pid": 5,
                "exe_path": r"C:\x\claude.exe",
                "parent_name": "pwsh.exe",
                "name": "proba",
                "cwd": None,
            }
        ]
        status = {"abc": {"ts": 1, "pid": 5}}  # nincs "state"
        sessions, stale = build_snapshot(procs, status, 100)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["st"], "unknown")
        self.assertEqual(stale, [])


class HibaturesAKorben(unittest.TestCase):
    """Egy elszállt kör nem döntheti meg a szolgáltatást.

    A `tick()`-ben csak a soros rész volt védve; bármi más (egy sérült fájl, egy
    pillanatnyi CIM-hiba) kilőtte volna az egész ügynököt, és a Dial csendben
    „nincs kapcsolat"-ra váltott volna.
    """

    def _agent(self, fail_times):
        from session_agent.agent import Agent

        naplo = []
        agent = Agent(
            "COM_NINCS", status_dir=self.dir, log=naplo.append, tick_s=0
        )
        allapot = {"hivas": 0}

        def tick():
            allapot["hivas"] += 1
            if allapot["hivas"] <= fail_times:
                raise RuntimeError("szandekos hiba")

        agent.tick = tick
        return agent, allapot, naplo

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_egy_hibas_kor_utan_fut_tovabb(self):
        agent, allapot, naplo = self._agent(fail_times=2)
        agent.run(ticks=5, use_lock=False)
        self.assertEqual(allapot["hivas"], 5, "mind az ot kornek le kellett futnia")
        self.assertTrue(any("szandekos hiba" in sor for sor in naplo))

    def test_tartos_hiba_utan_feladja(self):
        from session_agent.agent import MAX_CONSECUTIVE_ERRORS

        agent, allapot, naplo = self._agent(fail_times=10000)
        agent.run(ticks=MAX_CONSECUTIVE_ERRORS + 50, use_lock=False)
        self.assertEqual(
            allapot["hivas"],
            MAX_CONSECUTIVE_ERRORS,
            "tartos hiba eseten nem pörög tovább a vegtelensegig",
        )
        self.assertTrue(any("feladom" in sor for sor in naplo))

    def test_a_szamlalo_nullazodik_egy_sikeres_kor_utan(self):
        from session_agent.agent import MAX_CONSECUTIVE_ERRORS

        agent, allapot, naplo = self._agent(fail_times=MAX_CONSECUTIVE_ERRORS - 1)
        agent.run(ticks=MAX_CONSECUTIVE_ERRORS + 5, use_lock=False)
        self.assertEqual(
            allapot["hivas"],
            MAX_CONSECUTIVE_ERRORS + 5,
            "a sikeres kor utan ujra teli a hibakeret",
        )


class FocusEsemeny(unittest.TestCase):
    """A Dial `focus` kerese (terv 4.4): session-azonosito -> Warp-tab neve.

    A Windows-oldali muveletet (ablak elore, tabvaltas) kicsereljuk - itt csak
    az erdekel, hogy az ugynok a HELYES nevet adja at, es hogy egy elszallt
    focus ne dontse meg a kort.
    """

    def setUp(self):
        from session_agent import warpfocus
        from session_agent.agent import Agent

        self.warpfocus = warpfocus
        self.calls = []
        self.orig = warpfocus.focus_session
        warpfocus.focus_session = self._fake_focus
        self.agent = Agent("COM_TESZT", status_dir="nincs-ilyen-mappa",
                           log=lambda *_a, **_k: None)

    def tearDown(self):
        self.warpfocus.focus_session = self.orig

    def _fake_focus(self, name, pids, log=None, focus_url=None):
        self.calls.append(name)
        return "found"

    def test_az_azonositobol_a_session_nevet_kuldi_tovabb(self):
        self.agent.last_sessions = [
            {"id": "aaa", "n": "cc-m5stack-dialv1.1", "st": "waiting"},
            {"id": "bbb", "n": "ShopKit", "st": "busy"},
        ]
        self.agent._apply_event({"t": "focus", "id": "bbb"})
        self.assertEqual(self.calls, ["ShopKit"])

    def test_ismeretlen_azonositonal_is_elore_hozza_az_ablakot(self):
        """Nev nelkul is hivunk: az ablak elore hozasa a garantalt resz."""
        self.agent.last_sessions = [{"id": "aaa", "n": "alfa", "st": "idle"}]
        self.agent._apply_event({"t": "focus", "id": "nincs-ilyen"})
        self.assertEqual(self.calls, [None])

    def test_ures_pillanatkepnel_sem_szall_el(self):
        self.agent.last_sessions = []
        self.agent._apply_event({"t": "focus", "id": "barmi"})
        self.assertEqual(self.calls, [None])

    def test_a_focus_hibaja_nem_dontheti_meg_az_ugynokot(self):
        def robban(name, pids, log=None, focus_url=None):
            raise RuntimeError("a Warp eltunt")

        self.warpfocus.focus_session = robban
        self.agent.last_sessions = [{"id": "aaa", "n": "alfa", "st": "idle"}]
        self.agent._apply_event({"t": "focus", "id": "aaa"})  # nem dobhat

    def test_a_nev_nelkuli_session_nem_okoz_kivetelt(self):
        self.agent.last_sessions = [{"id": "aaa", "st": "idle"}]
        self.agent._apply_event({"t": "focus", "id": "aaa"})
        self.assertEqual(self.calls, [None])


class AktivTabOlvasas(unittest.TestCase):
    """Az ugynok minden korben megnezi, melyik session Warp-tabja van elol.

    A Win32-olvasast (`foreground_probe`) kicsereljuk; a dontes tiszta fuggveny.
    """

    SESSIONS = [
        {"id": "aaa", "n": "alfa", "st": "idle"},
        {"id": "bbb", "n": "beta", "st": "busy"},
    ]

    def _agent(self, probe):
        from session_agent.agent import Agent

        self.naplo = []
        return Agent("COM_TESZT", status_dir="nincs-ilyen-mappa",
                     log=self.naplo.append, foreground_probe=probe)

    def test_elol_levo_warp_tab_azonositoja(self):
        agent = self._agent(lambda: ("✳ beta", True))
        self.assertEqual(agent._read_active(self.SESSIONS), "bbb")

    def test_mas_alkalmazas_elol_nincs_aktiv(self):
        agent = self._agent(lambda: ("beta", False))
        self.assertIsNone(agent._read_active(self.SESSIONS))

    def test_a_proba_hibaja_nem_donti_meg_a_kort(self):
        def robban():
            raise OSError("GetForegroundWindow elbukott")

        agent = self._agent(robban)
        self.assertIsNone(agent._read_active(self.SESSIONS))

    def test_a_proba_hibaja_csak_egyszer_naplozodik(self):
        def robban():
            raise OSError("nincs ablak")

        agent = self._agent(robban)
        agent._read_active(self.SESSIONS)
        agent._read_active(self.SESSIONS)
        self.assertEqual(len([s for s in self.naplo if "nincs ablak" in s]), 1)

    def test_ertelmezhetetlen_proba_eredmeny_nincs_aktiv(self):
        agent = self._agent(lambda: None)
        self.assertIsNone(agent._read_active(self.SESSIONS))


class VolEsemeny(unittest.TestCase):
    """A Dial "vol" esemenye: fokozat + (opcionalis) nemitas."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        path = os.path.join(self._tmp.name, "config.json")
        write(self._tmp.name, "config.json", {"mute": False, "volume": 2})
        patcher = mock.patch.object(agent_module, "CONFIG_PATH", path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)
        self.path = path
        self.agent = agent_module.Agent("COM_TESZT", status_dir="nincs-ilyen-mappa",
                                        log=lambda *_a, **_k: None)

    def test_m_nelkul_nem_nemit(self):
        self.agent.cfg = {"mute": True, "volume": 1}
        self.agent._apply_event({"t": "vol", "v": 3})
        self.assertEqual(self.agent.cfg["volume"], 3)
        self.assertFalse(self.agent.cfg["mute"])

    def test_m_egy_nemit_es_megtartja_a_fokozatot(self):
        self.agent._apply_event({"t": "vol", "v": 2, "m": 1})
        self.assertEqual(self.agent.cfg["volume"], 2)
        self.assertTrue(self.agent.cfg["mute"])
        with open(self.path, encoding="utf-8") as h:
            self.assertEqual(json.load(h), {"mute": True, "volume": 2})

    def test_m_nulla_felold(self):
        self.agent.cfg = {"mute": True, "volume": 2}
        self.agent._apply_event({"t": "vol", "v": 2, "m": 0})
        self.assertFalse(self.agent.cfg["mute"])


if __name__ == "__main__":
    unittest.main()
