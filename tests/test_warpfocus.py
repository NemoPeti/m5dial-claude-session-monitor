"""A Warp-tab kereses tiszta logikaja (terv 4.4 `focus`).

A Windows-specifikus resz (ablakkereses, SetForegroundWindow, billentyu)
nem tesztelheto itt - ezert a keresest ugy irtuk meg, hogy a "olvasd el a
cimet" es a "lepj a kovetkezo tabra" muveletet kivulrol kapja. Igy a teljes
dontesi logika fut le a gepen, hardver es Warp nelkul.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from session_agent.warpfocus import (  # noqa: E402
    MAX_TAB_STEPS,
    active_session_id,
    FALLBACK_ENV,
    fallback_enabled,
    focus_session,
    focus_tab,
    focus_url_for_pid,
    is_focus_url,
    normalize_title,
    parse_env_block,
    pick_window_for,
    pid_from_session_id,
    title_matches,
    warp_pids,
)


class AktivSessionAzonosito(unittest.TestCase):
    """Az elotérben levo Warp-ablak cime -> melyik session tabja aktiv."""

    SESSIONS = [
        {"id": "aaa", "n": "cc-DashTiles", "st": "busy"},
        {"id": "bbb", "n": "cc-m5stack-dialv1.1", "st": "idle"},
    ]

    def test_egyezo_cim_az_azonositot_adja(self):
        self.assertEqual(
            active_session_id("✳ cc-m5stack-dialv1.1", True, self.SESSIONS), "bbb"
        )

    def test_allapotjelzo_glifa_nelkul_is_egyezik(self):
        self.assertEqual(
            active_session_id("cc-DashTiles", True, self.SESSIONS), "aaa"
        )

    def test_nem_warp_ablak_eseten_nincs_aktiv(self):
        """Mas alkalmazas van elol: a cim az ove, akkor is, ha veletlenul egyezik."""
        self.assertIsNone(
            active_session_id("cc-DashTiles", False, self.SESSIONS)
        )

    def test_nincs_egyezo_session(self):
        self.assertIsNone(active_session_id("◐ pwsh", True, self.SESSIONS))

    def test_azonos_nevu_sessionok_eseten_nincs_aktiv(self):
        """Ket azonos nevu tab kozul a cim nem mondja meg, melyik az: inkabb semmi."""
        sessions = self.SESSIONS + [{"id": "ccc", "n": "cc-DashTiles", "st": "idle"}]
        self.assertIsNone(active_session_id("◐ cc-DashTiles", True, sessions))

    def test_reszleges_egyezes_nem_szamit(self):
        sessions = [{"id": "g", "n": "gateway", "st": "idle"}]
        self.assertIsNone(active_session_id("✳ auth-gateway", True, sessions))

    def test_ures_vagy_hianyzo_cim(self):
        self.assertIsNone(active_session_id("", True, self.SESSIONS))
        self.assertIsNone(active_session_id(None, True, self.SESSIONS))

    def test_nev_nelkuli_session_nem_egyezik_az_ures_cimmel(self):
        sessions = [{"id": "x", "st": "idle"}, {"id": "y", "n": "", "st": "idle"}]
        self.assertIsNone(active_session_id("✳ ", True, sessions))

    def test_ures_session_lista(self):
        self.assertIsNone(active_session_id("alfa", True, []))
        self.assertIsNone(active_session_id("alfa", True, None))


class FakeWarp:
    """Warp-utanzat: tabok korben, `press_next` lep egyet."""

    def __init__(self, titles, start=0):
        self.titles = titles
        self.index = start
        self.presses = 0

    def read_title(self):
        return self.titles[self.index]

    def press_next(self):
        self.presses += 1
        self.index = (self.index + 1) % len(self.titles)


class NormalizeTitleTests(unittest.TestCase):
    def test_plain_title_unchanged(self):
        self.assertEqual(normalize_title("ShopKit"), "ShopKit")

    def test_strips_status_glyph_and_space(self):
        self.assertEqual(normalize_title("✳ ShopKit"), "ShopKit")

    def test_strips_unknown_glyph_rendered_as_question_mark(self):
        # A meresben ez tenylegesen igy jott vissza: "? auth-gateway"
        self.assertEqual(normalize_title("? auth-gateway"), "auth-gateway")

    def test_strips_surrounding_whitespace(self):
        self.assertEqual(normalize_title("   cc-123456  "), "cc-123456")

    def test_keeps_leading_path_like_characters(self):
        self.assertEqual(normalize_title("~/projects"), "~/projects")

    def test_none_becomes_empty(self):
        self.assertEqual(normalize_title(None), "")

    def test_only_glyphs_becomes_empty(self):
        self.assertEqual(normalize_title("✳ "), "")


class TitleMatchesTests(unittest.TestCase):
    def test_exact_match(self):
        self.assertTrue(title_matches("cc-m5stack-dialv1.1", "cc-m5stack-dialv1.1"))

    def test_match_through_status_glyph(self):
        self.assertTrue(title_matches("✳ ShopKit", "ShopKit"))

    def test_suffix_is_not_a_match(self):
        # "gateway" nem egyezhet az "auth-gateway" tabbal - kulonben egy
        # rovid nevu session idegen tabra vinne.
        self.assertFalse(title_matches("? auth-gateway", "gateway"))

    def test_prefix_is_not_a_match(self):
        self.assertFalse(title_matches("? auth-gateway", "auth"))

    def test_empty_name_never_matches(self):
        self.assertFalse(title_matches("valami", ""))
        self.assertFalse(title_matches("valami", None))

    def test_empty_title_never_matches(self):
        self.assertFalse(title_matches("", "valami"))
        self.assertFalse(title_matches(None, "valami"))


class FocusTabTests(unittest.TestCase):
    def test_already_on_target_presses_nothing(self):
        warp = FakeWarp(["✳ alfa", "beta", "gamma"], start=0)
        result, steps = focus_tab("alfa", warp.read_title, warp.press_next)
        self.assertEqual(result, "already")
        self.assertEqual(steps, 0)
        self.assertEqual(warp.presses, 0)

    def test_finds_next_tab_in_one_step(self):
        warp = FakeWarp(["alfa", "beta", "gamma"], start=0)
        result, steps = focus_tab("beta", warp.read_title, warp.press_next)
        self.assertEqual((result, steps), ("found", 1))
        self.assertEqual(warp.read_title(), "beta")

    def test_finds_last_tab_walking_forward(self):
        warp = FakeWarp(["alfa", "beta", "gamma"], start=0)
        result, steps = focus_tab("gamma", warp.read_title, warp.press_next)
        self.assertEqual((result, steps), ("found", 2))
        self.assertEqual(warp.read_title(), "gamma")

    def test_finds_target_through_status_glyph(self):
        warp = FakeWarp(["alfa", "✳ beta"], start=0)
        result, _ = focus_tab("beta", warp.read_title, warp.press_next)
        self.assertEqual(result, "found")

    def test_missing_tab_returns_to_start(self):
        warp = FakeWarp(["alfa", "beta", "gamma"], start=1)
        result, _ = focus_tab("nincs-ilyen", warp.read_title, warp.press_next)
        self.assertEqual(result, "not_found")
        self.assertEqual(warp.read_title(), "beta")

    def test_missing_tab_walks_exactly_one_lap(self):
        warp = FakeWarp(["alfa", "beta", "gamma"], start=0)
        focus_tab("nincs-ilyen", warp.read_title, warp.press_next)
        self.assertEqual(warp.presses, 3)

    def test_single_tab_not_matching_stops_immediately(self):
        warp = FakeWarp(["alfa"], start=0)
        result, _ = focus_tab("beta", warp.read_title, warp.press_next)
        self.assertEqual(result, "not_found")
        self.assertEqual(warp.presses, 1)
        self.assertEqual(warp.read_title(), "alfa")

    def test_gives_up_after_max_steps_when_titles_never_repeat(self):
        # Patologikus eset: minden lepesnel mas cim (pl. a cim epp valtozik).
        # Nem pörgunk vegtelenul.
        titles = ["t{}".format(i) for i in range(MAX_TAB_STEPS + 5)]
        warp = FakeWarp(titles, start=0)
        result, steps = focus_tab("nincs-ilyen", warp.read_title, warp.press_next)
        self.assertEqual(result, "not_found")
        self.assertEqual(steps, MAX_TAB_STEPS)

    def test_empty_target_does_nothing(self):
        warp = FakeWarp(["alfa", "beta"], start=0)
        result, steps = focus_tab("", warp.read_title, warp.press_next)
        self.assertEqual((result, steps), ("not_found", 0))
        self.assertEqual(warp.presses, 0)

    def test_duplicate_start_title_does_not_loop_forever(self):
        warp = FakeWarp(["alfa", "alfa", "beta"], start=0)
        result, _ = focus_tab("nincs-ilyen", warp.read_title, warp.press_next)
        self.assertEqual(result, "not_found")

    def test_stops_pressing_as_soon_as_found(self):
        warp = FakeWarp(["alfa", "beta", "gamma", "delta"], start=0)
        focus_tab("beta", warp.read_title, warp.press_next)
        self.assertEqual(warp.presses, 1)

    def test_read_title_failure_is_not_fatal(self):
        def read_title():
            raise OSError("ablak eltunt")

        def press_next():
            self.fail("hibas cimolvasas utan nem szabad billentyut kuldeni")

        result, steps = focus_tab("alfa", read_title, press_next)
        self.assertEqual((result, steps), ("error", 0))


class WarpPidsTests(unittest.TestCase):
    def test_finds_warp_processes(self):
        table = {
            25588: (1234, "warp.exe"),
            28728: (25588, "warp.exe"),
            27152: (25588, "pwsh.exe"),
        }
        self.assertEqual(sorted(warp_pids(table)), [25588, 28728])

    def test_ignores_cloudflare_warp_service(self):
        # Ugyanezen a gepen fut a Cloudflare VPN-kliense is - nem terminal.
        table = {900: (4, "warp-svc.exe"), 901: (4, "cloudflare-warp.exe")}
        self.assertEqual(warp_pids(table), [])

    def test_empty_table(self):
        self.assertEqual(warp_pids({}), [])

    def test_no_warp_running(self):
        self.assertEqual(warp_pids({1: (0, "pwsh.exe")}), [])


class IsFocusUrlTests(unittest.TestCase):
    """Az ertek allapotfajlbol jon - ADAT, nem parancs. Csak a warp:// sema mehet at."""

    def test_accepts_the_measured_real_url(self):
        self.assertTrue(is_focus_url("warp://session/f96028319afc4f178bebc90a25841f1b"))

    def test_accepts_uuid_with_dashes(self):
        self.assertTrue(
            is_focus_url("warp://session/550e8400-e29b-41d4-a716-446655440000")
        )

    def test_rejects_other_warp_actions(self):
        self.assertFalse(is_focus_url("warp://action/new_tab"))

    def test_rejects_foreign_scheme(self):
        self.assertFalse(is_focus_url("file:///C:/Windows/System32/calc.exe"))
        self.assertFalse(is_focus_url("http://example.com"))

    def test_rejects_command_injection_attempt(self):
        self.assertFalse(is_focus_url("warp://session/abc & calc.exe"))
        self.assertFalse(is_focus_url("warp://session/../../evil"))

    def test_rejects_empty_identifier(self):
        self.assertFalse(is_focus_url("warp://session/"))

    def test_rejects_absurdly_long_identifier(self):
        self.assertFalse(is_focus_url("warp://session/" + "a" * 65))

    def test_rejects_none_and_non_string(self):
        self.assertFalse(is_focus_url(None))
        self.assertFalse(is_focus_url(""))
        self.assertFalse(is_focus_url(12345))


