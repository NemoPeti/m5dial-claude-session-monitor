"""Az óra/időjárás panel tiszta logikájának tesztjei — hardver nélkül.

A panel a Dialon fut, de minden döntése kiszámítható bemenetből: ezért itt
tesztelhető, asztali Pythonon.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from session_agent.panel import (  # noqa: E402
    DAY_NAMES,
    anyone_waiting,
    format_clock,
    format_date,
    format_summary,
    format_weather,
    summarize,
    summary_lines,
    to_device_epoch,
    view_for,
)


def s(sid, state):
    return {"id": sid, "n": sid, "st": state}


class AnyoneWaiting(unittest.TestCase):
    def test_waiting_es_blocked_szamit(self):
        self.assertTrue(anyone_waiting([s("a", "idle"), s("b", "waiting")]))
        self.assertTrue(anyone_waiting([s("a", "blocked")]))

    def test_a_tobbi_allapot_nem_szamit(self):
        self.assertFalse(anyone_waiting([s("a", "busy"), s("b", "idle")]))
        self.assertFalse(anyone_waiting([s("a", "unknown")]))

    def test_ures_lista(self):
        self.assertFalse(anyone_waiting([]))
        self.assertFalse(anyone_waiting(None))

    def test_hianyzo_allapot_nem_szall_el(self):
        self.assertFalse(anyone_waiting([{"id": "a"}]))


class Summarize(unittest.TestCase):
    def test_megszamolja_az_allapotokat(self):
        sessions = [s("a", "busy"), s("b", "busy"), s("c", "waiting"), s("d", "idle")]
        self.assertEqual(
            summarize(sessions), {"total": 4, "busy": 2, "waiting": 1, "blocked": 0}
        )

    def test_blocked_kulon_szamlalodik(self):
        self.assertEqual(
            summarize([s("a", "blocked")]),
            {"total": 1, "busy": 0, "waiting": 0, "blocked": 1},
        )

    def test_ures_lista(self):
        self.assertEqual(
            summarize([]), {"total": 0, "busy": 0, "waiting": 0, "blocked": 0}
        )

    def test_az_alugynokeire_varo_session_dolgozik(self):
        sessions = [s("a", "agents"), s("b", "busy"), s("c", "idle")]
        self.assertEqual(
            summarize(sessions), {"total": 3, "busy": 2, "waiting": 0, "blocked": 0}
        )
        self.assertEqual(format_summary(sessions), "3 session, 2 dolgozik, 0 var")

    def test_agents_nem_var_a_felhasznalora(self):
        self.assertFalse(anyone_waiting([s("a", "agents")]))


class FormatSummary(unittest.TestCase):
    def test_szokasos_sor(self):
        sessions = [s("a", "busy"), s("b", "busy"), s("c", "idle")]
        self.assertEqual(format_summary(sessions), "3 session, 2 dolgozik, 0 var")

    def test_a_blocked_beleszamit_a_varokba(self):
        sessions = [s("a", "waiting"), s("b", "blocked")]
        self.assertEqual(format_summary(sessions), "2 session, 0 dolgozik, 2 var")

    def test_ures(self):
        self.assertEqual(format_summary([]), "nincs session")

    def test_csak_ascii(self):
        sessions = [s("a", "busy")]
        self.assertTrue(
            format_summary(sessions).isascii(),
            "a kijelzo betukeszlete ekezet nelkuli - lasd a modul-docstringet",
        )


class SummaryLines(unittest.TestCase):
    """Ket sorra tordelve, mert egy sorban belelogna a gyuruTbe.

    A kerek kijelzon a hasznalhato szelesseg lefele egyre kisebb: a gyuru belso
    sugara 90 px, tehat a kozepponttol 52 px-re mar csak ~146 px all
    rendelkezesre. Az egysoros "8 session, 3 dolgozik, 0 var" ennel szelesebb.
    """

    def test_ket_sorra_bomlik(self):
        sessions = [s("a", "busy"), s("b", "busy"), s("c", "idle")]
        self.assertEqual(summary_lines(sessions), ["3 session", "2 dolgozik, 0 var"])

    def test_a_blocked_beleszamit_a_varokba(self):
        sessions = [s("a", "waiting"), s("b", "blocked")]
        self.assertEqual(summary_lines(sessions), ["2 session", "0 dolgozik, 2 var"])

    def test_ures_egy_sor(self):
        self.assertEqual(summary_lines([]), ["nincs session"])

    def test_egyik_sor_sem_tul_szeles(self):
        # 12-es betukeszlet ~7 px/karakter; 152 px a szuk hely a also sornal.
        sessions = [s(str(i), "busy") for i in range(12)]
        for line in summary_lines(sessions):
            self.assertLessEqual(len(line) * 7, 152, "belelogna a gyuruTbe: " + line)

    def test_minden_sor_ascii(self):
        for line in summary_lines([s("a", "busy")]):
            self.assertTrue(line.isascii())


class FormatClock(unittest.TestCase):
    def test_ora_perc_ket_jegyre_toltve(self):
        self.assertEqual(format_clock((2026, 9, 10, 9, 5, 0, 2, 253)), "09:05")

    def test_delutan(self):
        self.assertEqual(format_clock((2026, 9, 10, 14, 42, 0, 2, 253)), "14:42")

    def test_ejfel(self):
        self.assertEqual(format_clock((2026, 9, 10, 0, 0, 0, 2, 253)), "00:00")

    def test_hibas_bemenet_nem_szall_el(self):
        self.assertEqual(format_clock(None), "--:--")
        self.assertEqual(format_clock(()), "--:--")


class FormatDate(unittest.TestCase):
    def test_datum_es_napnev(self):
        # 2026-09-10 szerda; a MicroPython idotupliben a hetfo = 0.
        self.assertEqual(format_date((2026, 9, 10, 9, 5, 0, 2, 253)), "09-10 szerda")

    def test_minden_napnev_ascii(self):
        for name in DAY_NAMES:
            self.assertTrue(name.isascii(), "ekezet nelkuli napnev kell: " + name)

    def test_hibas_bemenet_nem_szall_el(self):
        self.assertEqual(format_date(None), "")

    def test_ervenytelen_napindex_nem_szall_el(self):
        self.assertEqual(format_date((2026, 9, 10, 9, 5, 0, 99, 253)), "09-10")


class FormatWeather(unittest.TestCase):
    def test_homerseklet_es_felirat(self):
        self.assertEqual(format_weather({"t": 12, "c": "felhos"}), "12C felhos")

    def test_negativ_homerseklet(self):
        self.assertEqual(format_weather({"t": -3, "c": "havas"}), "-3C havas")

    def test_hianyzo_idojaras_ures_sor(self):
        self.assertEqual(format_weather(None), "")
        self.assertEqual(format_weather({}), "")

    def test_hianyzo_felirat_csak_homerseklet(self):
        self.assertEqual(format_weather({"t": 20}), "20C")


class ToDeviceEpoch(unittest.TestCase):
    """Ezen a firmware-en az idoszamitas 1970-tol megy - MEGMERVE, nem feltetelezve.

    A MicroPython ESP32-portja hagyomanyosan 2000-01-01-tol szamol, ezert
    kezenfekvo lenne 946684800-at levonni. Az eszkoz viszont ezt mondta:
    `time.localtime(0) == (1970, 1, 1, 0, 0, 0, 3, 1)`.
    """

    def test_ezen_a_firmwareen_nincs_atszamitas(self):
        self.assertEqual(to_device_epoch(1789026300), 1789026300)

    def test_masik_firmwarehez_atallithato(self):
        self.assertEqual(to_device_epoch(1789026300, offset=946684800),
                         1789026300 - 946684800)

    def test_hibas_bemenet_nem_szall_el(self):
        self.assertIsNone(to_device_epoch(None))
        self.assertIsNone(to_device_epoch("delben"))


class ViewFor(unittest.TestCase):
    """A harom nezet kozotti valtas - ez a panel egyetlen igazi dontese."""

    def test_kapcsolat_nelkul_mindig_offline(self):
        self.assertEqual(
            view_for([s("a", "waiting")], 10000, 9000, link_up=False), "offline"
        )

    def test_ha_valaki_var_a_session_nezet(self):
        self.assertEqual(
            view_for([s("a", "waiting")], 10000, 0, link_up=True), "sessions"
        )

    def test_ha_senki_nem_var_a_panel(self):
        self.assertEqual(view_for([s("a", "busy")], 10000, 0, link_up=True), "panel")

    def test_friss_bevitel_utan_meg_a_session_nezet_marad(self):
        # 2 mp-e nyult hozza: az 5 mp-es turelmi idon belul vagyunk.
        self.assertEqual(
            view_for([s("a", "busy")], 10000, 8000, link_up=True), "sessions"
        )

    def test_a_turelmi_ido_utan_visszaall_a_panel(self):
        self.assertEqual(
            view_for([s("a", "busy")], 10000, 4000, link_up=True), "panel"
        )

    def test_a_turelmi_ido_hatara(self):
        self.assertEqual(
            view_for([s("a", "busy")], 10000, 5000, link_up=True), "panel",
            "pontosan 5000 ms mar lejart",
        )

    def test_ures_session_lista_eseten_is_panel(self):
        self.assertEqual(view_for([], 10000, 0, link_up=True), "panel")

    def test_a_turelmi_ido_atallithato(self):
        self.assertEqual(
            view_for([s("a", "busy")], 10000, 8000, link_up=True, grace_ms=1000),
            "panel",
        )

    # --- zarolt gep --------------------------------------------------------

    def test_zarolt_gepen_a_locked_nezet(self):
        self.assertEqual(
            view_for([s("a", "busy")], 10000, 0, link_up=True, locked=True), "locked"
        )

    def test_a_zarolas_eros_ebb_mint_a_varakozo_session(self):
        # Zarolt gepen semmilyen munka-informacio nem lathato, meg akkor sem,
        # ha valaki epp rad var.
        self.assertEqual(
            view_for([s("a", "waiting")], 10000, 0, link_up=True, locked=True),
            "locked",
        )

    def test_a_zarolas_eros_ebb_mint_a_turelmi_ido(self):
        self.assertEqual(
            view_for([s("a", "busy")], 10000, 9000, link_up=True, locked=True),
            "locked",
        )

    def test_kapcsolat_nelkul_nem_bizunk_a_regi_zar_jelzesben(self):
        # Az `lk` mezo az ugynoktol jon; ha nincs kapcsolat, elavult. Az offline
        # nezet ugyis csak orat es idojarast mutat, tehat nem szivarog ki semmi.
        self.assertEqual(
            view_for([s("a", "busy")], 10000, 0, link_up=False, locked=True),
            "offline",
        )

    def test_feloldas_utan_visszaall_a_panel(self):
        self.assertEqual(
            view_for([s("a", "busy")], 10000, 0, link_up=True, locked=False), "panel"
        )


from session_agent.panel import (  # noqa: E402
    LABEL_MAX,
    CENTER_NAME_MAX,
    CLOCK_SYNC_INTERVAL_MS,
    center_name,
    short_label,
    short_labels,
    should_sync_clock,
)


class ShortLabel(unittest.TestCase):
    """A gyuru-feliratok: melyik szegmens melyik session."""

    def test_a_cc_prefixet_levagja(self):
        self.assertEqual(short_label("cc-notes-md"), "note")

    def test_a_prefix_levagasa_kis_nagybetutol_fuggetlen(self):
        self.assertEqual(short_label("CC-notes-md"), "note")

    def test_valodi_projektnevek(self):
        self.assertEqual(short_label("cc-m5stack-dialv1.1"), "m5st")
        self.assertEqual(short_label("cc-sync-allrepo-check"), "sync")
        self.assertEqual(short_label("cc-123456"), "1234")
        self.assertEqual(short_label("cc-invoice"), "invo")
        self.assertEqual(short_label("cc-deploy-pin"), "depl")

    def test_prefix_nelkuli_nevek(self):
        self.assertEqual(short_label("ShopKit"), "Shop")
        self.assertEqual(short_label("GIT_demo"), "GIT")
        self.assertEqual(short_label("cdemo"), "cdem")

    def test_rovid_nev_valtozatlan(self):
        self.assertEqual(short_label("api"), "api")

    def test_ures_es_none(self):
        self.assertEqual(short_label(""), "")
        self.assertEqual(short_label(None), "")

    def test_csak_prefix(self):
        self.assertEqual(short_label("cc-"), "")

    def test_hosszabb_hatar_kerheto(self):
        self.assertEqual(short_label("cc-notes-md", max_len=6), "notes")

    def test_soha_nem_hosszabb_a_hatarnal(self):
        for name in ("cc-m5stack-dialv1.1", "ShopKit", "x" * 40):
            self.assertLessEqual(len(short_label(name)), LABEL_MAX)


class ShortLabels(unittest.TestCase):
    def test_a_valodi_session_keszlet(self):
        names = [
            "cc-m5stack-dialv1.1", "cc-notes-md", "cc-sync-allrepo-check",
            "cc-123456", "cc-invoice", "cc-deploy-pin",
            "ShopKit", "GIT_demo", "cdemo",
        ]
        self.assertEqual(
            short_labels(names),
            ["m5st", "note", "sync", "1234", "invo", "depl",
             "Shop", "GIT", "cdem"],
        )

    def test_utkozesnel_a_masodik_tag_kezdobetuje_dont(self):
        labels = short_labels(["cc-notes-md", "cc-notes-web"])
        self.assertEqual(labels, ["note", "notw"])
        self.assertEqual(len(set(labels)), 2)

    def test_teljes_utkozesnel_sorszam(self):
        labels = short_labels(["proj", "proj", "proj"])
        self.assertEqual(len(set(labels)), 3)

    def test_mindig_kulonbozoek(self):
        names = ["cc-alfa-egy", "cc-alfa-ketto", "cc-alfa-harom", "cc-alfa"]
        self.assertEqual(len(set(short_labels(names))), len(names))

    def test_ures_lista(self):
        self.assertEqual(short_labels([]), [])
        self.assertEqual(short_labels(None), [])

    def test_nevtelen_session_kap_jelet(self):
        self.assertEqual(short_labels([""]), ["?"])

    def test_determinisztikus(self):
        names = ["cc-notes-md", "cc-notes-web", "cc-notes-md"]
        self.assertEqual(short_labels(names), short_labels(names))


class OraSzinkron(unittest.TestCase):
    """Idozitett orasszinkron a gep idejebol.

    Ket elesben mert hiba vezetett ide: az RTC eloszor CSAK az elso
    kapcsolatfelvetelkor allt be (16 percet kesett), az elso javitas pedig a ket
    idot hasonlitotta ossze, es MINDEN korben ujraallitotta - az eszkoz
    `time.time()`-ja mas viszonyitasi rendszerben van, mint amit kuldunk.
    Ezert itt nincs osszehasonlitas, csak idozites.
    """

    def test_elso_alkalommal_mindig_szinkronizal(self):
        self.assertTrue(should_sync_clock(False, None))
        self.assertTrue(should_sync_clock(False, 0))

    def test_beallitott_ora_nem_all_ujra_azonnal(self):
        self.assertFalse(should_sync_clock(True, 0))
        self.assertFalse(should_sync_clock(True, 1000))

    def test_az_intervallum_letelte_utan_ujra(self):
        self.assertTrue(should_sync_clock(True, CLOCK_SYNC_INTERVAL_MS))
        self.assertTrue(should_sync_clock(True, CLOCK_SYNC_INTERVAL_MS + 1))

    def test_kozvetlenul_a_hatar_elott_meg_nem(self):
        self.assertFalse(should_sync_clock(True, CLOCK_SYNC_INTERVAL_MS - 1))

    def test_hianyzo_eltelt_ido_eseten_nem_nyulunk_hozza(self):
        self.assertFalse(should_sync_clock(True, None))

    def test_ertelmezhetetlen_eltelt_ido_nem_szall_el(self):
        self.assertFalse(should_sync_clock(True, "nem szam"))

    def test_sajat_intervallum_kerheto(self):
        self.assertTrue(should_sync_clock(True, 100, interval_ms=50))
        self.assertFalse(should_sync_clock(True, 40, interval_ms=50))


class KozepsoNev(unittest.TestCase):
    """A kozepen mutatott nev hossza.

    A fotokon latszott: a hosszabb nev levagta a bal es jobb oldali
    gyuru-feliratot (`LL`, `er`), mert azok ugyanabban a vizszintes savban ulnek.
    """

    def test_a_cc_prefixet_levagja(self):
        self.assertEqual(center_name("cc-notes-md"), "notes-md")

    def test_rovid_nev_valtozatlan(self):
        self.assertEqual(center_name("GIT_demo"), "GIT_demo")

    def test_a_hatarnal_pontosan_nem_vag(self):
        self.assertEqual(len(center_name("x" * CENTER_NAME_MAX)), CENTER_NAME_MAX)
        self.assertEqual(center_name("x" * CENTER_NAME_MAX), "x" * CENTER_NAME_MAX)

    def test_hosszu_nevet_ponttal_zar(self):
        out = center_name("cc-m5stack-dialv1.1")
        self.assertEqual(out, "m5stack-dia.")
        self.assertEqual(len(out), CENTER_NAME_MAX)

    def test_soha_nem_hosszabb_a_hatarnal(self):
        for name in ("cc-sync-allrepo-check", "ShopKit", "x" * 60):
            self.assertLessEqual(len(center_name(name)), CENTER_NAME_MAX)

    def test_ures_es_none(self):
        self.assertEqual(center_name(""), "")
        self.assertEqual(center_name(None), "")

    def test_sajat_hatar_kerheto(self):
        self.assertEqual(center_name("cc-notes-md", max_len=6), "notes.")

    def test_a_prefix_levagasa_kis_nagybetutol_fuggetlen(self):
        self.assertEqual(center_name("CC-notes-md"), "notes-md")


if __name__ == "__main__":
    unittest.main()
