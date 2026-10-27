"""A hangszabaly (4.5) es a hangero-leptetes (4.6) tesztjei — asztali Pythonon futnak."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from session_agent.alerts import (  # noqa: E402
    ActiveFollower,
    ClickGesture,
    FOLLOW_GRACE_MS,
    DOUBLE_CLICK_MS,
    DWELL_FOCUS_MS,
    DwellTrigger,
    LONG_TOUCH_MS,
    TouchGesture,
    VOLUME_OVERLAY_MS,
    VOLUME_PENDING_MS,
    next_volume,
    should_alert,
    volume_for,
    volume_overlay_lines,
    volume_overlay_visible,
    snapshot_cfg_accepted,
)


class ShouldAlert(unittest.TestCase):
    def test_elso_pillanatkep_nema(self):
        """Csatlakozas utani elso pillanatkep soha nem szol, meg ha mar waiting is."""
        new = [{"id": "a", "n": "proj", "st": "waiting"}]
        alert, muted = should_alert(None, new, set())
        self.assertFalse(alert)
        self.assertEqual(muted, set())

    def test_atmenet_idle_bol_waitingbe_szol(self):
        prev = [{"id": "a", "n": "proj", "st": "idle"}]
        new = [{"id": "a", "n": "proj", "st": "waiting"}]
        alert, _ = should_alert(prev, new, set())
        self.assertTrue(alert)

    def test_atmenet_busybol_blockedbe_szol(self):
        prev = [{"id": "a", "n": "proj", "st": "busy"}]
        new = [{"id": "a", "n": "proj", "st": "blocked"}]
        alert, _ = should_alert(prev, new, set())
        self.assertTrue(alert)

    def test_mar_waitingben_maradva_nem_szol_ujra(self):
        prev = [{"id": "a", "n": "proj", "st": "waiting"}]
        new = [{"id": "a", "n": "proj", "st": "waiting"}]
        alert, _ = should_alert(prev, new, set())
        self.assertFalse(alert)

    def test_mar_blockedben_maradva_nem_szol_ujra(self):
        prev = [{"id": "a", "n": "proj", "st": "blocked"}]
        new = [{"id": "a", "n": "proj", "st": "blocked"}]
        alert, _ = should_alert(prev, new, set())
        self.assertFalse(alert)

    def test_uj_session_ami_mar_waitingben_jelenik_meg_szol(self):
        """Dontes: egy uj session-id, ami rogton waiting-ben tunik fel, atmenetnek
        szamit (nem volt korabban waiting), tehat szoljon."""
        prev = [{"id": "a", "n": "proj", "st": "idle"}]
        new = [
            {"id": "a", "n": "proj", "st": "idle"},
            {"id": "b", "n": "proj2", "st": "waiting"},
        ]
        alert, _ = should_alert(prev, new, set())
        self.assertTrue(alert)

    def test_uj_session_busyban_nem_szol(self):
        prev = []
        new = [{"id": "a", "n": "proj", "st": "busy"}]
        alert, _ = should_alert(prev, new, set())
        self.assertFalse(alert)

    def test_eltuno_session_nem_szol_es_nem_all_ossze(self):
        prev = [{"id": "a", "n": "proj", "st": "waiting"}]
        new = []
        alert, muted = should_alert(prev, new, set())
        self.assertFalse(alert)
        self.assertEqual(muted, set())

    def test_nemitott_session_nem_szol(self):
        prev = [{"id": "a", "n": "proj", "st": "idle"}]
        new = [{"id": "a", "n": "proj", "st": "waiting"}]
        alert, muted = should_alert(prev, new, {"a"})
        self.assertFalse(alert)
        self.assertIn("a", muted)

    def test_nemitas_allapotvaltaskor_magatol_megszunik(self):
        """A nemitas csak az adott allapotig tart: ha a session tovabblep egy
        masik allapotba, a nemites torlodik, es a KOVETKEZO waiting/blocked
        atmenet mar ujra szol."""
        muted = {"a"}
        # 1) meg mindig waiting -> nemitve marad, nincs hang
        prev = [{"id": "a", "n": "proj", "st": "waiting"}]
        new = [{"id": "a", "n": "proj", "st": "waiting"}]
        alert, muted = should_alert(prev, new, muted)
        self.assertFalse(alert)
        self.assertIn("a", muted)

        # 2) allapotvaltas idle-re -> a nemites torlodik
        prev = new
        new = [{"id": "a", "n": "proj", "st": "idle"}]
        alert, muted = should_alert(prev, new, muted)
        self.assertFalse(alert)
        self.assertNotIn("a", muted)

        # 3) ujabb atmenet waitingbe -> ujra szol
        prev = new
        new = [{"id": "a", "n": "proj", "st": "waiting"}]
        alert, muted = should_alert(prev, new, muted)
        self.assertTrue(alert)

    def test_tobb_session_egyszerre_csak_az_uj_atmenet_szamit(self):
        prev = [
            {"id": "a", "n": "p1", "st": "waiting"},
            {"id": "b", "n": "p2", "st": "busy"},
        ]
        new = [
            {"id": "a", "n": "p1", "st": "waiting"},
            {"id": "b", "n": "p2", "st": "blocked"},
        ]
        alert, _ = should_alert(prev, new, set())
        self.assertTrue(alert)

    def test_agents_allapotba_lepes_nem_szol(self):
        """Az alugynokeire varo session (kek) nem a felhasznalora var."""
        for prev_st in ("busy", "idle", "waiting"):
            prev = [{"id": "a", "n": "proj", "st": prev_st}]
            new = [{"id": "a", "n": "proj", "st": "agents"}]
            alert, _ = should_alert(prev, new, set())
            self.assertFalse(alert, prev_st)
        alert, _ = should_alert([], [{"id": "b", "n": "p", "st": "agents"}], set())
        self.assertFalse(alert)


class VolumeFor(unittest.TestCase):
    def test_fokozatok_leterkepezese(self):
        self.assertEqual(volume_for({"mute": False, "volume": 0}), 0)
        self.assertEqual(volume_for({"mute": False, "volume": 1}), 48)
        self.assertEqual(volume_for({"mute": False, "volume": 2}), 128)
        self.assertEqual(volume_for({"mute": False, "volume": 3}), 255)

    def test_mute_barmelyik_fokozaton_elnyom(self):
        for level in (0, 1, 2, 3):
            self.assertEqual(volume_for({"mute": True, "volume": level}), 0)


class NextVolume(unittest.TestCase):
    def test_korbeer_a_negy_fokozaton(self):
        self.assertEqual(next_volume(0), 1)
        self.assertEqual(next_volume(1), 2)
        self.assertEqual(next_volume(2), 3)
        self.assertEqual(next_volume(3), 0)




class Kattintasgesztus(unittest.TestCase):
    """EGY kattintas = ugras a Warp-tabra, KETTO = nemitas.

    Az egyes kattintas szuksegkeppen kesik a dupla-ablaknyit: amig az le nem
    jar, nem tudhato, hogy nem par elso fele-e.
    """

    def setUp(self):
        self.g = ClickGesture()

    def test_egy_kattintas_onmagaban_meg_nem_dont(self):
        self.assertIsNone(self.g.click())

    def test_az_ablakon_belul_nincs_single(self):
        self.g.click()
        self.assertIsNone(self.g.poll(DOUBLE_CLICK_MS))

    def test_az_ablak_lejarta_utan_single(self):
        self.g.click()
        self.assertEqual(self.g.poll(DOUBLE_CLICK_MS + 1), "single")

    def test_a_single_csak_egyszer_sul_el(self):
        self.g.click()
        self.assertEqual(self.g.poll(9000), "single")
        self.assertIsNone(self.g.poll(9000))

    def test_gyors_masodik_kattintas_dupla(self):
        self.g.click()
        self.assertEqual(self.g.click(), "double")

    def test_dupla_utan_nincs_single(self):
        self.g.click()
        self.g.click()
        self.assertIsNone(self.g.poll(9000))

    def test_lassu_masodik_kattintas_ket_kulon_egyes(self):
        self.g.click()
        self.assertEqual(self.g.poll(DOUBLE_CLICK_MS + 1), "single")
        self.g.click()
        self.assertEqual(self.g.poll(DOUBLE_CLICK_MS + 1), "single")

    def test_harom_gyors_kattintas_egy_dupla_es_egy_egyes(self):
        self.assertIsNone(self.g.click())
        self.assertEqual(self.g.click(), "double")
        self.assertIsNone(self.g.click())
        self.assertEqual(self.g.poll(9000), "single")

    def test_kattintas_nelkul_a_poll_nem_dont(self):
        self.assertIsNone(self.g.poll(9000))
        self.assertIsNone(self.g.poll(None))

    def test_hianyzo_eltelt_ido_nem_sut_el_semmit(self):
        self.g.click()
        self.assertIsNone(self.g.poll(None))

    def test_sajat_ablak_meret_hasznalhato(self):
        g = ClickGesture(window_ms=100)
        g.click()
        self.assertIsNone(g.poll(80))
        self.assertEqual(g.poll(150), "single")


class Tartozkodas(unittest.TestCase):
    """Forgatas utan DWELL_FOCUS_MS nyugalom = ugras a Warp-tabra, nyomas nelkul."""

    def setUp(self):
        self.d = DwellTrigger()

    def test_forgatas_nelkul_nem_sul_el(self):
        self.assertFalse(self.d.poll(9000))

    def test_az_ido_letelte_elott_nem_sul_el(self):
        self.d.moved()
        self.assertFalse(self.d.poll(DWELL_FOCUS_MS - 1))

    def test_az_ido_leteltekor_elsul(self):
        self.d.moved()
        self.assertTrue(self.d.poll(DWELL_FOCUS_MS))

    def test_csak_egyszer_sul_el(self):
        self.d.moved()
        self.assertTrue(self.d.poll(9000))
        self.assertFalse(self.d.poll(9000))

    def test_ujabb_forgatas_ujra_elesit(self):
        self.d.moved()
        self.d.poll(9000)
        self.d.moved()
        self.assertTrue(self.d.poll(9000))

    def test_cancel_utan_nem_sul_el(self):
        self.d.moved()
        self.d.cancel()
        self.assertFalse(self.d.poll(9000))

    def test_hianyzo_eltelt_ido_nem_sut_el_semmit(self):
        self.d.moved()
        self.assertFalse(self.d.poll(None))

    def test_sajat_ido_hasznalhato(self):
        d = DwellTrigger(dwell_ms=100)
        d.moved()
        self.assertFalse(d.poll(80))
        self.assertTrue(d.poll(100))

    def test_alapertek_ket_masodperc(self):
        self.assertEqual(DWELL_FOCUS_MS, 2000)


class AktivTabKovetese(unittest.TestCase):
    """A kivalasztas koveti a gepen aktiv Warp-tabot - de csak VALTOZASKOR.

    update(act, since_rotate_ms, shown_ids) -> index vagy None.
    """

    IDS = ["aaa", "bbb", "ccc"]

    def setUp(self):
        self.f = ActiveFollower()

    def test_elso_aktiv_tab_alkalmazodik(self):
        self.assertEqual(self.f.update("bbb", None, self.IDS), 1)

    def test_ugyanaz_az_aktiv_tab_nem_alkalmazodik_ujra(self):
        """Kulonben a felhasznalo forgatasat masodpercenkent visszaallitana."""
        self.f.update("bbb", None, self.IDS)
        self.assertIsNone(self.f.update("bbb", None, self.IDS))
        self.assertIsNone(self.f.update("bbb", 99999, self.IDS))

    def test_masik_tabra_valtas_alkalmazodik(self):
        self.f.update("bbb", None, self.IDS)
        self.assertEqual(self.f.update("ccc", None, self.IDS), 2)

    def test_hianyzo_act_nem_valtoztat(self):
        self.f.update("bbb", None, self.IDS)
        self.assertIsNone(self.f.update(None, None, self.IDS))

    def test_alt_tab_oda_vissza_ugyanarra_a_tabra_nem_valtoztat(self):
        """Hianyzo act NEM torli az emleket: a visszateres nem szamit valtozasnak."""
        self.f.update("bbb", None, self.IDS)
        self.f.update(None, None, self.IDS)
        self.f.update(None, None, self.IDS)
        self.assertIsNone(self.f.update("bbb", 99999, self.IDS))

    def test_alt_tab_utan_masik_tab_alkalmazodik(self):
        self.f.update("bbb", None, self.IDS)
        self.f.update(None, None, self.IDS)
        self.assertEqual(self.f.update("aaa", 99999, self.IDS), 0)

    def test_friss_forgatas_utan_nem_alkalmazodik(self):
        self.f.update("aaa", None, self.IDS)
        self.assertIsNone(self.f.update("ccc", FOLLOW_GRACE_MS - 1, self.IDS))

    def test_a_turelmi_idoben_eldobott_valtozas_elhasznalodik(self):
        """Nem halasztjuk: a tartozkodas ugyis a Dialhoz igazitja majd a tabot."""
        self.f.update("aaa", None, self.IDS)
        self.assertIsNone(self.f.update("ccc", 100, self.IDS))
        self.assertIsNone(self.f.update("ccc", FOLLOW_GRACE_MS + 1, self.IDS))

    def test_a_turelmi_ido_leteltevel_alkalmazodik(self):
        self.f.update("aaa", None, self.IDS)
        self.assertEqual(self.f.update("ccc", FOLLOW_GRACE_MS, self.IDS), 2)

    def test_nem_lathato_session_figyelmen_kivul_marad(self):
        """Pl. a MAX_SEGMENTS utani session: nincs szegmense, nem valaszthato."""
        self.assertIsNone(self.f.update("zzz", None, self.IDS))

    def test_nem_lathato_session_is_elhasznalodik(self):
        self.f.update("zzz", None, self.IDS)
        self.assertIsNone(self.f.update("zzz", None, self.IDS + ["zzz"]))

    def test_ures_lista(self):
        self.assertIsNone(self.f.update("aaa", None, []))

    def test_sajat_turelmi_ido_hasznalhato(self):
        f = ActiveFollower(grace_ms=100)
        self.assertIsNone(f.update("aaa", 99, self.IDS))
        self.assertEqual(f.update("bbb", 100, self.IDS), 1)

    def test_alapertek_harom_masodperc(self):
        self.assertEqual(FOLLOW_GRACE_MS, 3000)


class VolumeOverlay(unittest.TestCase):
    def test_nema(self):
        self.assertEqual(volume_overlay_lines(0), ["Nema"])

    def test_fokozatok_ket_sorban(self):
        self.assertEqual(volume_overlay_lines(1), ["Hangero", "1/3"])
        self.assertEqual(volume_overlay_lines(2), ["Hangero", "2/3"])
        self.assertEqual(volume_overlay_lines(3), ["Hangero", "3/3"])

    def test_nema_ha_nemitott_a_fokozattol_fuggetlenul(self):
        self.assertEqual(volume_overlay_lines(2, muted=True), ["Nema"])
        self.assertEqual(volume_overlay_lines(3, True), ["Nema"])

    def test_nemitas_nelkul_a_fokozat(self):
        self.assertEqual(volume_overlay_lines(2, muted=False), ["Hangero", "2/3"])

    def test_ismeretlen_fokozat_nem_szall_el(self):
        self.assertEqual(volume_overlay_lines(9), ["Hangero", "3/3"])
        self.assertEqual(volume_overlay_lines(-1), ["Nema"])

    def test_alapertek_ket_masodperc(self):
        self.assertEqual(VOLUME_OVERLAY_MS, 2000)

    def test_lathato_a_lejaratig(self):
        self.assertTrue(volume_overlay_visible(0))
        self.assertTrue(volume_overlay_visible(VOLUME_OVERLAY_MS - 1))
        self.assertFalse(volume_overlay_visible(VOLUME_OVERLAY_MS))

    def test_nincs_inditas_nem_lathato(self):
        self.assertFalse(volume_overlay_visible(None))

    def test_negativ_eltelt_ido_nem_lathato(self):
        """Ticks korbefordulas: a negativ kulonbseg nem jelenthet 'friss'-t."""
        self.assertFalse(volume_overlay_visible(-5))


class SnapshotCfgAccepted(unittest.TestCase):
    def snap(self, volume, mute=False):
        return {"volume": volume, "mute": mute}

    def test_alapertek_ot_masodperc(self):
        self.assertEqual(VOLUME_PENDING_MS, 5000)

    def test_nincs_fuggo_valtoztatas_elfogadja(self):
        self.assertTrue(snapshot_cfg_accepted(None, None, self.snap(2)))

    def test_egyezo_allapot_elfogadja(self):
        self.assertTrue(snapshot_cfg_accepted((3, False), 100, self.snap(3)))
        self.assertTrue(snapshot_cfg_accepted((2, True), 100, self.snap(2, True)))

    def test_eltero_fokozat_hatarido_alatt_elutasitja(self):
        self.assertFalse(snapshot_cfg_accepted((3, False), 100, self.snap(2)))
        self.assertFalse(
            snapshot_cfg_accepted((3, False), VOLUME_PENDING_MS - 1, self.snap(2))
        )

    def test_elavult_pillanatkep_nem_oldja_fel_a_nemitast(self):
        self.assertFalse(snapshot_cfg_accepted((2, True), 100, self.snap(2, False)))

    def test_elavult_pillanatkep_nem_nemit_vissza(self):
        self.assertFalse(snapshot_cfg_accepted((2, False), 100, self.snap(2, True)))

    def test_hianyzo_mute_mezo_hamis(self):
        self.assertTrue(snapshot_cfg_accepted((2, False), 100, {"volume": 2}))

    def test_hatarido_lejarta_elfogadja(self):
        self.assertTrue(snapshot_cfg_accepted((3, True), VOLUME_PENDING_MS, self.snap(2)))

    def test_ismeretlen_vagy_negativ_ido_elfogadja(self):
        """Ticks korbefordulas: nem ragadhatunk bele egy elavult fuggoben."""
        self.assertTrue(snapshot_cfg_accepted((3, False), None, self.snap(2)))
        self.assertTrue(snapshot_cfg_accepted((3, False), -5, self.snap(2)))


class TouchGestureTests(unittest.TestCase):
    def test_alapertek_nyolcszaz_ms(self):
        self.assertEqual(LONG_TOUCH_MS, 800)

    def test_rovid_erintes_felengedeskor_short(self):
        g = TouchGesture()
        g.down()
        self.assertIsNone(g.poll(100))
        self.assertEqual(g.up(), "short")

    def test_hosszu_erintes_tartva_long_egyszer(self):
        g = TouchGesture()
        g.down()
        self.assertIsNone(g.poll(LONG_TOUCH_MS - 1))
        self.assertEqual(g.poll(LONG_TOUCH_MS), "long")
        self.assertIsNone(g.poll(LONG_TOUCH_MS + 500))

    def test_long_utan_felengedes_nem_short(self):
        g = TouchGesture()
        g.down()
        g.poll(LONG_TOUCH_MS)
        self.assertIsNone(g.up())

    def test_up_down_nelkul_semmi(self):
        g = TouchGesture()
        self.assertIsNone(g.up())
        self.assertIsNone(g.poll(5000))

    def test_felengedes_utan_nem_pollol(self):
        g = TouchGesture()
        g.down()
        g.up()
        self.assertIsNone(g.poll(5000))

    def test_ujabb_erintes_ujra_lehet_long(self):
        g = TouchGesture()
        g.down()
        g.poll(LONG_TOUCH_MS)
        g.up()
        g.down()
        self.assertEqual(g.poll(LONG_TOUCH_MS), "long")

    def test_none_vagy_negativ_ido_nem_lo(self):
        g = TouchGesture()
        g.down()
        self.assertIsNone(g.poll(None))
        self.assertIsNone(g.poll(-10))
        self.assertEqual(g.up(), "short")

    def test_cancel_eldobja_a_gesztust(self):
        g = TouchGesture()
        g.down()
        g.cancel()
        self.assertIsNone(g.up())
        self.assertIsNone(g.poll(5000))


if __name__ == "__main__":
    unittest.main(verbosity=2)