class FallbackEnabledTests(unittest.TestCase):
    """A billentyus tartalek alapbol KI van kapcsolva.

    Elesben megharapott: fokusz-URL nelkuli sessionre a tartalek vegigsetalt egy
    talalomra valasztott Warp ablak tabjain.
    """

    def test_disabled_by_default(self):
        self.assertFalse(fallback_enabled({}))
        self.assertFalse(fallback_enabled(None))

    def test_enabled_by_one(self):
        self.assertTrue(fallback_enabled({FALLBACK_ENV: "1"}))

    def test_enabled_by_true_and_yes(self):
        self.assertTrue(fallback_enabled({FALLBACK_ENV: "true"}))
        self.assertTrue(fallback_enabled({FALLBACK_ENV: "IGEN"}))

    def test_empty_or_zero_stays_disabled(self):
        self.assertFalse(fallback_enabled({FALLBACK_ENV: ""}))
        self.assertFalse(fallback_enabled({FALLBACK_ENV: "0"}))
        self.assertFalse(fallback_enabled({FALLBACK_ENV: "nem"}))

    def test_whitespace_tolerated(self):
        self.assertTrue(fallback_enabled({FALLBACK_ENV: "  1  "}))


class FocusSessionUtvalasztas(unittest.TestCase):
    """Fokusz-URL nelkul, kikapcsolt tartalekkal semmihez nem nyulunk."""

    def setUp(self):
        self.logs = []

    def test_no_url_returns_no_url_without_touching_windows(self):
        result = focus_session("valami", [], log=self.logs.append,
                               focus_url=None)
        self.assertEqual(result, "no_url")

    def test_unusable_url_also_stops(self):
        result = focus_session("valami", [], log=self.logs.append,
                               focus_url="http://example.com")
        self.assertEqual(result, "no_url")
        self.assertTrue(any("nem hasznalhato" in line for line in self.logs))


