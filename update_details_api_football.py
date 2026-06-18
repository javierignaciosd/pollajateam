#!/usr/bin/env python3
"""
Actualiza estadísticas avanzadas de la Polla '26 desde API-FOOTBALL / API-SPORTS.

Escribe en Firebase:
  /polla/meta/<idx>                -> fecha y estadio
  /polla/results/<idx>             -> marcador final de respaldo
  /polla/details/<idx>             -> eventos, estadísticas y alineaciones
  /polla/tournament                -> goleadores y asistidores
  /polla/apiFootballLastUpdate     -> diagnóstico completo de la última ejecución

Variables de entorno en GitHub Actions:
  APIFOOTBALL_KEY    -> API key de API-FOOTBALL / API-SPORTS
  APIFOOTBALL_LEAGUE -> opcional. Para FIFA World Cup normalmente es 1
  APIFOOTBALL_SEASON -> opcional. Para Mundial 2026: 2026
  MAX_DETAILS_MATCHES-> opcional. Límite de partidos a enriquecer por corrida. Default 4
  FORCE_TOPS         -> opcional. Si es "1", fuerza actualización de goleadores/asistencias
"""

import os
import json
import re
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

DB_URL = "https://polla-gol-jateam-default-rtdb.firebaseio.com"
API_BASE = "https://v3.football.api-sports.io"
API_KEY = (
    os.environ.get("APIFOOTBALL_KEY")
    or os.environ.get("API_FOOTBALL_KEY")
    or os.environ.get("APISPORTS_KEY")
    or ""
).strip()
LEAGUE = int(os.environ.get("APIFOOTBALL_LEAGUE", "1"))
SEASON = int(os.environ.get("APIFOOTBALL_SEASON", "2026"))
MAX_DETAILS_MATCHES = int(os.environ.get("MAX_DETAILS_MATCHES", "4"))
FORCE_TOPS = os.environ.get("FORCE_TOPS", "").strip() == "1"

# Si la key no existe, dejamos un diagnóstico en stdout y salimos sin fallar el Action.
if not API_KEY:
    print("APIFOOTBALL_KEY no está definido. Crea el secreto APIFOOTBALL_KEY en GitHub Actions.")
    raise SystemExit(0)

# idx -> local, visita en nombres normalizados de tu polla
FIX = [
    [0, "republica checa", "sudafrica"], [1, "suiza", "bosnia y herzegovina"], [2, "canada", "qatar"], [3, "mexico", "corea del sur"],
    [4, "estados unidos", "australia"], [5, "escocia", "marruecos"], [6, "brasil", "haiti"], [7, "turquia", "paraguay"],
    [8, "paises bajos", "suecia"], [9, "alemania", "costa de marfil"], [10, "ecuador", "curazao"], [11, "tunez", "japon"],
    [12, "espana", "arabia saudita"], [13, "belgica", "iran"], [14, "uruguay", "cabo verde"], [15, "nueva zelanda", "egipto"],
    [16, "argentina", "austria"], [17, "francia", "irak"], [18, "noruega", "senegal"], [19, "jordania", "argelia"],
    [20, "portugal", "uzbekistan"], [21, "inglaterra", "ghana"], [22, "panama", "croacia"], [23, "colombia", "rd del congo"],
    [24, "suiza", "canada"], [25, "bosnia y herzegovina", "qatar"], [26, "escocia", "brasil"], [27, "marruecos", "haiti"],
    [28, "republica checa", "mexico"], [29, "sudafrica", "corea del sur"], [30, "ecuador", "alemania"], [31, "curazao", "costa de marfil"],
    [32, "tunez", "paises bajos"], [33, "japon", "suecia"], [34, "turquia", "estados unidos"], [35, "paraguay", "australia"],
    [36, "noruega", "francia"], [37, "senegal", "irak"], [38, "uruguay", "espana"], [39, "cabo verde", "arabia saudita"],
    [40, "nueva zelanda", "belgica"], [41, "egipto", "iran"], [42, "panama", "inglaterra"], [43, "croacia", "ghana"],
    [44, "colombia", "portugal"], [45, "rd del congo", "uzbekistan"], [46, "jordania", "argentina"], [47, "argelia", "austria"],
    [48, "corea del sur", "republica checa"], [49, "mexico", "sudafrica"], [50, "bosnia y herzegovina", "canada"], [51, "qatar", "suiza"],
    [52, "australia", "turquia"], [53, "estados unidos", "paraguay"], [54, "brasil", "marruecos"], [55, "escocia", "haiti"],
    [56, "japon", "paises bajos"], [57, "suecia", "tunez"], [58, "alemania", "curazao"], [59, "costa de marfil", "ecuador"],
    [60, "arabia saudita", "uruguay"], [61, "cabo verde", "espana"], [62, "belgica", "egipto"], [63, "iran", "nueva zelanda"],
    [64, "argelia", "argentina"], [65, "austria", "jordania"], [66, "francia", "senegal"], [67, "irak", "noruega"],
    [68, "colombia", "uzbekistan"], [69, "portugal", "rd del congo"], [70, "croacia", "inglaterra"], [71, "ghana", "panama"]
]

