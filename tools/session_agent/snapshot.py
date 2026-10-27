"""Tiszta logika a session-agent pillanatkep-osszefesuleséhez (spec 4.3).

Ez a modul semmilyen kornyezeti hivast nem vegez: nincs fajlrendszer-eleres,
nincs folyamatlistazas, nincs soros port. Minden bemenet argumentumkent erkezik,
ezert asztali Python 3.12-n, hardver nelkul tesztelheto. A valos vilagbeli
gyujto (Win32 folyamatlista, fajlolvasas) egy masik modulban keszul kesobb.

**Parositas: elsodlegesen `pid` szerint.** A hook a sajat szulolancan felfele
haladva megkeresi a legkozelebbi `claude.exe`-t, es annak a pid-jet irja az
allapotfajlba (merve 2026-09-10-en: egy unoka-folyamatbol negy szinten felfele
haladva talalta meg a sajat sessionjet). Ez pontos, ketertelmuseg-mentes
egyezes - nincs szukseg a `cwd`-re, ha a `pid` megvan es el.

**Ismert korlat (szandekos dontes, nem hiba) - csak a tartalek utra
vonatkozik:** ha egy allapotfajlnak nincs `pid` mezoje (regi fajl, vagy a hook
nem tudta feloldani az os-lancot), a parositas visszaesik a `cwd`-re. A valos
gyujto (`procs.py`) viszont a Win32 API korlatai miatt SOHA nem tudja egy masik
folyamat `cwd`-jet, tehat ez az ut csak akkor talal, ha a status-fajl `cwd`-je
egy masik forrasbol (pl. a hook sajat `cwd`-je) szarmazik. Ha ket elo session
ugyanabbol a munkakonyvtarbol fut es csak ezen a tartalek uton parosithato,
a dontes determinisztikus: a legkisebb pid-u folyamat kapja meg az
allapotfajlt, a tobbi "unknown" allapotban jelenik meg. Ez ritka eset, de a
kovetkezo olvasonak tudnia kell, hogy tudatos dontes, nem felejtett eset.

**Harmas osztalyozas azokra a status-fajlokra, amelyekhez nem talalunk elo
folyamatot** (ez a lenyeg: egy `waiting` session soha nem tunhet el nyomtalanul,
csak azert, mert a hook nem tudta feloldani a sajat pid-jet):

1. **van `pid`, de az nem el** -> valodi elavulas. Azonnal `stale_ids`-be kerul,
   fuggetlenul a `ts`-tol - ez a normalis "a session vegetert" ut, es a TTL nem
   menti meg (ld. `test_halott_pid_azonnal_elavult_meg_friss_ts_eseten_is`).
2. **nincs `pid`, es a `cwd`-fallback sem talal** -> **arva**, nem elavult. Megis
   megjelenik sessionkent: `id` a session_id, `n` a `cwd` utolso tagja (vagy a
   session_id, ha `cwd` sincs), `st` a fajlban levo allapot valtozatlanul. Az
   allapotot egy valodi hook irta, csak a folyamathoz nem tudtuk kotni - ezt
   eldobni pont azt a sessiont rejtene el, amire a keszulek valo.
3. **arva, de a `ts`-e regebbi, mint `ORPHAN_TTL_S`** -> vegul is elavult, hogy
   egy tenylegesen elhalt session ne ragadjon orokre a gyuruben. Hianyzo vagy
   ertelmezhetetlen `ts` lejartkent szamit (nem vegtelen frissesegkent), es nem
   dob kivetelt.

**Sorrend:** a `pid`-hez kotott sessionok (parositott vagy "unknown" elo
folyamat) `pid` szerint rendezve elolrol jonnek; utanuk az arvak
kovetkeznek, `session_id` szerint abc-sorrendben - determinisztikus mindket
csoportban, mert az arvaknak nincs pid-jük, amivel a tobbivel egyutt
rendezodhetnenek.
"""

import os

from .hookstate import AGENT_STALE_S, live_agents

#: Ha egy pid nelkuli, cwd-fallback nelkul is arva statusfajl `ts`-je ennel
#: regebbi (masodpercben), vegul elavultnak szamit. 15 perc.
ORPHAN_TTL_S = 900

#: Ennyi masodperc utan az `idle` allapot `waiting`-re valt (a gyurun zoldrol
#: borostyanra).
#:
#: Miert kell: a `Stop` esemeny pillanataban a session MAR rad var, de a
#: `Notification`/`idle_prompt` - ami ezt kimondana - sokkal kesobb vagy
#: egyaltalan nem jon. Elesben merve: egy session 110 masodperce allt `idle`-ben
#: (zolden), miközben valojaban keresre vart.
#:
#: Miert nem azonnal: kozvetlenul a `Stop` utan a felhasznalo altalaban meg ott
#: ul a session elott - ott a zold a helyes ("epp vegzett"). A borostyan annak
#: szol, ami mar egy ideje valaszra var.
IDLE_ESCALATE_S = 45


