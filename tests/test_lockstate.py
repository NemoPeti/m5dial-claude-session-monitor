"""A gépzár-észlelés tiszta döntéslogikájának tesztjei — Win32 nélkül.

A tényleges mérés (`WTSQuerySessionInformationW`, `SPI_GETSCREENSAVERRUNNING`,
`GetLastInputInfo`) egy vékony, tesztelhetetlen ctypes-réteg. Minden döntés itt,
kiszámítható bemeneten dől el.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from session_agent.lockstate import (  # noqa: E402
    DEFAULT_IDLE_THRESHOLD_S,
    lock_reason,
)


class LockReasonTest(unittest.TestCase):
    def test_feloldott_session_es_semmi_mas_nincs_zar(self):
        self.assertIsNone(lock_reason(False, False, 0))

    def test_zarolt_session_zarolas(self):
        # Win+L, felhasználóváltás, RDP-lecsatlakozás: a session WTS-flagje
        # WTS_SESSIONSTATE_LOCK-ra vált.
        self.assertEqual(lock_reason(True, False, 0), "lock")

    def test_kepernyovedo_akkor_is_zar_ha_a_session_feloldott(self):
        self.assertEqual(lock_reason(False, True, 0), "saver")

    def test_a_zarolas_eros_ebb_mint_a_kepernyovedo(self):
        self.assertEqual(lock_reason(True, True, 99999), "lock")

    def test_hosszu_tetlenseg_zarnak_szamit(self):
        self.assertEqual(lock_reason(False, False, DEFAULT_IDLE_THRESHOLD_S), "idle")

    def test_a_tetlensegi_kuszob_hatara_alatt_nincs_zar(self):
        self.assertIsNone(lock_reason(False, False, DEFAULT_IDLE_THRESHOLD_S - 1))

    def test_a_tetlensegi_kuszob_atallithato(self):
        self.assertEqual(lock_reason(False, False, 61, idle_threshold_s=60), "idle")

    def test_nulla_kuszob_kikapcsolja_a_tetlenseg_figyelest(self):
        self.assertIsNone(lock_reason(False, False, 99999, idle_threshold_s=0))

    def test_none_kuszob_is_kikapcsolja(self):
        self.assertIsNone(lock_reason(False, False, 99999, idle_threshold_s=None))

    def test_ismeretlen_session_allapot_nem_zar(self):
        # A próba elbukott (None): ilyenkor NEM zárunk. Egy néma, örökre zárolt
        # Dial rosszabb és nehezebben diagnosztizálható, mint egy elmaradó zár.
        self.assertIsNone(lock_reason(None, False, 0))

    def test_ismeretlen_session_allapot_mellett_a_tobbi_jel_meg_szamit(self):
        self.assertEqual(lock_reason(None, True, 0), "saver")

    def test_hianyzo_tetlensegi_ertek_nem_szall_el(self):
        self.assertIsNone(lock_reason(False, False, None))

    def test_negativ_tetlenseg_nem_zar(self):
        self.assertIsNone(lock_reason(False, False, -5))

    def test_ertelmezhetetlen_tetlenseg_nem_szall_el(self):
        self.assertIsNone(lock_reason(False, False, "sok"))


class SessionFlagsTest(unittest.TestCase):
    """A WTS nyers `SessionFlags` ertekenek ertelmezese.

    MERVE 2026-09-11-en, Windows 11 Pro 26200-on, egy Win+L -> ujjlenyomatos
    feloldas koron: a flag a zarolas teljes ideje alatt 0 volt, feloldaskor 1.
    """

    def test_a_nulla_zarolt(self):
        from session_agent.lockstate import session_locked_from_flags
        self.assertIs(session_locked_from_flags(0), True)

    def test_az_egy_feloldott(self):
        from session_agent.lockstate import session_locked_from_flags
        self.assertIs(session_locked_from_flags(1), False)

    def test_az_ismeretlen_none(self):
        # WTS_SESSIONSTATE_UNKNOWN = 0xFFFFFFFF
        from session_agent.lockstate import session_locked_from_flags
        self.assertIsNone(session_locked_from_flags(0xFFFFFFFF))

    def test_a_hianyzo_ertek_none(self):
        from session_agent.lockstate import session_locked_from_flags
        self.assertIsNone(session_locked_from_flags(None))


if __name__ == "__main__":
    unittest.main()
