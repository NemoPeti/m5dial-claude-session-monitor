"""A launcher tiszta logikájának tesztjei — asztali Pythonon futnak, hardver nélkül."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from applist import move_selection, visible_window  # noqa: E402


class MoveSelection(unittest.TestCase):
    def test_lep_elore_es_hatra(self):
        self.assertEqual(move_selection(0, 1, 3), 1)
        self.assertEqual(move_selection(2, -1, 3), 1)

    def test_korbeer_mindket_iranyban(self):
        self.assertEqual(move_selection(2, 1, 3), 0, "a vegerol az elejere kell ugrania")
        self.assertEqual(move_selection(0, -1, 3), 2, "az elejerol a vegere kell ugrania")

    def test_nagy_delta_tobbszor_korbeer(self):
        self.assertEqual(move_selection(0, 7, 3), 1)
        self.assertEqual(move_selection(0, -7, 3), 2)

    def test_ures_lista_nem_szall_el(self):
        self.assertEqual(move_selection(0, 1, 0), 0)
        self.assertEqual(move_selection(0, -5, 0), 0)

    def test_egyelemu_lista_helyben_marad(self):
        self.assertEqual(move_selection(0, 1, 1), 0)
        self.assertEqual(move_selection(0, -3, 1), 0)

    def test_nulla_delta_nem_mozdit(self):
        self.assertEqual(move_selection(1, 0, 3), 1)


class VisibleWindow(unittest.TestCase):
    def test_rovid_lista_teljesen_latszik(self):
        self.assertEqual(visible_window(0, 3, 5), (0, 3))
        self.assertEqual(visible_window(2, 3, 5), (0, 3))

    def test_hosszu_lista_gorget_a_kivalasztottal(self):
        # 10 elem, 5 sor: a 0. elemnel az elso ablak latszik
        self.assertEqual(visible_window(0, 10, 5), (0, 5))
        # a 7. elemnel mar gorgetni kell, de az ablak a listan belul marad
        start, end = visible_window(7, 10, 5)
        self.assertEqual(end - start, 5)
        self.assertTrue(start <= 7 < end, "a kivalasztott elemnek latszania kell")

    def test_a_vegen_nem_log_tul(self):
        start, end = visible_window(9, 10, 5)
        self.assertEqual((start, end), (5, 10))

    def test_ures_lista(self):
        self.assertEqual(visible_window(0, 0, 5), (0, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