def _normalize_path(path):
    """Windows-utvonalak osszehasonlithato alakja: kisbetu, `\\` elvalaszto,
    nincs zaro elvalaszto. `None`/ures bemenetre `None`-t ad vissza."""
    if not path:
        return None
    normalized = path.strip().replace("/", "\\").rstrip("\\")
    return normalized.lower() or None


def is_session_process(proc, cli_path, shell_names):
    """Igaz, ha a folyamat valodi felhasznaloi CLI-session (spec 4.3).

    Ket felteteinek egyszerre kell teljesulnie:
    1. a folyamat a CLI binarisbol fut (nem a Claude Desktop Electron
       alkalmazasbol, amelynek a bemenete veletlenul szinten `claude.exe`);
    2. a szuloje egy ismert parancssori hej (`pwsh.exe` stb.), nem pl. egy
       masik `claude.exe` (ez zarja ki az esetleges alugynok-gyerekeket is,
       pozitiv feltetelkent, mert a mert allapot szerint most nincs ilyen).
    """
    exe = _normalize_path(proc.get("exe_path"))
    cli = _normalize_path(cli_path)
    if exe is None or exe != cli:
        return False
    parent = (proc.get("parent_name") or "").lower()
    shells = {s.lower() for s in shell_names}
    return parent in shells


def display_name(proc):
    """A megjelenitendo nev: a `--name` ertek, ha van; kulonben a `cwd` utolso
    tagja; kulonben a pid szovegkent (spec 4.3 - a session `--name` nelkul is
    lathato kell maradjon a gyuruben)."""
    name = proc.get("name")
    if name:
        return name
    cwd = _raw_last_segment(proc.get("cwd"))
    if cwd:
        return cwd
    return str(proc["pid"])


def _raw_last_segment(cwd):
    """A `cwd` utolso path-tagja, eredeti (nem kisbetusitett) alakban, vagy
    `None`, ha a `cwd` hianyzik/ures."""
    if not cwd:
        return None
    normalized = cwd.strip().replace("/", "\\").rstrip("\\")
    if not normalized:
        return None
    return normalized.split("\\")[-1]


def _is_orphan_expired(ts, now_ts, orphan_ttl_s):
    """Igaz, ha egy arva statusfajl `ts`-je a TTL-nel regebbi. Hianyzo vagy
    ertelmezhetetlen `ts` is lejartnak szamit - sose vegtelen frissessegnek."""
    try:
        ts_value = float(ts)
    except (TypeError, ValueError):
        return True
    return (now_ts - ts_value) > orphan_ttl_s


def escalate_idle(state, ts, now_ts, escalate_s=IDLE_ESCALATE_S):
    """A regota `idle` session `waiting`-be valt. Lasd `IDLE_ESCALATE_S`.

    Csak az `idle` erintett: a `busy` dolgozik, a `blocked`/`waiting` mar ugyis
    rad var. Ertelmezhetetlen `ts` eseten nem valtunk - inkabb maradjon zold,
    mint hogy egy hibas idobelyeg miatt hamisan riasszunk.
    """
    if state != "idle":
        return state
    try:
        age = now_ts - float(ts)
    except (TypeError, ValueError):
        return state
    return "waiting" if age > escalate_s else state


def display_state(info, now_ts, escalate_s=IDLE_ESCALATE_S,
                  agent_stale_s=AGENT_STALE_S):
    """Az allapotfajlbol a gyurun mutatott allapot.

    Az `agents` (kek, "az alugynokeire var") itt, MEGJELENITESKOR szuletik, nem
    a hookban - ugyanazert, amiert az `escalate_idle` is itt el: mindketto az
    idotol fugg (a 30 perces lejarat, a 45 mp-es eszkalacio), a hook viszont
    csak esemenykor fut. Ha a hook irna ki, egy elveszett SubagentStop utan
    semmi nem allitana vissza, es a fajl orokre kek maradna.

    Szabaly: `idle` vagy `waiting` + legalabb egy futo, nem lejart alugynok ->
    `agents`. A tarolt `waiting` (Notification/idle_prompt) is ide tartozik: az
    ugyanaz a helyzet (vege a kornek, csend van), csak kesobb jelezve. A
    `busy`/`blocked` erintetlen. Ha nincs futo alugynok, a szokasos eskalacio
    jon, de a 45 mp az utolso alugynok vegetol (vagy lejaratatol) szamit, ha az
    frissebb a `ts`-nel.
    """
    state = info.get("state")
    state = state if isinstance(state, str) and state else "unknown"
    if now_ts is None:
        return state
    running, last_end = live_agents(
        info.get("agents"), info.get("agents_ts"), now_ts, agent_stale_s
    )
    if running and state in ("idle", "waiting"):
        return "agents"
    ts = info.get("ts")
    if last_end is not None:
        try:
            ts = max(float(ts), last_end)
        except (TypeError, ValueError):
            pass
    return escalate_idle(state, ts, now_ts, escalate_s)