class PidFromSessionIdTests(unittest.TestCase):
    """A `pid<szam>` alakot a snapshot adja a parositatlan elo folyamatoknak."""

    def test_parses_the_snapshot_format(self):
        self.assertEqual(pid_from_session_id("pid16444"), 16444)

    def test_uuid_is_not_a_pid(self):
        self.assertIsNone(pid_from_session_id("4487cb00-e929-48be-9cc6-8aa070e88e03"))

    def test_pid_prefix_without_digits(self):
        self.assertIsNone(pid_from_session_id("pid"))
        self.assertIsNone(pid_from_session_id("pidabc"))

    def test_none_and_empty(self):
        self.assertIsNone(pid_from_session_id(None))
        self.assertIsNone(pid_from_session_id(""))
        self.assertIsNone(pid_from_session_id(12345))


class ParseEnvBlockTests(unittest.TestCase):
    def test_parses_utf16_block(self):
        block = "A=1\x00WARP_FOCUS_URL=warp://session/abc\x00\x00".encode("utf-16-le")
        env = parse_env_block(block)
        self.assertEqual(env["A"], "1")
        self.assertEqual(env["WARP_FOCUS_URL"], "warp://session/abc")

    def test_value_may_contain_equals(self):
        block = "PATH=C:\\a;C:\\b\x00X=a=b\x00\x00".encode("utf-16-le")
        self.assertEqual(parse_env_block(block)["X"], "a=b")

    def test_empty_and_garbage_never_raise(self):
        self.assertEqual(parse_env_block(b""), {})
        self.assertEqual(parse_env_block(None), {})
        self.assertIsInstance(parse_env_block(b"\x01\x02\x03"), dict)

    def test_entry_without_equals_is_skipped(self):
        block = "CSAKNEV\x00A=1\x00\x00".encode("utf-16-le")
        self.assertEqual(parse_env_block(block), {"A": "1"})


