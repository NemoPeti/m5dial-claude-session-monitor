# SPDX-License-Identifier: MIT
"""A hook tiszta logikaja: melyik esemenybol milyen allapot lesz (spec 4.2).

Kulon modul, hogy asztali Pythonon tesztelheto legyen - a hook-szkript maga
(session_status_hook.py) csak beolvassa a stdin-t, meghivja ezt, es ir egy
fajlt. Ott nincs mit tesztelni; itt van.

A mezonevek igazolva vannak: a telepitett Claude Agent SDK
`claude_agent_sdk/types.py` `BaseHookInput`/`NotificationHookInput` tipusai, es a
`warp` plugin szkriptjei pontosan ezeket olvassak ki.
"""

# A spec 4.2 tablazata. A Notification kulon jar, mert ott a notification_type
# donti el, hogy tenyleg a felhasznalora var-e a session.
DELETE = "__delete__"

_EVENT_STATES = {
    "PermissionRequest": "blocked",
    "UserPromptSubmit": "busy",
    "Stop": "idle",
    "SessionEnd": DELETE,
}

# A Notification esemeny csak ezzel a tipussal jelent "rad var" allapotot.
# Igazolva: a warp plugin on-notification.sh-ja a .notification_type mezot
# olvassa, es a hookja kizarolag erre a matcherre van bekotve.
IDLE_PROMPT = "idle_prompt"


def state_for(payload):
    """A hook payloadjabol allapot, vagy None, ha ez az esemeny nem erdekes.

    A `DELETE` visszateresi ertek azt jelenti, hogy az allapotfajlt torolni
    kell (a session veget ert), nem azt, hogy allapotot kell irni.
    """
    if not isinstance(payload, dict):
        return None

    event = payload.get("hook_event_name")
    if event == "Stop" and agent_id_of(payload) is not None:
        # Az `agent_id` csak alugynokon belul fut hook-esemenyen van (hooks.md).
        # Egy alugynok vege a SubagentStop dolga; a szulo kore ettol meg nem
        # ert veget, tehat nem lehet `idle`. A PermissionRequest viszont
        # alugynokbol is a felhasznalot kivanja, az marad `blocked`. A
        # Notification/idle_prompt a felhasznalo bevitelere var, barhonnan
        # jon is - az is valtozatlan.
        return None
    if event == "Notification":
        # Ismeretlen notification_type-ra szandekosan NEM allitunk allapotot:
        # az SDK sima str-kent tipizalja a mezot, tehat johet mas ertek is, es
        # abbol hamis "rad var" jelzes lenne.
        if payload.get("notification_type") == IDLE_PROMPT:
            return "waiting"
        return None

    return _EVENT_STATES.get(event)


# --- Alugynok-kovetes ------------------------------------------------------------
#
# Ha egy session alugynokokre (foleg hatter-alugynokokre) var, a kore veget er,
# jon a `Stop` -> `idle` -> 45 mp utan sarga "rad var", pedig nem a
# felhasznalora var. Ezert a rekord a futo alugynokoket is tarolja:
#
#     "agents":    {agent_id: inditas_ts, ...}  - csak ha van futo alugynok
#     "agents_ts": az utolso alugynok vegenek (vagy lejaratanak) ideje - csak
#                  ha a rekord `ts`-enel frissebb, mert csak akkor szamit
#
# A SubagentStart/SubagentStop a fo `state`-et es `ts`-t NEM irja felul: egy
# eloteres alugynok `busy` alatt fut. A megjelenitett `agents` allapotot a
# snapshot.py szarmaztatja, megjeleniteskor.

SUBAGENT_START = "SubagentStart"
SUBAGENT_STOP = "SubagentStop"

#: Ennel regebben indult alugynok-bejegyzest nem veszunk figyelembe (30 perc).
#: Nem dokumentalt, hogy a SubagentStop megy-e egy megolt/elbukott alugynokre;
#: egy elveszett Stop nem tarthatja orokre kek allapotban a sessiont.
AGENT_STALE_S = 1800


def agent_id_of(payload):
    """Az alugynok azonositoja a payloadbol, vagy None."""
    if not isinstance(payload, dict):
        return None
    agent_id = payload.get("agent_id")
    if not agent_id or not isinstance(agent_id, str):
        return None
    return agent_id


