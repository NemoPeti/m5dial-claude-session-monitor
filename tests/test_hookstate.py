"""A hook allapot-lekepezesenek tesztjei — hook es hardver nelkul, asztali Pythonon."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from session_agent.hookstate import (  # noqa: E402
    AGENT_STALE_S,
    DELETE,
    focus_url_from_env,
    next_record,
    session_id_of,
    state_for,
    status_record,
)


def payload(event, **extra):
    base = {
        "hook_event_name": event,
        "session_id": "2cd028e8",
        "cwd": r"D:\proj\demo",
        "transcript_path": r"C:\tmp\t.jsonl",
    }
    base.update(extra)
    return base


class StateFor(unittest.TestCase):
    def test_a_negy_egyszeru_esemeny(self):
        self.assertEqual(state_for(payload("PermissionRequest")), "blocked")
        self.assertEqual(state_for(payload("UserPromptSubmit")), "busy")
        self.assertEqual(state_for(payload("Stop")), "idle")
        self.assertEqual(state_for(payload("SessionEnd")), DELETE)

    def test_notification_idle_prompttal_varakozas(self):
        p = payload("Notification", notification_type="idle_prompt")
        self.assertEqual(state_for(p), "waiting")

    def test_notification_mas_tipussal_nem_allit_allapotot(self):
        p = payload("Notification", notification_type="valami_mas")
        self.assertIsNone(
            state_for(p), "ismeretlen tipusbol nem szabad hamis 'rad var' jelzes"
        )

    def test_notification_tipus_nelkul_nem_allit_allapotot(self):
        self.assertIsNone(state_for(payload("Notification")))

    def test_ismeretlen_esemeny(self):
        self.assertIsNone(state_for(payload("SessionStart")))

    def test_hibas_bemenet_nem_szall_el(self):
        for bad in (None, "", 42, [], {"nincs": "esemeny"}):
            self.assertIsNone(state_for(bad))


class StatusRecord(unittest.TestCase):
    def test_a_negy_mezot_irja(self):
        rec = status_record(payload("UserPromptSubmit"), 96624, 1757421000.9)
        self.assertEqual(
            rec,
            {
                "state": "busy",
                "ts": 1757421000,
                "pid": 96624,
                "cwd": r"D:\proj\demo",
            },
        )

    def test_a_ts_egesz_szamma_valik(self):
        rec = status_record(payload("Stop"), 1, 1757421000.999)
        self.assertIsInstance(rec["ts"], int)

    def test_sessionend_nem_ir_rekordot(self):
        self.assertIsNone(
            status_record(payload("SessionEnd"), 1, 0),
            "a session vegen torolni kell a fajlt, nem irni",
        )

    def test_erdektelen_esemeny_nem_ir_rekordot(self):
        self.assertIsNone(status_record(payload("SessionStart"), 1, 0))

    def test_hianyzo_cwd_ures_sztring_lesz(self):
        p = payload("Stop")
        del p["cwd"]
        self.assertEqual(status_record(p, 1, 0)["cwd"], "")

    def test_feloldatlan_pid_none_marad(self):
        rec = status_record(payload("Stop"), None, 0)
        self.assertIsNone(rec["pid"], "az arva eset a snapshot dolga, nem itt dol el")


class SessionIdOf(unittest.TestCase):
    def test_szokasos_azonosito(self):
        self.assertEqual(session_id_of(payload("Stop")), "2cd028e8")

    def test_hianyzo_vagy_ures_azonosito(self):
        self.assertIsNone(session_id_of(payload("Stop", session_id="")))
        self.assertIsNone(session_id_of({"hook_event_name": "Stop"}))

    def test_utvonal_elvalaszto_az_azonositoban_elutasitva(self):
        for bad in ("../x", r"..\x", "a/b", "."):
            self.assertIsNone(
                session_id_of(payload("Stop", session_id=bad)),
                "a fajlnevbe kerul, nem torhet ki a mappabol",
            )

    def test_nem_sztring_azonosito(self):
        self.assertIsNone(session_id_of(payload("Stop", session_id=123)))


class FocusUrlAKornyezetbol(unittest.TestCase):
    """A Warp-tab azonositoja (warpdotdev/warp#8611 -> PR #11130, merge-elve)."""

    def test_a_meresben_latott_valodi_erteket_elfogadja(self):
        env = {"WARP_FOCUS_URL": "warp://session/f96028319afc4f178bebc90a25841f1b"}
        self.assertEqual(focus_url_from_env(env), "warp://session/f96028319afc4f178bebc90a25841f1b")

    def test_korulvago_szokozoket_levagja(self):
        env = {"WARP_FOCUS_URL": "  warp://session/f96028319afc4f178bebc90a25841f1b  "}
        self.assertEqual(focus_url_from_env(env), "warp://session/f96028319afc4f178bebc90a25841f1b")

    def test_hianyzo_valtozora_none(self):
        self.assertIsNone(focus_url_from_env({}))
        self.assertIsNone(focus_url_from_env(None))

    def test_ures_ertekre_none(self):
        self.assertIsNone(focus_url_from_env({"WARP_FOCUS_URL": ""}))

    def test_idegen_semat_nem_fogad_el(self):
        self.assertIsNone(
            focus_url_from_env({"WARP_FOCUS_URL": "http://example.com"})
        )

    def test_nem_sztring_erteket_nem_fogad_el(self):
        self.assertIsNone(focus_url_from_env({"WARP_FOCUS_URL": 42}))


class AlugynokonBeluliEsemenyek(unittest.TestCase):
    """Az `agent_id`-t hordozo esemenyek egy alugynokbol jonnek (hooks.md)."""

    def test_alugynok_engedelykerese_blokkol(self):
        p = payload("PermissionRequest", agent_id="ag1", agent_type="Explore")
        self.assertEqual(state_for(p), "blocked", "a felhasznalo kell hozza")

    def test_alugynok_stopja_nem_allitja_idle_re_a_szulot(self):
        p = payload("Stop", agent_id="ag1")
        self.assertIsNone(state_for(p))

    def test_alugynok_idle_prompt_ertesitese_valtozatlan(self):
        p = payload("Notification", notification_type="idle_prompt", agent_id="ag1")
        self.assertEqual(state_for(p), "waiting")

    def test_subagent_start_es_stop_nem_allapot(self):
        self.assertIsNone(state_for(payload("SubagentStart", agent_id="ag1")))
        self.assertIsNone(state_for(payload("SubagentStop", agent_id="ag1")))


class NextRecord(unittest.TestCase):
    """Az elozo rekord + egy esemeny -> az uj rekord (alugynok-kovetes)."""

    def test_subagent_start_felveszi_es_megtartja_az_allapotot(self):
        prev = {"state": "busy", "ts": 900, "pid": 7, "cwd": "d:\\a"}
        rec = next_record(prev, payload("SubagentStart", agent_id="ag1"), 7, 1000)
        self.assertEqual(rec["state"], "busy")
        self.assertEqual(rec["ts"], 900, "az allapot nem valtozott, a ts sem")
        self.assertEqual(rec["agents"], {"ag1": 1000})

    def test_subagent_stop_torli_es_feljegyzi_a_veget(self):
        prev = {"state": "idle", "ts": 900, "pid": 7, "cwd": "d:\\a",
                "agents": {"ag1": 950, "ag2": 960}}
        rec = next_record(prev, payload("SubagentStop", agent_id="ag1"), 7, 1000)
        self.assertEqual(rec["state"], "idle")
        self.assertEqual(rec["agents"], {"ag2": 960})
        self.assertEqual(rec["agents_ts"], 1000)

    def test_utolso_alugynok_utan_nincs_agents_mezo(self):
        prev = {"state": "idle", "ts": 900, "pid": 7, "cwd": "", "agents": {"ag1": 950}}
        rec = next_record(prev, payload("SubagentStop", agent_id="ag1"), 7, 1000)
        self.assertNotIn("agents", rec)
        self.assertEqual(rec["agents_ts"], 1000)

    def test_agent_id_nelkuli_subagent_esemeny_nem_ir(self):
        prev = {"state": "idle", "ts": 900, "pid": 7, "cwd": ""}
        self.assertIsNone(next_record(prev, payload("SubagentStart"), 7, 1000))

    def test_elozo_rekord_nelkul_a_subagent_start_busy(self):
        rec = next_record(None, payload("SubagentStart", agent_id="ag1"), 7, 1000)
        self.assertEqual(rec["state"], "busy")
        self.assertEqual(rec["ts"], 1000)
        self.assertEqual(rec["agents"], {"ag1": 1000})

    def test_stop_megtartja_a_futo_alugynokoket(self):
        prev = {"state": "busy", "ts": 900, "pid": 7, "cwd": "", "agents": {"ag1": 950}}
        rec = next_record(prev, payload("Stop"), 7, 1000)
        self.assertEqual(rec["state"], "idle")
        self.assertEqual(rec["ts"], 1000)
        self.assertEqual(rec["agents"], {"ag1": 950})

    def test_userpromptsubmit_nem_torli_az_alugynokoket(self):
        prev = {"state": "idle", "ts": 900, "pid": 7, "cwd": "", "agents": {"ag1": 950}}
        rec = next_record(prev, payload("UserPromptSubmit"), 7, 1000)
        self.assertEqual(rec["state"], "busy")
        self.assertEqual(rec["agents"], {"ag1": 950})

    def test_sessionend_torles(self):
        prev = {"state": "idle", "ts": 900, "pid": 7, "cwd": "", "agents": {"ag1": 950}}
        self.assertEqual(next_record(prev, payload("SessionEnd"), 7, 1000), DELETE)

    def test_erdektelen_esemeny_none(self):
        self.assertIsNone(next_record({}, payload("SessionStart"), 7, 1000))

    def test_elavult_alugynok_kikerul_es_a_lejarata_a_veg(self):
        prev = {"state": "idle", "ts": 900, "pid": 7, "cwd": "",
                "agents": {"regi": 100, "ag2": 5000}}
        now = 100 + AGENT_STALE_S + 10
        rec = next_record(prev, payload("SubagentStart", agent_id="uj"), 7, now)
        self.assertEqual(rec["agents"], {"ag2": 5000, "uj": now})
        self.assertEqual(rec["agents_ts"], 100 + AGENT_STALE_S)

    def test_serult_agents_mezo_nem_szall_el(self):
        for bad in ("x", 42, ["a"], {"a": "nem szam"}):
            prev = {"state": "idle", "ts": 900, "pid": 7, "cwd": "", "agents": bad}
            rec = next_record(prev, payload("SubagentStart", agent_id="ag1"), 7, 1000)
            self.assertEqual(rec["agents"], {"ag1": 1000})

    def test_regi_agents_ts_nem_kerul_a_friss_rekordba(self):
        prev = {"state": "idle", "ts": 900, "pid": 7, "cwd": "", "agents_ts": 800}
        rec = next_record(prev, payload("UserPromptSubmit"), 7, 1000)
        self.assertNotIn("agents_ts", rec, "a ts-nel regebbi veg nem szamit")


if __name__ == "__main__":
    unittest.main()
