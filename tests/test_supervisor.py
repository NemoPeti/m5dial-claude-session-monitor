"""Az ugynok onfelugyeletenek (terv 3, egypeldanyos zar + tetlensegi kilepes)
tesztjei. Mindig tempfile-t hasznalnak, soha nem indit/olt valodi folyamatot -
az elettartamot a beinjektalt `is_alive` szimulalja."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from session_agent.supervisor import (  # noqa: E402
    IDLE_EXIT_S,
    acquire_lock,
    read_lock,
    release_lock,
    should_exit_idle,
)


class SupervisorTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmpdir.name, "agent.lock")

    def tearDown(self):
        self.tmpdir.cleanup()


def alive_none(pid):
    return False


def alive_all(pid):
    return True


class ShouldExitIdle(unittest.TestCase):
    def test_sessionok_mellett_nincs_tetlenseg(self):
        exitf, idle_since = should_exit_idle(3, None, 1000)
        self.assertFalse(exitf)
        self.assertIsNone(idle_since)

    def test_nullara_esve_indul_a_tetlensegi_ora(self):
        exitf, idle_since = should_exit_idle(0, None, 1000)
        self.assertFalse(exitf)
        self.assertEqual(idle_since, 1000)

    def test_az_ora_nem_indul_ujra_minden_korben(self):
        exitf, idle_since = should_exit_idle(0, 1000, 1500, idle_exit_s=IDLE_EXIT_S)
        self.assertFalse(exitf)
        self.assertEqual(idle_since, 1000, "az idle_since nem valtozhat kozbulso korokben")

    def test_idokorlat_eleresekor_kilep(self):
        exitf, idle_since = should_exit_idle(0, 1000, 1000 + IDLE_EXIT_S)
        self.assertTrue(exitf)
        self.assertEqual(idle_since, 1000)

    def test_idokorlat_alatt_meg_nem_lep_ki(self):
        exitf, idle_since = should_exit_idle(0, 1000, 1000 + IDLE_EXIT_S - 1)
        self.assertFalse(exitf)

    def test_ujra_megjeleno_session_torli_a_szamlalot(self):
        exitf, idle_since = should_exit_idle(1, 1000, 1500)
        self.assertFalse(exitf)
        self.assertIsNone(idle_since)

    def test_kesobbi_tetlenseg_uj_szamlalast_kezd(self):
        # elso tetlen szakasz kezdodik
        _, idle_since = should_exit_idle(0, None, 1000)
        self.assertEqual(idle_since, 1000)
        # session visszater, a szamlalo torlodik
        _, idle_since = should_exit_idle(2, idle_since, 1050)
        self.assertIsNone(idle_since)
        # ujabb tetlen szakasz - uj kezdopont, nem a regi 1000
        exitf, idle_since = should_exit_idle(0, idle_since, 2000)
        self.assertFalse(exitf)
        self.assertEqual(idle_since, 2000)

    def test_ervenytelen_idle_since_nem_szall_el(self):
        exitf, idle_since = should_exit_idle(0, "nem-szam", 1000)
        self.assertFalse(exitf)
        self.assertEqual(idle_since, 1000)

    def test_none_session_count_tetlenkent_kezelt(self):
        exitf, idle_since = should_exit_idle(None, None, 1000)
        self.assertFalse(exitf)
        self.assertEqual(idle_since, 1000)

    def test_negativ_session_count_tetlenkent_kezelt(self):
        exitf, idle_since = should_exit_idle(-5, None, 1000)
        self.assertFalse(exitf)
        self.assertEqual(idle_since, 1000)


class AcquireLock(SupervisorTestCase):
    def test_ures_helyen_megszerezzuk_a_zarat(self):
        got = acquire_lock(self.path, 111, alive_none)
        self.assertTrue(got)
        self.assertEqual(read_lock(self.path), 111)

    def test_elo_tulajdonos_eseten_nem_kapjuk_meg(self):
        acquire_lock(self.path, 111, alive_none)
        got = acquire_lock(self.path, 222, alive_all)
        self.assertFalse(got)
        self.assertEqual(read_lock(self.path), 111)

    def test_holt_tulajdonos_zarjat_atvesszuk(self):
        acquire_lock(self.path, 111, alive_none)
        got = acquire_lock(self.path, 222, alive_none)
        self.assertTrue(got)
        self.assertEqual(read_lock(self.path), 222)

    def test_serult_zarfajlt_atvesszuk(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("nem-szam-szemet")
        got = acquire_lock(self.path, 222, alive_all)
        self.assertTrue(got)
        self.assertEqual(read_lock(self.path), 222)

    def test_ures_zarfajlt_atvesszuk(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("")
        got = acquire_lock(self.path, 222, alive_all)
        self.assertTrue(got)
        self.assertEqual(read_lock(self.path), 222)

    def test_verseny_szimulacio_masodik_veszit(self):
        # Elozetesen letrehozott fajl szimulalja, hogy egy masik folyamat
        # nyert a versenyben - az atomi O_CREAT|O_EXCL miatt a masodik
        # hivo nem irhatja felul, csak ha az elso holt.
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("111")
        got = acquire_lock(self.path, 222, alive_all)
        self.assertFalse(got)
        self.assertEqual(read_lock(self.path), 111)


class ReleaseLock(SupervisorTestCase):
    def test_sajat_zarat_torli(self):
        acquire_lock(self.path, 111, alive_none)
        release_lock(self.path, 111)
        self.assertFalse(os.path.exists(self.path))

    def test_idegen_zarat_nem_torli(self):
        acquire_lock(self.path, 111, alive_none)
        release_lock(self.path, 222)
        self.assertTrue(os.path.exists(self.path))
        self.assertEqual(read_lock(self.path), 111)

    def test_hianyzo_fajlon_nem_hibazik(self):
        release_lock(self.path, 111)  # nem szabad kivetelt dobnia
        self.assertFalse(os.path.exists(self.path))


class ReadLock(SupervisorTestCase):
    def test_hianyzo_fajl_none(self):
        self.assertIsNone(read_lock(self.path))

    def test_ervenyes_pid_visszaadva(self):
        acquire_lock(self.path, 333, alive_none)
        self.assertEqual(read_lock(self.path), 333)

    def test_serult_tartalom_none(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("abc")
        self.assertIsNone(read_lock(self.path))


if __name__ == "__main__":
    unittest.main(verbosity=2)