def _state_of(info, now_ts=None, escalate_s=IDLE_ESCALATE_S):
    """Az allapotfajl allapota. Hianyzo/hibas mezore "unknown".

    Elesben elofordult, hogy egy nem-allapotfajl (weather.json) kerult az
    allapotmappaba, es az `info["state"]` KeyErrorral megallitotta az egesz
    kort. Egy serult fajl nem dontheti meg a pillanatkepet.
    """
    return display_state(info, now_ts, escalate_s)


def build_snapshot(processes, status_files, now_ts, orphan_ttl_s=ORPHAN_TTL_S,
                   escalate_s=IDLE_ESCALATE_S):
    """A 4.3 osszefesulo tablazata. Visszaad (sessions, stale_ids) part.

    `processes` mar a `is_session_process` altal atengedett, valodi
    session-folyamatok listaja (a szures a hivo dolga, ez a fuggveny csak az
    osszefesulest vegzi).

    Parositas: elsodlegesen a status-fajl `pid` mezoje szerint, pontos egyezes
    a live-folyamatok listajaval. Ha a status-fajlnak nincs `pid`-je, tartalek
    ut a normalizalt `cwd` (ld. modul-docstring: ismert korlat ketertelmu cwd
    eseten). Ha a `pid` megvan, de nem el, a status NEM esik vissza `cwd`-re -
    elavultnak szamit, mert a `pid` a megbizhatobb jel. Ha se `pid`, se `cwd`
    nem parosit, a statusfajl arvakent jelenik meg, amig a `ts`-e a
    `orphan_ttl_s`-en (masodpercben, `now_ts`-hez kepest) belul van - ld.
    modul-docstring, harmas osztalyozas.
    """
    procs_by_pid = {proc["pid"]: proc for proc in processes}

    procs_by_cwd = {}
    for proc in processes:
        cwd = _normalize_path(proc.get("cwd"))
        if cwd is not None:
            procs_by_cwd.setdefault(cwd, []).append(proc)

    owner_pid_by_cwd = {
        cwd: min(p["pid"] for p in plist) for cwd, plist in procs_by_cwd.items()
    }

    matched_pids = set()
    stale_ids = []
    entries = []  # (pid, session-dict) parok a pid-hez kotott sessionoknak
    orphans = []  # session-dict-ek a pid nelkuli, cwd-vel sem parosithato arvaknak

    for session_id, info in status_files.items():
        pid = info.get("pid")
        owner = None
        owner_pid = None
        if pid is not None:
            owner = procs_by_pid.get(pid)
            owner_pid = pid if owner is not None else None
        else:
            cwd = _normalize_path(info.get("cwd"))
            plist = procs_by_cwd.get(cwd) if cwd is not None else None
            if plist:
                owner_pid = owner_pid_by_cwd[cwd]
                owner = next(p for p in plist if p["pid"] == owner_pid)

        if owner is not None:
            entries.append(
                (owner_pid, {"id": session_id, "n": display_name(owner),
                             "st": _state_of(info, now_ts, escalate_s)})
            )
            matched_pids.add(owner_pid)
            continue

        if pid is not None:
            # volt pid, de nem el - ez valodi elavulas, a TTL nem menti meg
            stale_ids.append(session_id)
            continue

        # se pid, se cwd-egyezes: arva, amig a ts friss
        if _is_orphan_expired(info.get("ts"), now_ts, orphan_ttl_s):
            stale_ids.append(session_id)
            continue

        name = _raw_last_segment(info.get("cwd")) or session_id
        orphans.append({"id": session_id, "n": name,
                        "st": _state_of(info, now_ts, escalate_s)})

    for proc in processes:
        if proc["pid"] in matched_pids:
            continue
        entries.append(
            (proc["pid"], {"id": "pid%d" % proc["pid"], "n": display_name(proc), "st": "unknown"})
        )

    entries.sort(key=lambda entry: entry[0])
    orphans.sort(key=lambda session: session["id"])
    sessions = [entry[1] for entry in entries] + orphans
    return sessions, stale_ids
