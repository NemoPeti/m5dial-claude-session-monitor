"""A hook-szkript vegpontol vegpontig: valodi folyamatkent, ideiglenes allapotmappaval."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HOOK = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "tools", "hooks", "session_status_hook.py"
)


def run_hook(status_dir, payload):
    env = dict(os.environ)
    env["CLAUDE_SESSION_STATUS_DIR"] = status_dir
    env.pop("WARP_FOCUS_URL", None)
    result = subprocess.run(
        [sys.executable, HOOK],
        input=json.dumps(payload),
        text=True,
        env=env,
        capture_output=True,
        timeout=30,
    )
    return result.returncode


def event(name, **extra):
    base = {"hook_event_name": name, "session_id": "e2e-sess", "cwd": "D:/x"}
    base.update(extra)
    return base


class HookSzkriptAlugynokkel(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.path = os.path.join(self.dir, "e2e-sess.json")

    def tearDown(self):
        self._tmp.cleanup()

    def read(self):
        with open(self.path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def test_start_majd_stop_a_fo_allapotot_nem_irja_felul(self):
        self.assertEqual(run_hook(self.dir, event("Stop")), 0)
        before = self.read()
        self.assertEqual(before["state"], "idle")

        self.assertEqual(
            run_hook(self.dir, event("SubagentStart", agent_id="ag-1", agent_type="Explore")), 0
        )
        rec = self.read()
        self.assertEqual(rec["state"], "idle")
        self.assertEqual(rec["ts"], before["ts"])
        self.assertEqual(list(rec["agents"]), ["ag-1"])

        self.assertEqual(
            run_hook(self.dir, event("SubagentStop", agent_id="ag-1", agent_type="Explore")), 0
        )
        rec = self.read()
        self.assertEqual(rec["state"], "idle")
        self.assertNotIn("agents", rec)
        # Az agents_ts csak akkor kerul a fajlba, ha frissebb a ts-nel - egy
        # masodpercen belul lefuto tesztben lehet, hogy egyenlo.
        self.assertGreaterEqual(rec.get("agents_ts", rec["ts"]), before["ts"])

    def test_alugynok_stopja_nem_ir_fajlt(self):
        self.assertEqual(run_hook(self.dir, event("Stop", agent_id="ag-1")), 0)
        self.assertFalse(os.path.exists(self.path))


if __name__ == "__main__":
    unittest.main()