def _as_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def live_agents(agents, agents_ts, now_ts, stale_s=AGENT_STALE_S):
    """(futo alugynokok {id: ts}, utolso veg ideje vagy None).

    A `stale_s`-nel regebbi bejegyzes nem fut tovabb: a lejarata
    (`inditas + stale_s`) a vege. Serult mezok csendben kimaradnak.
    """
    running = {}
    last_end = _as_number(agents_ts)
    if isinstance(agents, dict):
        for agent_id, started in agents.items():
            started = _as_number(started)
            if not isinstance(agent_id, str) or started is None:
                continue
            if now_ts - started > stale_s:
                expired_at = started + stale_s
                if last_end is None or expired_at > last_end:
                    last_end = expired_at
                continue
            running[agent_id] = started
    return running, last_end


def next_record(previous, payload, pid, now_ts):
    """Az elozo allapotfajl-tartalom + egy hook-esemeny -> az uj tartalom.

    Visszaad: az uj rekordot; `DELETE`-et, ha a fajlt torolni kell; vagy None-t,
    ha nincs mit irni. A `focus_url` a hivo dolga (a kornyezetbol jon).
    """
    if not isinstance(payload, dict):
        return None
    prev = previous if isinstance(previous, dict) else {}
    now = int(now_ts)
    event = payload.get("hook_event_name")
    agents, agents_ts = live_agents(prev.get("agents"), prev.get("agents_ts"), now)

    if event in (SUBAGENT_START, SUBAGENT_STOP):
        agent_id = agent_id_of(payload)
        if agent_id is None:
            return None
        if event == SUBAGENT_START:
            agents[agent_id] = now
        else:
            agents.pop(agent_id, None)
            agents_ts = now
        state = prev.get("state")
        ts = _as_number(prev.get("ts"))
        if not isinstance(state, str) or not state or ts is None:
            # Nincs ertelmes elozo allapot: egy alugynok epp dolgozik.
            state = "busy"
            ts = now
    else:
        state = state_for(payload)
        if state is None or state == DELETE:
            return state
        ts = now

    record = {
        "state": state,
        "ts": ts,
        "pid": pid,
        "cwd": payload.get("cwd") or "",
    }
    if agents:
        record["agents"] = agents
    if agents_ts is not None and agents_ts > ts:
        record["agents_ts"] = int(agents_ts)
    return record


def status_record(payload, pid, now_ts):
    """Az allapotfajl tartalma (spec 4.2), vagy None, ha nincs mit irni."""
    state = state_for(payload)
    if state is None or state == DELETE:
        return None
    return {
        "state": state,
        "ts": int(now_ts),
        "pid": pid,
        "cwd": payload.get("cwd") or "",
    }


# A Warp 2026-05-22 ota (warpdotdev/warp#8611 -> PR #11130) minden panel
# kornyezeteben elhelyez egy fokusz-URL-t. A hook a claude.exe gyereke, az meg
# a Warp-panel shelljee, tehat ezt orokli. Ez az EGYETLEN megbizhato mod arra,
# hogy egy sessiont a sajat Warp-tabjahoz kossunk: a tabnak nincs sajat
# ablak-handle-je, es nincs API, ami megmondana, melyik tabban mi fut.
WARP_FOCUS_ENV = "WARP_FOCUS_URL"


def focus_url_from_env(environ):
    """A session Warp-fokusz URL-je a kornyezetbol, vagy None.

    Csak `warp://` sema fogadhato el: ez az ertek kesobb a rendszer
    URL-kezelojehez kerul, tehat nem lehet akarmi.
    """
    if not environ:
        return None
    url = environ.get(WARP_FOCUS_ENV)
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if not url.startswith("warp://"):
        return None
    return url


def session_id_of(payload):
    """Az allapotfajl neve ebbol lesz. Ures/hianyzo azonositora None."""
    if not isinstance(payload, dict):
        return None
    session_id = payload.get("session_id")
    if not session_id or not isinstance(session_id, str):
        return None
    # A fajlnevbe kerul, tehat nem tartalmazhat utvonal-elvalasztot.
    if "/" in session_id or "\\" in session_id or session_id in (".", ".."):
        return None
    return session_id
