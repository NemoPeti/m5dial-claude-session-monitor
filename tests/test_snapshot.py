"""A session-agent osszefesulo logikajanak tesztjei — asztali Pythonon futnak, hardver nelkul."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from session_agent.snapshot import (  # noqa: E402
    AGENT_STALE_S,
    IDLE_ESCALATE_S,
    ORPHAN_TTL_S,
    build_snapshot,
    display_name,
    display_state,
    escalate_idle,
    is_session_process,
)

CLI_PATH = r"C:\Users\user\.local\bin\claude.exe"
SHELL_NAMES = {"pwsh.exe", "powershell.exe", "cmd.exe", "bash.exe", "windowsterminal.exe"}


def make_proc(pid, exe_path=CLI_PATH, parent_name="pwsh.exe", name=None, cwd=None):
    """Segedfuggveny: kitolti a proc-dict tobbi mezojet ertelmes alapertekkel."""
    return {"pid": pid, "exe_path": exe_path, "parent_name": parent_name, "name": name, "cwd": cwd}


class IsSessionProcess(unittest.TestCase):
    """A 4.3 uj szabalya: CLI-utvonal ES shell-szulo, nem `--name`."""

    def test_valodi_cli_shell_gyerekekent_elfogadott(self):
        proc = make_proc(1000, parent_name="pwsh.exe")
        self.assertTrue(is_session_process(proc, CLI_PATH, SHELL_NAMES))

    def test_utvonal_osszehasonlitas_nem_erzekeny_kis_nagybeture_es_elvalasztora(self):
        proc = make_proc(1000, exe_path=r"c:\users\user\.local\bin\CLAUDE.EXE", parent_name="PWSH.EXE")
        self.assertTrue(is_session_process(proc, CLI_PATH, SHELL_NAMES))

    def test_utvonal_perjeles_valtozata_is_egyezik(self):
        proc = make_proc(1000, exe_path="C:/Users/user/.local/bin/claude.exe")
        self.assertTrue(is_session_process(proc, CLI_PATH, SHELL_NAMES))

    def test_claude_desktop_electron_fofolyamat_kizarva_utvonal_alapjan(self):
        electron = make_proc(
            2000,
            exe_path=r"C:\Users\user\AppData\Local\AnthropicClaude\app-1.2.3\claude.exe",
            parent_name="explorer.exe",
        )
        self.assertFalse(is_session_process(electron, CLI_PATH, SHELL_NAMES))

    def test_claude_desktop_electron_gyerekfolyamatok_kizarva_utvonal_alapjan(self):
        for typ in ("renderer", "gpu-process", "utility", "crashpad-handler"):
            renderer = make_proc(
                2001,
                exe_path=r"C:\Users\user\AppData\Local\AnthropicClaude\app-1.2.3\claude.exe",
                parent_name="claude.exe",
                name=None,
            )
            self.assertFalse(
                is_session_process(renderer, CLI_PATH, SHELL_NAMES),
                "electron --type=%s gyereket ki kellene zarni" % typ,
            )

    def test_claude_exe_gyereke_kizarva_szulo_neve_alapjan(self):
        # a CLI binarisbol fut, de a szuloje egy masik claude.exe (feltetelezett alugynok)
        child = make_proc(3000, parent_name="claude.exe")
        self.assertFalse(is_session_process(child, CLI_PATH, SHELL_NAMES))

    def test_masik_binaris_kizarva_meg_ha_a_szulo_shell_is(self):
        other = make_proc(4000, exe_path=r"C:\Windows\System32\notepad.exe", parent_name="pwsh.exe")
        self.assertFalse(is_session_process(other, CLI_PATH, SHELL_NAMES))

    def test_nev_nelkuli_valodi_session_is_elfogadott(self):
        # ez az uj szabaly lenyege: --name nem szukseges a felismereshez
        proc = make_proc(5000, parent_name="WindowsTerminal.exe", name=None)
        self.assertTrue(is_session_process(proc, CLI_PATH, SHELL_NAMES))


class DisplayNameTests(unittest.TestCase):
    def test_name_mezo_elsobbseget_elvez(self):
        proc = make_proc(1, name="cc-m5stack-dialv1.1", cwd=r"D:\proj\masmi")
        self.assertEqual(display_name(proc), "cc-m5stack-dialv1.1")

    def test_name_hianyaban_a_cwd_utolso_tagja(self):
        proc = make_proc(1, name=None, cwd=r"D:\proj\cc-m5stack-dialv1.1")
        self.assertEqual(display_name(proc), "cc-m5stack-dialv1.1")

    def test_name_hianyaban_a_cwd_utolso_tagja_zaro_elvalasztoval(self):
        proc = make_proc(1, name=None, cwd=r"D:\proj\cc-m5stack-dialv1.1\\")
        self.assertEqual(display_name(proc), "cc-m5stack-dialv1.1")

    def test_name_es_cwd_hianyaban_a_pid_szovegkent(self):
        proc = make_proc(4242, name=None, cwd=None)
        self.assertEqual(display_name(proc), "4242")

    def test_ures_cwd_is_a_pid_tartalekra_esik(self):
        proc = make_proc(7, name=None, cwd="")
        self.assertEqual(display_name(proc), "7")


class BuildSnapshotMergeTable(unittest.TestCase):
    """A 4.3 osszefesulesi tablazatanak minden sora."""

    def test_elo_folyamat_es_allapotfajl_is_van__az_allapotfajl_allapota_latszik(self):
        proc = make_proc(100, name="dial", cwd=r"D:\proj\cc-m5stack-dialv1.1")
        status_files = {
            "sess-abc": {"state": "waiting", "ts": 1000, "cwd": r"D:\proj\cc-m5stack-dialv1.1"}
        }
        sessions, stale_ids = build_snapshot([proc], status_files, now_ts=2000)
        self.assertEqual(sessions, [{"id": "sess-abc", "n": "dial", "st": "waiting"}])
        self.assertEqual(stale_ids, [])

    def test_elo_folyamat_de_nincs_allapotfajl__unknown(self):
        proc = make_proc(101, name="dial", cwd=r"D:\proj\cc-m5stack-dialv1.1")
        sessions, stale_ids = build_snapshot([proc], {}, now_ts=2000)
        self.assertEqual(sessions, [{"id": "pid101", "n": "dial", "st": "unknown"}])
        self.assertEqual(stale_ids, [])

    def test_nincs_elo_folyamat_de_van_allapotfajl__elavult(self):
        status_files = {
            "sess-gone": {"state": "waiting", "ts": 1000, "cwd": r"D:\proj\eltunt"}
        }
        sessions, stale_ids = build_snapshot([], status_files, now_ts=2000)
        self.assertEqual(sessions, [])
        self.assertEqual(stale_ids, ["sess-gone"])


class BuildSnapshotEdgeCases(unittest.TestCase):
    def test_ures_bemenetek(self):
        sessions, stale_ids = build_snapshot([], {}, now_ts=0)
        self.assertEqual(sessions, [])
        self.assertEqual(stale_ids, [])

    def test_nev_nelkuli_valodi_session_a_cwd_bol_szarmazo_nevvel_jelenik_meg(self):
        # ez az egesz uj szabaly lenyege: --name nelkul sem tunik el a sessionrol a soron
        proc = make_proc(200, name=None, cwd=r"D:\proj\cc-m5stack-dialv1.1")
        status_files = {
            "sess-noname": {"state": "busy", "ts": 1000, "cwd": r"D:\proj\cc-m5stack-dialv1.1"}
        }
        sessions, _ = build_snapshot([proc], status_files, now_ts=2000)
        self.assertEqual(sessions, [{"id": "sess-noname", "n": "cc-m5stack-dialv1.1", "st": "busy"}])

    def test_stabil_sorrend_pid_szerint_rendezve(self):
        procs = [
            make_proc(300, name="c", cwd=r"D:\c"),
            make_proc(100, name="a", cwd=r"D:\a"),
            make_proc(200, name="b", cwd=r"D:\b"),
        ]
        sessions, _ = build_snapshot(procs, {}, now_ts=0)
        self.assertEqual([s["id"] for s in sessions], ["pid100", "pid200", "pid300"])

    def test_stabil_sorrend_kevert_forrassal_is_pid_szerint(self):
        procs = [
            make_proc(300, name="c", cwd=r"D:\c"),
            make_proc(100, name="a", cwd=r"D:\a"),
        ]
        status_files = {"sess-b": {"state": "idle", "ts": 1, "cwd": r"D:\c"}}
        sessions, _ = build_snapshot(procs, status_files, now_ts=0)
        self.assertEqual([s["id"] for s in sessions], ["pid100", "sess-b"])

    def test_ketertelmu_cwd_a_legkisebb_pid_kapja_az_allapotfajlt(self):
        # ket elo folyamat ugyanazzal a cwd-vel: a hook nem tudja megmondani, melyik irta
        # az allapotfajlt, mert a payload nem tartalmaz pid-et. Determinisztikus dontes:
        # a legkisebb pid-u folyamat kapja a statust, a tobbi "unknown" marad.
        procs = [
            make_proc(500, name="masodik", cwd=r"D:\proj\ketertelmu"),
            make_proc(400, name="elso", cwd=r"D:\proj\ketertelmu"),
        ]
        status_files = {
            "sess-x": {"state": "blocked", "ts": 1000, "cwd": r"D:\proj\ketertelmu"}
        }
        sessions, stale_ids = build_snapshot(procs, status_files, now_ts=2000)
        self.assertEqual(stale_ids, [])
        by_id = {s["id"]: s for s in sessions}
        self.assertEqual(by_id["sess-x"], {"id": "sess-x", "n": "elso", "st": "blocked"})
        self.assertEqual(by_id["pid500"], {"id": "pid500", "n": "masodik", "st": "unknown"})

    def test_cwd_egyezes_nem_erzekeny_kis_nagybeture_es_zaro_elvalasztora(self):
        proc = make_proc(600, name="dial", cwd=r"D:\proj\cc-m5stack-dialv1.1\\")
        status_files = {
            "sess-case": {"state": "idle", "ts": 1000, "cwd": r"d:\proj\cc-m5stack-dialv1.1"}
        }
        # A `now_ts` szandekosan kozel van a `ts`-hez: itt a PAROSITAS a targy,
        # nem az idle-eszkalacio (azt az IdleEskalacio osztaly fedi).
        sessions, stale_ids = build_snapshot([proc], status_files, now_ts=1010)
        self.assertEqual(sessions, [{"id": "sess-case", "n": "dial", "st": "idle"}])
        self.assertEqual(stale_ids, [])


class BuildSnapshotPidJoin(unittest.TestCase):
    """Az uj foagas: pid-alapu parositas (a hook a szulolancon at derite ki a pid-jet)."""

    def test_pid_alapu_parositas_mukodik_ha_a_folyamat_cwd_je_none__ez_a_valos_eset(self):
        # a valodi gyujto (procs.py) SOHA nem tudja a masik folyamat cwd-jet a Win32
        # API-bol, tehat a proc dict cwd mezoje mindig None - ez itt a realis eset.
        proc = make_proc(96624, name="cc-m5stack-dialv1.1", cwd=None)
        status_files = {
            "sess-real": {"state": "waiting", "ts": 1000, "pid": 96624, "cwd": r"D:\proj\cc-m5stack-dialv1.1"}
        }
        sessions, stale_ids = build_snapshot([proc], status_files, now_ts=2000)
        self.assertEqual(
            sessions, [{"id": "sess-real", "n": "cc-m5stack-dialv1.1", "st": "waiting"}]
        )
        self.assertEqual(stale_ids, [])

    def test_pid_egyezes_felulirja_az_eltero_cwd_et(self):
        # a statusfajl pid-je A folyamate, de a cwd-je (ha lenne) B folyamatra mutatna -
        # a pid nyer, A-hoz kell parositani, nem B-hez.
        proc_a = make_proc(700, name="a-proc", cwd=None)
        proc_b = make_proc(701, name="b-proc", cwd=None)
        status_files = {
            "sess-y": {"state": "busy", "ts": 1000, "pid": 700, "cwd": r"D:\masik\mappa\amit\a_b_proc_hasznal"}
        }
        sessions, stale_ids = build_snapshot([proc_a, proc_b], status_files, now_ts=2000)
        by_id = {s["id"]: s for s in sessions}
        self.assertEqual(by_id["sess-y"], {"id": "sess-y", "n": "a-proc", "st": "busy"})
        self.assertEqual(by_id["pid701"], {"id": "pid701", "n": "b-proc", "st": "unknown"})
        self.assertEqual(stale_ids, [])

    def test_pid_nelkuli_statusfajl_meg_mindig_cwd_al_parosodik(self):
        # regi statusfajl vagy olyan hook, amely nem tudta feloldani az ospid-et:
        # a fallback ut tovabbra is mukodik.
        proc = make_proc(800, name="fallback-proc", cwd=r"D:\proj\cc-m5stack-dialv1.1")
        status_files = {
            "sess-fallback": {"state": "idle", "ts": 1000, "cwd": r"D:\proj\cc-m5stack-dialv1.1"}
        }
        # `now_ts` a `ts`-hez kozel: a parositas a targy, nem az idle-eszkalacio.
        sessions, stale_ids = build_snapshot([proc], status_files, now_ts=1010)
        self.assertEqual(
            sessions, [{"id": "sess-fallback", "n": "fallback-proc", "st": "idle"}]
        )
        self.assertEqual(stale_ids, [])

    def test_halott_pid_elavult_meg_ha_mas_elo_folyamat_ugyanazt_a_cwd_et_hasznalja_is(self):
        # ha a statusfajlnak van pid-je, de az nem el, NEM esik vissza cwd-re -
        # elavultnak szamit, mert a pid a ford megbizhato jel.
        live_other = make_proc(900, name="mas-session", cwd=r"D:\proj\kozos")
        status_files = {
            "sess-dead": {"state": "waiting", "ts": 1000, "pid": 1234, "cwd": r"D:\proj\kozos"}
        }
        sessions, stale_ids = build_snapshot([live_other], status_files, now_ts=2000)
        self.assertEqual(sessions, [{"id": "pid900", "n": "mas-session", "st": "unknown"}])
        self.assertEqual(stale_ids, ["sess-dead"])


class BuildSnapshotOrphans(unittest.TestCase):
    """Ha nincs `pid`, es a `cwd`-fallback sem talal: a session akkor sem tunhet
    el nyomtalanul (pl. egy `waiting` allapot ne vesszen el csak azert, mert a
    hook nem tudta feloldani a sajat os-lancat)."""

    def test_ttl_n_beluli_arva_sessionkent_jelenik_meg(self):
        status_files = {
            "sess-orphan": {"state": "waiting", "ts": 1000, "cwd": r"D:\proj\cc-m5stack-dialv1.1"}
        }
        sessions, stale_ids = build_snapshot([], status_files, now_ts=1000 + ORPHAN_TTL_S - 1)
        self.assertEqual(
            sessions,
            [{"id": "sess-orphan", "n": "cc-m5stack-dialv1.1", "st": "waiting"}],
        )
        self.assertEqual(stale_ids, [])

    def test_ttl_n_tuli_arva_mar_elavult(self):
        status_files = {
            "sess-orphan": {"state": "waiting", "ts": 1000, "cwd": r"D:\proj\cc-m5stack-dialv1.1"}
        }
        sessions, stale_ids = build_snapshot([], status_files, now_ts=1000 + ORPHAN_TTL_S + 1)
        self.assertEqual(sessions, [])
        self.assertEqual(stale_ids, ["sess-orphan"])

    def test_egyedi_ttl_atadhato_kulcsszo_argumentumkent(self):
        status_files = {
            "sess-orphan": {"state": "idle", "ts": 1000, "cwd": r"D:\x"}
        }
        sessions, stale_ids = build_snapshot([], status_files, now_ts=1050, orphan_ttl_s=10)
        self.assertEqual(sessions, [])
        self.assertEqual(stale_ids, ["sess-orphan"])

    def test_halott_pid_azonnal_elavult_meg_friss_ts_eseten_is__a_ttl_nem_menti_meg(self):
        status_files = {
            "sess-dead-fresh": {"state": "waiting", "ts": 999, "pid": 55555, "cwd": None}
        }
        sessions, stale_ids = build_snapshot([], status_files, now_ts=1000)
        self.assertEqual(sessions, [])
        self.assertEqual(stale_ids, ["sess-dead-fresh"])

    def test_hianyzo_ts_lejartkent_kezelt_es_nem_dobbanik(self):
        status_files = {
            "sess-no-ts": {"state": "waiting", "cwd": r"D:\proj\cc-m5stack-dialv1.1"}
        }
        sessions, stale_ids = build_snapshot([], status_files, now_ts=1000)
        self.assertEqual(sessions, [])
        self.assertEqual(stale_ids, ["sess-no-ts"])

    def test_ertelmetlen_ts_lejartkent_kezelt_es_nem_dobbanik(self):
        status_files = {
            "sess-garbage-ts": {"state": "waiting", "ts": "nem-egy-szam", "cwd": r"D:\x"}
        }
        sessions, stale_ids = build_snapshot([], status_files, now_ts=1000)
        self.assertEqual(sessions, [])
        self.assertEqual(stale_ids, ["sess-garbage-ts"])

    def test_arvanak_cwd_nelkul_is_van_hasznalhato_neve(self):
        status_files = {
            "sess-no-cwd": {"state": "busy", "ts": 999, "cwd": None}
        }
        sessions, stale_ids = build_snapshot([], status_files, now_ts=1000)
        self.assertEqual(
            sessions, [{"id": "sess-no-cwd", "n": "sess-no-cwd", "st": "busy"}]
        )
        self.assertEqual(stale_ids, [])

    def test_arvak_a_pid_parositott_sessionok_utan_kovetkeznek_stabil_sorrendben(self):
        proc = make_proc(100, name="matched", cwd=None)
        status_files = {
            "sess-matched": {"state": "idle", "ts": 999, "pid": 100, "cwd": None},
            "sess-orphan-b": {"state": "waiting", "ts": 999, "cwd": r"D:\b"},
            "sess-orphan-a": {"state": "waiting", "ts": 999, "cwd": r"D:\a"},
        }
        sessions, stale_ids = build_snapshot([proc], status_files, now_ts=1000)
        self.assertEqual(stale_ids, [])
        self.assertEqual(
            [s["id"] for s in sessions],
            ["sess-matched", "sess-orphan-a", "sess-orphan-b"],
        )


class IdleEskalacio(unittest.TestCase):
    """A regota `idle` session `waiting`-be valt (zoldrol borostyanra).

    Elesben merve: egy session 110 masodperce allt `idle`-ben, miközben
    valojaban keresre vart - a `Notification`/`idle_prompt` nem jott meg.
    """

    def test_friss_idle_marad_zold(self):
        self.assertEqual(escalate_idle("idle", 1000, 1010), "idle")

    def test_regi_idle_borostyan_lesz(self):
        self.assertEqual(escalate_idle("idle", 1000, 1000 + 60), "waiting")

    def test_pontosan_a_hataron_meg_idle(self):
        self.assertEqual(
            escalate_idle("idle", 1000, 1000 + IDLE_ESCALATE_S), "idle"
        )

    def test_a_tobbi_allapotot_nem_bantja(self):
        for state in ("busy", "waiting", "blocked", "unknown"):
            self.assertEqual(escalate_idle(state, 0, 999999), state)

    def test_ertelmezhetetlen_ts_eseten_marad(self):
        self.assertEqual(escalate_idle("idle", None, 1000), "idle")
        self.assertEqual(escalate_idle("idle", "nem szam", 1000), "idle")

    def test_sajat_hatarido_kerheto(self):
        self.assertEqual(escalate_idle("idle", 1000, 1005, escalate_s=1), "waiting")

    def test_a_pillanatkepben_is_ervenyesul(self):
        procs = [{"pid": 10, "name": "alfa", "cwd": "d:\\a",
                  "exe_path": "", "parent_name": "pwsh.exe"}]
        status = {"s1": {"state": "idle", "ts": 1000, "pid": 10, "cwd": "d:\\a"}}
        sessions, stale = build_snapshot(procs, status, 1000 + 60)
        self.assertEqual(stale, [])
        self.assertEqual(sessions[0]["st"], "waiting")

    def test_a_friss_idle_a_pillanatkepben_zold_marad(self):
        procs = [{"pid": 10, "name": "alfa", "cwd": "d:\\a",
                  "exe_path": "", "parent_name": "pwsh.exe"}]
        status = {"s1": {"state": "idle", "ts": 1000, "pid": 10, "cwd": "d:\\a"}}
        sessions, _ = build_snapshot(procs, status, 1000 + 5)
        self.assertEqual(sessions[0]["st"], "idle")


class AlugynokAllapot(unittest.TestCase):
    """Futo alugynok mellett az `idle`/`waiting` session `agents` (kek), nem sarga."""

    def info(self, state="idle", ts=1000, agents=None, agents_ts=None):
        rec = {"state": state, "ts": ts, "pid": 10, "cwd": "d:\\a"}
        if agents is not None:
            rec["agents"] = agents
        if agents_ts is not None:
            rec["agents_ts"] = agents_ts
        return rec

    def test_idle_futo_alugynokkel_agents(self):
        self.assertEqual(display_state(self.info(agents={"a": 1000}), 1010), "agents")

    def test_regi_idle_futo_alugynokkel_nem_lesz_sarga(self):
        self.assertEqual(display_state(self.info(agents={"a": 1000}), 1000 + 600), "agents")

    def test_tarolt_waiting_futo_alugynokkel_agents(self):
        info = self.info(state="waiting", agents={"a": 1000})
        self.assertEqual(display_state(info, 1010), "agents")

    def test_busy_es_blocked_nem_valtozik(self):
        for state in ("busy", "blocked", "unknown"):
            info = self.info(state=state, agents={"a": 1000})
            self.assertEqual(display_state(info, 1010), state)

    def test_elavult_alugynok_nem_szamit(self):
        info = self.info(agents={"a": 1000})
        now = 1000 + AGENT_STALE_S + IDLE_ESCALATE_S + 1
        self.assertEqual(display_state(info, now), "waiting")

    def test_eskalacio_a_lejarattol_szamit(self):
        info = self.info(ts=900, agents={"a": 1000})
        now = 1000 + AGENT_STALE_S + 1
        self.assertEqual(display_state(info, now, escalate_s=45), "idle")
        now = 1000 + AGENT_STALE_S + 46
        self.assertEqual(display_state(info, now, escalate_s=45), "waiting")
        info = self.info(ts=900, agents={"a": 1000 - 40})
        # 960 + stale lejart, 41 mp-e: meg nincs 45, tehat zold
        now = 960 + AGENT_STALE_S + 41
        self.assertEqual(display_state(info, now, escalate_s=45), "idle")

    def test_eskalacio_az_utolso_alugynok_vegetol_szamit(self):
        info = self.info(ts=1000, agents_ts=2000)
        self.assertEqual(display_state(info, 2030), "idle")
        self.assertEqual(display_state(info, 2000 + IDLE_ESCALATE_S + 1), "waiting")

    def test_serult_agents_mezo_nem_szall_el(self):
        for bad in ("x", 42, ["a"], {"a": "nem szam"}, {"a": None}):
            self.assertEqual(display_state(self.info(agents=bad), 1010), "idle")
        self.assertEqual(display_state(self.info(agents_ts="x"), 1010), "idle")

    def test_now_nelkul_a_tarolt_allapot(self):
        self.assertEqual(display_state(self.info(agents={"a": 1}), None), "idle")

    def test_a_pillanatkepben_is_ervenyesul(self):
        procs = [{"pid": 10, "name": "alfa", "cwd": "d:\\a",
                  "exe_path": "", "parent_name": "pwsh.exe"}]
        status = {"s1": self.info(agents={"a": 1000})}
        sessions, _ = build_snapshot(procs, status, 1000 + 60)
        self.assertEqual(sessions[0]["st"], "agents")


if __name__ == "__main__":
    unittest.main(verbosity=2)
