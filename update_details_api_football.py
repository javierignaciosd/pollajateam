#!/usr/bin/env python3
"""
Carga detalles avanzados de partidos para Polla '26 desde API-FOOTBALL / API-SPORTS.

Qué escribe en Firebase:
  /polla/meta/<idx>                -> fecha y estadio, usando API-FOOTBALL como respaldo/complemento
  /polla/results/<idx>             -> resultado final si API-FOOTBALL ya lo tiene y football-data no lo cargó
  /polla/details/<idx>             -> eventos, estadísticas y alineaciones del partido
  /polla/tournament/topscorers     -> goleadores del torneo
  /polla/tournament/topassists     -> asistidores del torneo
  /polla/apiFootballLastUpdate     -> resumen técnico de última ejecución

Variables de entorno en GitHub Actions:
  APIFOOTBALL_KEY    -> API key de API-FOOTBALL / API-SPORTS. También acepta API_FOOTBALL_KEY o APISPORTS_KEY.
  APIFOOTBALL_LEAGUE -> opcional. Para FIFA World Cup normalmente es 1.
  APIFOOTBALL_SEASON -> opcional. Para Mundial 2026: 2026.
  MAX_DETAILS_MATCHES-> opcional. Límite de partidos a enriquecer por corrida. Default 2.
  FORCE_TOPS         -> opcional. Si es "1", fuerza actualización de goleadores/asistidores.
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
MAX_DETAILS_MATCHES = int(os.environ.get("MAX_DETAILS_MATCHES", "2"))
FORCE_TOPS = os.environ.get("FORCE_TOPS", "").strip() == "1"

if not API_KEY:
    print("APIFOOTBALL_KEY no está definido. Se omite carga de estadísticas avanzadas.")
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
    "mexico": "mexico", "south africa": "sudafrica", "rsa": "sudafrica", "sudafrica": "sudafrica",
    "korea republic": "corea del sur", "south korea": "corea del sur", "republic of korea": "corea del sur", "korea, republic of": "corea del sur",
    "czechia": "republica checa", "czech republic": "republica checa", "republica checa": "republica checa",
    "switzerland": "suiza", "suiza": "suiza", "bosnia and herzegovina": "bosnia y herzegovina", "bosniaherzegovina": "bosnia y herzegovina",
    "canada": "canada", "qatar": "qatar", "united states": "estados unidos", "usa": "estados unidos", "united states of america": "estados unidos",
    "australia": "australia", "turkey": "turquia", "turkiye": "turquia", "türkiye": "turquia", "paraguay": "paraguay",
    "scotland": "escocia", "morocco": "marruecos", "brazil": "brasil", "haiti": "haiti", "netherlands": "paises bajos", "holland": "paises bajos",
    "sweden": "suecia", "germany": "alemania", "ivory coast": "costa de marfil", "cote divoire": "costa de marfil", "cote d ivoire": "costa de marfil",
    "ecuador": "ecuador", "curacao": "curazao", "tunisia": "tunez", "japan": "japon", "spain": "espana", "saudi arabia": "arabia saudita",
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


def req_json(url, *, method="GET", data=None, headers=None, timeout=35):
    body = None if data is None else json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    if body is not None and "Content-Type" not in req.headers:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8")
        return json.loads(raw) if raw else None


def api_get(path, params):
    qs = urllib.parse.urlencode(params)
    url = f"{API_BASE}{path}?{qs}"
    return req_json(url, headers={"x-apisports-key": API_KEY})


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
    # el endpoint ya viene ordenado, pero reforzamos por si cambia
    if kind == "assists":
        out.sort(key=lambda x: (x.get("assists") or 0, x.get("goals") or 0), reverse=True)
    else:
        out.sort(key=lambda x: (x.get("goals") or 0, x.get("assists") or 0), reverse=True)
    return out[:20]


def update_tournament_tops(now):
    current = fb_get("polla/tournament") or {}
    last = iso_to_dt(current.get("lastFetch"))
    # no gastar llamadas cada 20 minutos: basta cada 6 horas salvo FORCE_TOPS=1
    if last and not FORCE_TOPS and (now - last) < timedelta(hours=6):
        print("Top scorers/assists: omitido, última carga hace menos de 6 horas.")
        return False
    scorers = []
    assists = []
    try:
        scorers = api_get("/players/topscorers", {"league": LEAGUE, "season": SEASON}).get("response") or []
    except Exception as e:
        print(f"WARN endpoint topscorers: {e}")
    try:
        assists = api_get("/players/topassists", {"league": LEAGUE, "season": SEASON}).get("response") or []
    except Exception as e:
        print(f"WARN endpoint topassists: {e}")
    fb_put("polla/tournament", {
        "lastFetch": now.isoformat(),
        "league": LEAGUE,
        "season": SEASON,
        "topscorers": simplify_top_players(scorers, "goals"),
        "topassists": simplify_top_players(assists, "assists"),
    })
    print(f"Top scorers: {len(scorers)} · Top assists: {len(assists)}")
    return True


def should_update_details(status, dt, cached, now):
    if status in LIVE_STATUS:
        return True
    if status in PRE_STATUS and dt:
        # Busca alineaciones el día del partido / pocas horas antes.
        return timedelta(hours=-2) <= (dt - now) <= timedelta(hours=8)
    if status in FINAL_STATUS:
        # Los finales se congelan: una vez con detalle final, no se vuelve a gastar llamadas.
        if not cached:
            return True
        if not cached.get("isFinal"):
            return True
        if not cached.get("events") and not cached.get("statistics") and not cached.get("lineups"):
            return True
    return False


def main():
    now = datetime.now(timezone.utc)
    fixtures = api_get("/fixtures", {"league": LEAGUE, "season": SEASON}).get("response") or []
    cached_details = fb_get("polla/details") or {}
    wrote_details = 0
    wrote_meta = 0
    wrote_results = 0
    mapped = 0
    unmatched = []

    # Orden: vivos primero, luego finales sin cache, luego próximos.
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
        if not hit:
            st = (((item.get("fixture") or {}).get("status") or {}).get("short") or "")
            if st in FINAL_STATUS or st in LIVE_STATUS:
                unmatched.append(f"{home.get('name')} vs {away.get('name')} [{st}]")
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

        # Si API-FOOTBALL ya tiene marcador final, también respalda /polla/results.
        goals = item.get("goals") or {}
        if status in FINAL_STATUS and goals.get("home") is not None and goals.get("away") is not None:
            if ch == polla_home:
                l, v = int(goals["home"]), int(goals["away"])
            else:
                l, v = int(goals["away"]), int(goals["home"])
            fb_put(f"polla/results/{idx}", {"l": l, "v": v})
            wrote_results += 1

        cdet = cached_details.get(str(idx)) or cached_details.get(idx) or {}
        if wrote_details >= MAX_DETAILS_MATCHES:
            continue
        if not should_update_details(status, dt, cdet, now):
            continue

        fid = fixture.get("id")
        if not fid:
            continue
        print(f"Detalle idx {idx} fixture {fid} {home.get('name')} vs {away.get('name')} status={status}")
        try:
            events = api_get("/fixtures/events", {"fixture": fid}).get("response") or []
            statistics = api_get("/fixtures/statistics", {"fixture": fid}).get("response") or []
            lineups = api_get("/fixtures/lineups", {"fixture": fid}).get("response") or []
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
            })
            wrote_details += 1
        except Exception as e:
            print(f"WARN detalle idx {idx}: {e}")

    tops_updated = False
    try:
        tops_updated = update_tournament_tops(now)
    except Exception as e:
        print(f"WARN top scorers/assists: {e}")

    summary = {
        "updatedAt": now.isoformat(),
        "source": "api-football",
        "league": LEAGUE,
        "season": SEASON,
        "fixturesReceived": len(fixtures),
        "mappedGroupFixtures": mapped,
        "metaWritten": wrote_meta,
        "resultsWritten": wrote_results,
        "detailsWritten": wrote_details,
        "topTournamentUpdated": tops_updated,
        "unmatched": unmatched[:20],
    }
    fb_put("polla/apiFootballLastUpdate", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