ALIAS = {
    "mexico": "mexico", "méxico": "mexico", "south africa": "sudafrica", "rsa": "sudafrica", "sudafrica": "sudafrica",
    "korea republic": "corea del sur", "south korea": "corea del sur", "republic of korea": "corea del sur", "korea, republic of": "corea del sur",
    "czechia": "republica checa", "czech republic": "republica checa", "republica checa": "republica checa",
    "switzerland": "suiza", "suiza": "suiza", "bosnia and herzegovina": "bosnia y herzegovina", "bosniaherzegovina": "bosnia y herzegovina",
    "canada": "canada", "qatar": "qatar", "united states": "estados unidos", "usa": "estados unidos", "united states of america": "estados unidos",
    "australia": "australia", "turkey": "turquia", "turkiye": "turquia", "türkiye": "turquia", "paraguay": "paraguay",
    "scotland": "escocia", "morocco": "marruecos", "brazil": "brasil", "haiti": "haiti", "netherlands": "paises bajos", "holland": "paises bajos",
    "sweden": "suecia", "germany": "alemania", "ivory coast": "costa de marfil", "cote divoire": "costa de marfil", "cote d ivoire": "costa de marfil", "côte d'ivoire": "costa de marfil",
    "ecuador": "ecuador", "curacao": "curazao", "curaçao": "curazao", "tunisia": "tunez", "japan": "japon", "spain": "espana", "saudi arabia": "arabia saudita",
    "belgium": "belgica", "iran": "iran", "ir iran": "iran", "uruguay": "uruguay", "cape verde": "cabo verde", "cabo verde": "cabo verde",
    "new zealand": "nueva zelanda", "egypt": "egipto", "argentina": "argentina", "austria": "austria", "france": "francia", "iraq": "irak",
    "norway": "noruega", "senegal": "senegal", "jordan": "jordania", "algeria": "argelia", "portugal": "portugal", "uzbekistan": "uzbekistan",
    "england": "inglaterra", "ghana": "ghana", "panama": "panama", "croatia": "croacia", "colombia": "colombia", "dr congo": "rd del congo",
    "congo dr": "rd del congo", "democratic republic of congo": "rd del congo", "congo democratic republic": "rd del congo", "congo": "rd del congo",
}

PAIR = {frozenset((h, a)): (idx, h, a) for idx, h, a in FIX}
LIVE_STATUS = {"1H", "HT", "2H", "ET", "BT", "P", "LIVE", "INT"}
FINAL_STATUS = {"FT", "AET", "PEN"}
PRE_STATUS = {"NS", "TBD"}

api_calls = 0
api_errors = []