class FocusUrlForPidTests(unittest.TestCase):
    """A szulolanc bejarasa - a Windows-olvasas kivulrol jon, hogy tesztelheto legyen."""

    def test_found_on_the_process_itself(self):
        envs = {100: {"WARP_FOCUS_URL": "warp://session/abc"}}
        url = focus_url_for_pid(100, parent_of=lambda p: None,
                                read_env=envs.get)
        self.assertEqual(url, "warp://session/abc")

    def test_found_on_the_parent_shell(self):
        envs = {100: {"PATH": "x"}, 200: {"WARP_FOCUS_URL": "warp://session/abc"}}
        parents = {100: 200}
        url = focus_url_for_pid(100, parent_of=parents.get, read_env=envs.get)
        self.assertEqual(url, "warp://session/abc")

    def test_gives_up_at_max_depth(self):
        envs = {}
        url = focus_url_for_pid(1, parent_of=lambda p: p + 1,
                                read_env=envs.get, max_depth=3)
        self.assertIsNone(url)

    def test_cycle_does_not_hang(self):
        parents = {1: 2, 2: 1}
        url = focus_url_for_pid(1, parent_of=parents.get, read_env=lambda p: {})
        self.assertIsNone(url)

    def test_none_pid(self):
        self.assertIsNone(focus_url_for_pid(None))

    def test_unreadable_environment_is_not_fatal(self):
        url = focus_url_for_pid(100, parent_of=lambda p: None,
                                read_env=lambda p: None)
        self.assertIsNone(url)

    def test_foreign_scheme_in_environment_is_rejected(self):
        envs = {100: {"WARP_FOCUS_URL": "http://example.com"}}
        url = focus_url_for_pid(100, parent_of=lambda p: None, read_env=envs.get)
        self.assertIsNone(url)

    def test_value_is_stripped(self):
        envs = {100: {"WARP_FOCUS_URL": "  warp://session/abc  "}}
        url = focus_url_for_pid(100, parent_of=lambda p: None, read_env=envs.get)
        self.assertEqual(url, "warp://session/abc")