def norm(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", str(s or "")) if unicodedata.category(c) != "Mn").lower()
    s = re.sub(r"[^a-z ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def canon(*names):
    for n in names:
        k = norm(n)
        if not k:
            continue
        if k in ALIAS:
            return ALIAS[k]
        for _, h, a in FIX:
            if k == h or k == a:
                return k
    return None


def req_json(url, *, method="GET", data=None, headers=None, timeout=45):
    body = None if data is None else json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    if body is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8")
        return json.loads(raw) if raw else None


def api_get(path, params):
    global api_calls
    api_calls += 1
    qs = urllib.parse.urlencode(params)
    url = f"{API_BASE}{path}?{qs}"
    payload = req_json(url, headers={"x-apisports-key": API_KEY})
    errs = payload.get("errors") if isinstance(payload, dict) else None
    has_errors = bool(errs) and errs != []
    if has_errors:
        api_errors.append({"endpoint": path, "params": params, "errors": errs})
        print(f"API ERROR {path} {params}: {errs}")
    return payload if isinstance(payload, dict) else {"response": [], "errors": {"invalid": "Respuesta no JSON"}}


def fb_url(path):
    return f"{DB_URL.rstrip('/')}/{path.strip('/')}.json"


def fb_get(path):
    try:
        return req_json(fb_url(path))
    except Exception as e:
        print(f"WARN fb_get {path}: {e}")
        return None


def fb_put(path, obj):
    return req_json(fb_url(path), method="PUT", data=obj)


def iso_to_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def player_name(p):
    if not p:
        return ""
    if isinstance(p, dict):
        return p.get("name") or p.get("firstname") or p.get("lastname") or ""
    return str(p)


def simplify_events(resp):
    out = []
    for e in resp or []:
        tm = e.get("time") or {}
        minute = tm.get("elapsed")
        extra = tm.get("extra")
        out.append({
            "time": f"{minute}+{extra}" if minute is not None and extra else (str(minute) if minute is not None else ""),
            "team": (e.get("team") or {}).get("name") or "",
            "player": player_name(e.get("player")),
            "assist": player_name(e.get("assist")),
            "type": e.get("type") or "",
            "detail": e.get("detail") or "",
            "comments": e.get("comments") or "",
        })
    return out


def simplify_statistics(resp):
    simple = []
    for row in resp or []:
        team = (row.get("team") or {}).get("name") or ""
        stats = {}
        for st in row.get("statistics") or []:
            typ = st.get("type")
            if typ:
                stats[typ] = st.get("value")
        simple.append({"team": team, "stats": stats})
    home = simple[0] if len(simple) > 0 else {"team": "Local", "stats": {}}
    away = simple[1] if len(simple) > 1 else {"team": "Visita", "stats": {}}
    return {"home": home, "away": away}


def simplify_lineups(resp):
    out = []
    for lu in resp or []:
        def ply(x):
            p = x.get("player") or x
            return {"name": p.get("name") or "", "number": p.get("number") or "", "pos": p.get("pos") or p.get("grid") or ""}
        out.append({
            "team": ((lu.get("team") or {}).get("name") or ""),
            "formation": lu.get("formation") or "",
            "startXI": [ply(x) for x in (lu.get("startXI") or [])],
            "substitutes": [ply(x) for x in (lu.get("substitutes") or [])],
        })
    return out


def simplify_top_players(resp, kind):
    out = []
    for row in resp or []:
        player = row.get("player") or {}
        stats = (row.get("statistics") or [{}])[0] or {}
        goals = stats.get("goals") or {}
        games = stats.get("games") or {}
        team = stats.get("team") or {}
        out.append({
            "player": player.get("name") or "",
            "photo": player.get("photo") or "",
            "team": team.get("name") or "",
            "country": player.get("nationality") or "",
            "goals": goals.get("total") or 0,
            "assists": goals.get("assists") or 0,
            "appearances": games.get("appearences") or games.get("appearances") or 0,
            "minutes": games.get("minutes") or 0,
        })
    if kind == "assists":
        out.sort(key=lambda x: (x.get("assists") or 0, x.get("goals") or 0), reverse=True)
    else:
        out.sort(key=lambda x: (x.get("goals") or 0, x.get("assists") or 0), reverse=True)
    return out[:20]


def should_update_details(status, dt, cached, now):
    # Evita que los primeros partidos sin cobertura bloqueen siempre los siguientes.
    last_try = iso_to_dt((cached or {}).get("updatedAt"))
    if last_try and (now - last_try) < timedelta(hours=6) and not (status in LIVE_STATUS):
        return False
    if status in LIVE_STATUS:
        return True
    if status in PRE_STATUS and dt:
        return timedelta(hours=-2) <= (dt - now) <= timedelta(hours=8)
    if status in FINAL_STATUS:
        if not cached:
            return True
        if not cached.get("isFinal"):
            return True
        if not cached.get("hasAnyAdvancedData"):
            return True
    return False


def update_tournament_tops(now):
    current = fb_get("polla/tournament") or {}
    last = iso_to_dt(current.get("lastFetch"))
    if last and not FORCE_TOPS and (now - last) < timedelta(hours=6):
        print("Top scorers/assists: omitido, última carga hace menos de 6 horas. Usa FORCE_TOPS=1 para forzar.")
        return False, len(current.get("topscorers") or []), len(current.get("topassists") or []), []

    diag = []
    scorers_payload = api_get("/players/topscorers", {"league": LEAGUE, "season": SEASON})
    assists_payload = api_get("/players/topassists", {"league": LEAGUE, "season": SEASON})
    scorers = scorers_payload.get("response") or []
    assists = assists_payload.get("response") or []
    if scorers_payload.get("errors"):
        diag.append({"endpoint": "topscorers", "errors": scorers_payload.get("errors")})
    if assists_payload.get("errors"):
        diag.append({"endpoint": "topassists", "errors": assists_payload.get("errors")})

    obj = {
        "lastFetch": now.isoformat(),
        "league": LEAGUE,
        "season": SEASON,
        "topscorers": simplify_top_players(scorers, "goals"),
        "topassists": simplify_top_players(assists, "assists"),
        "rawCounts": {"topscorers": len(scorers), "topassists": len(assists)},
        "errors": diag,
    }
    fb_put("polla/tournament", obj)
    print(f"Top scorers: {len(scorers)} · Top assists: {len(assists)}")
    return True, len(scorers), len(assists), diag


def fixture_sample(fixtures, limit=8):
    out = []
    for item in fixtures[:limit]:
        f = item.get("fixture") or {}
        teams = item.get("teams") or {}
        out.append({
            "id": f.get("id"),
            "date": f.get("date"),
            "status": (f.get("status") or {}).get("short"),
            "home": (teams.get("home") or {}).get("name"),
            "away": (teams.get("away") or {}).get("name"),
            "venue": ((f.get("venue") or {}).get("name") or ""),
        })
    return out


def main():
    now = datetime.now(timezone.utc)
    fixtures_payload = api_get("/fixtures", {"league": LEAGUE, "season": SEASON})
    fixtures = fixtures_payload.get("response") or []
    cached_details = fb_get("polla/details") or {}
    wrote_details = 0
    wrote_meta = 0
    wrote_results = 0
    mapped = 0
    unmatched = []
    details_candidates = []

    def priority(row):
        st = (((row.get("fixture") or {}).get("status") or {}).get("short") or "")
        dt = iso_to_dt(((row.get("fixture") or {}).get("date"))) or now + timedelta(days=365)
        if st in LIVE_STATUS:
            return (0, dt)
        if st in FINAL_STATUS:
            return (1, dt)
        return (2, dt)

    for item in sorted(fixtures, key=priority):
        teams = item.get("teams") or {}
        home = teams.get("home") or {}
        away = teams.get("away") or {}
        ch = canon(home.get("name"), home.get("code"))
        ca = canon(away.get("name"), away.get("code"))
        hit = PAIR.get(frozenset((ch, ca))) if (ch and ca) else None
        st = (((item.get("fixture") or {}).get("status") or {}).get("short") or "")
        if not hit:
            if len(unmatched) < 30:
                unmatched.append({"home": home.get("name"), "away": away.get("name"), "status": st, "canonHome": ch, "canonAway": ca})
            continue

        idx, polla_home, polla_away = hit
        mapped += 1
        fixture = item.get("fixture") or {}
        status = (fixture.get("status") or {}).get("short") or ""
        dt = iso_to_dt(fixture.get("date"))
        venue_obj = fixture.get("venue") or {}
        venue = venue_obj.get("name") or ""
        city = venue_obj.get("city") or ""
        venue_full = f"{venue}, {city}" if venue and city and city.lower() not in venue.lower() else venue

        if dt or venue_full:
            fb_put(f"polla/meta/{idx}", {"date": fixture.get("date"), "venue": venue_full, "source": "api-football"})
            wrote_meta += 1

        goals = item.get("goals") or {}
        if status in FINAL_STATUS and goals.get("home") is not None and goals.get("away") is not None:
            if ch == polla_home:
                l, v = int(goals["home"]), int(goals["away"])
            else:
                l, v = int(goals["away"]), int(goals["home"])
            fb_put(f"polla/results/{idx}", {"l": l, "v": v})
            wrote_results += 1

        cdet = cached_details.get(str(idx)) or cached_details.get(idx) or {}
        wants = should_update_details(status, dt, cdet, now)
        if wants and len(details_candidates) < 20:
            details_candidates.append({"idx": idx, "fixtureId": fixture.get("id"), "home": home.get("name"), "away": away.get("name"), "status": status})
        if wrote_details >= MAX_DETAILS_MATCHES or not wants:
            continue

        fid = fixture.get("id")
        if not fid:
            continue
        print(f"Detalle idx {idx} fixture {fid} {home.get('name')} vs {away.get('name')} status={status}")
        try:
            events_payload = api_get("/fixtures/events", {"fixture": fid})
            statistics_payload = api_get("/fixtures/statistics", {"fixture": fid})
            lineups_payload = api_get("/fixtures/lineups", {"fixture": fid})
            events = events_payload.get("response") or []
            statistics = statistics_payload.get("response") or []
            lineups = lineups_payload.get("response") or []
            has_any = bool(events or statistics or lineups)
            fb_put(f"polla/details/{idx}", {
                "fixtureId": fid,
                "status": status,
                "isLive": status in LIVE_STATUS,
                "isFinal": status in FINAL_STATUS,
                "updatedAt": now.isoformat(),
                "home": home.get("name") or "",
                "away": away.get("name") or "",
                "events": simplify_events(events),
                "statistics": simplify_statistics(statistics),
                "lineups": simplify_lineups(lineups),
                "hasAnyAdvancedData": has_any,
                "rawCounts": {"events": len(events), "statistics": len(statistics), "lineups": len(lineups)},
                "errors": [
                    {"endpoint": "events", "errors": events_payload.get("errors")} if events_payload.get("errors") else None,
                    {"endpoint": "statistics", "errors": statistics_payload.get("errors")} if statistics_payload.get("errors") else None,
                    {"endpoint": "lineups", "errors": lineups_payload.get("errors")} if lineups_payload.get("errors") else None,
                ],
            })
            wrote_details += 1
        except Exception as e:
            print(f"WARN detalle idx {idx}: {e}")

    try:
        tops_updated, scorers_raw, assists_raw, tops_errors = update_tournament_tops(now)
    except Exception as e:
        print(f"WARN top scorers/assists: {e}")
        tops_updated, scorers_raw, assists_raw, tops_errors = False, 0, 0, [{"exception": str(e)}]

    summary = {
        "updatedAt": now.isoformat(),
        "source": "api-football",
        "league": LEAGUE,
        "season": SEASON,
        "apiCallsUsedInRun": api_calls,
        "fixturesReceived": len(fixtures),
        "fixtureApiErrors": fixtures_payload.get("errors") or None,
        "fixtureSample": fixture_sample(fixtures),
        "mappedGroupFixtures": mapped,
        "metaWritten": wrote_meta,
        "resultsWritten": wrote_results,
        "detailsWritten": wrote_details,
        "detailsCandidates": details_candidates,
        "topTournamentUpdated": tops_updated,
        "topscorersRaw": scorers_raw,
        "topassistsRaw": assists_raw,
        "topErrors": tops_errors,
        "apiErrors": api_errors[:20],
        "unmatched": unmatched[:30],
        "note": "Si fixturesReceived es 0 o apiErrors trae mensajes, el problema es API/key/plan/league-season. Si mappedGroupFixtures es 0, el fixture real de API-FOOTBALL no calza con los partidos hardcodeados de la polla o faltan alias de nombres.",
    }
    fb_put("polla/apiFootballLastUpdate", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