class PickWindowForTests(unittest.TestCase):
    """A fokusz-URL utan melyik Warp-ablakot hozzuk elore.

    Elesben megharapott: az URL atvaltotta a tabot, de az ablak hatterben
    maradt (Windows fokusz-elozar), es ugy nezett ki, mintha nem tortent volna
    semmi. A valtas utan a cel panelt tartalmazo ablak cime a session neve.
    """

    def test_picks_the_window_whose_title_matches(self):
        windows = [(11, "? masik-projekt"), (22, "? cc-notes-md")]
        self.assertEqual(pick_window_for("cc-notes-md", windows), 22)

    def test_matches_through_status_glyph(self):
        self.assertEqual(pick_window_for("alfa", [(9, "✳ alfa")]), 9)

    def test_single_window_wins_without_a_match(self):
        self.assertEqual(pick_window_for("nincs-ilyen", [(7, "barmi")]), 7)

    def test_several_windows_without_a_match_picks_nothing(self):
        """Inkabb semmit, mint talalomra elorehozni egy idegen ablakot."""
        windows = [(11, "egyik"), (22, "masik")]
        self.assertIsNone(pick_window_for("nincs-ilyen", windows))

    def test_no_windows(self):
        self.assertIsNone(pick_window_for("alfa", []))
        self.assertIsNone(pick_window_for("alfa", None))

    def test_missing_name_still_takes_the_only_window(self):
        self.assertEqual(pick_window_for(None, [(7, "barmi")]), 7)

    def test_zero_handles_are_ignored(self):
        self.assertEqual(pick_window_for("alfa", [(0, "alfa"), (5, "alfa")]), 5)

    def test_prefix_of_another_window_is_not_a_match(self):
        windows = [(11, "? auth-gateway"), (22, "? masik")]
        self.assertIsNone(pick_window_for("gateway", windows))


if __name__ == "__main__":
    unittest.main()
