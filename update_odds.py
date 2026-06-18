#!/usr/bin/env python3
"""
Actualiza cuotas 1X2 (local / empate / visita) desde Odds-API.io y las guarda en Firebase.

Flujo:
  Odds-API.io -> GitHub Actions -> Firebase /polla/odds/<idx> -> HTML

Variables de entorno:
  ODDS_API_KEY      -> API key de Odds-API.io (OBLIGATORIO)
  ODDS_BOOKMAKERS  -> Bookmakers separados por coma. Opcional.
                     Default: Bet365,Unibet,SingBet,Pinnacle,Betfair

Notas:
- No expongas ODDS_API_KEY en el HTML.
- El script intenta mapear los eventos de Odds-API.io contra los partidos de la polla
  usando los pares de equipos.
"""
import os, json, re, unicodedata, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta

DB_URL = "https://polla-gol-jateam-default-rtdb.firebaseio.com"
BASE = "https://api.odds-api.io/v3"

ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "").strip()
BOOKMAKERS = os.environ.get("ODDS_BOOKMAKERS", "Bet365,Unibet,SingBet,Pinnacle,Betfair").strip()

if not ODDS_API_KEY:
    raise SystemExit("Falta ODDS_API_KEY (API key de Odds-API.io).")

FIX = [
    [0, "republica checa", "sudafrica"],
    [1, "suiza", "bosnia y herzegovina"],
    [2, "canada", "qatar"],
    [3, "mexico", "corea del sur"],
    [4, "estados unidos", "australia"],
    [5, "escocia", "marruecos"],
    [6, "brasil", "haiti"],
    [7, "turquia", "paraguay"],
    [8, "paises bajos", "suecia"],
    [9, "alemania", "costa de marfil"],
    [10, "ecuador", "curazao"],
    [11, "tunez", "japon"],
    [12, "espana", "arabia saudita"],
    [13, "belgica", "iran"],
    [14, "uruguay", "cabo verde"],
    [15, "nueva zelanda", "egipto"],
    [16, "argentina", "austria"],
    [17, "francia", "irak"],
    [18, "noruega", "senegal"],
    [19, "jordania", "argelia"],
    [20, "portugal", "uzbekistan"],
    [21, "inglaterra", "ghana"],
    [22, "panama", "croacia"],
    [23, "colombia", "rd del congo"],
    [24, "suiza", "canada"],
    [25, "bosnia y herzegovina", "qatar"],
    [26, "escocia", "brasil"],
    [27, "marruecos", "haiti"],
    [28, "republica checa", "mexico"],
    [29, "sudafrica", "corea del sur"],
    [30, "ecuador", "alemania"],
    [31, "curazao", "costa de marfil"],
    [32, "tunez", "paises bajos"],
    [33, "japon", "suecia"],
    [34, "turquia", "estados unidos"],
    [35, "paraguay", "australia"],
    [36, "noruega", "francia"],
    [37, "senegal", "irak"],
    [38, "uruguay", "espana"],
    [39, "cabo verde", "arabia saudita"],
    [40, "nueva zelanda", "belgica"],
    [41, "egipto", "iran"],
    [42, "panama", "inglaterra"],
    [43, "croacia", "ghana"],
    [44, "colombia", "portugal"],
    [45, "rd del congo", "uzbekistan"],
    [46, "jordania", "argentina"],
    [47, "argelia", "austria"],
    [48, "corea del sur", "republica checa"],
    [49, "mexico", "sudafrica"],
    [50, "bosnia y herzegovina", "canada"],
    [51, "qatar", "suiza"],
    [52, "australia", "turquia"],
    [53, "estados unidos", "paraguay"],
    [54, "brasil", "marruecos"],
    [55, "escocia", "haiti"],
    [56, "japon", "paises bajos"],
    [57, "suecia", "tunez"],
    [58, "alemania", "curazao"],
    [59, "costa de marfil", "ecuador"],
    [60, "arabia saudita", "uruguay"],
    [61, "cabo verde", "espana"],
    [62, "belgica", "egipto"],
    [63, "iran", "nueva zelanda"],
    [64, "argelia", "argentina"],
    [65, "austria", "jordania"],
    [66, "francia", "senegal"],
    [67, "irak", "noruega"],
    [68, "colombia", "uzbekistan"],
    [69, "portugal", "rd del congo"],
    [70, "croacia", "inglaterra"],
    [71, "ghana", "panama"]
]

ALIAS = {
    "mexico":"mexico","south africa":"sudafrica","rsa":"sudafrica",
    "czechia":"republica checa","czech republic":"republica checa","czech rep":"republica checa",
    "republica checa":"republica checa","switzerland":"suiza","sui":"suiza",
    "bosnia and herzegovina":"bosnia y herzegovina","bosniaherzegovina":"bosnia y herzegovina",
    "bosnia & herzegovina":"bosnia y herzegovina","bosnia":"bosnia y herzegovina",
    "canada":"canada","qatar":"qatar","united states":"estados unidos","usa":"estados unidos",
    "united states of america":"estados unidos","australia":"australia","turkey":"turquia",
    "turkiye":"turquia","trkiye":"turquia","paraguay":"paraguay","scotland":"escocia",
    "morocco":"marruecos","brazil":"brasil","haiti":"haiti","netherlands":"paises bajos",
    "holland":"paises bajos","sweden":"suecia","germany":"alemania","ivory coast":"costa de marfil",
    "cote divoire":"costa de marfil","cote d ivoire":"costa de marfil","ecuador":"ecuador",
    "curacao":"curazao","tunisia":"tunez","japan":"japon","spain":"espana","saudi arabia":"arabia saudita",
    "belgium":"belgica","iran":"iran","ir iran":"iran","uruguay":"uruguay","cape verde":"cabo verde",
    "cabo verde":"cabo verde","new zealand":"nueva zelanda","egypt":"egipto","argentina":"argentina",
    "austria":"austria","france":"francia","iraq":"irak","norway":"noruega","senegal":"senegal",
    "jordan":"jordania","algeria":"argelia","portugal":"portugal","uzbekistan":"uzbekistan",
    "england":"inglaterra","ghana":"ghana","panama":"panama","croatia":"croacia","colombia":"colombia",
    "dr congo":"rd del congo","congo dr":"rd del congo","democratic republic of congo":"rd del congo",
    "congo democratic republic":"rd del congo","dr congo (kinshasa)":"rd del congo",
    "korea republic":"corea del sur","south korea":"corea del sur","republic of korea":"corea del sur",
    "korea, republic of":"corea del sur"
}

def norm(s):
    s=''.join(c for c in unicodedata.normalize('NFD',str(s or '')) if unicodedata.category(c)!='Mn').lower()
    s=re.sub(r'[^a-z ]',' ',s)
    return re.sub(r'\s+',' ',s).strip()

def canon(*names):
    for n in names:
        k=norm(n)
        if not k:
            continue
        if k in ALIAS:
            return ALIAS[k]
        for _,h,a in FIX:
            if k==h or k==a:
                return k
    return None

PAIR={}
for idx,h,a in FIX:
    PAIR[frozenset((h,a))]=(idx,h,a)

def fb_put(path, obj):
    data=json.dumps(obj, ensure_ascii=False).encode()
    req=urllib.request.Request(
        f"{DB_URL}/{path}.json",
        data=data,
        method="PUT",
        headers={"Content-Type":"application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status

def api_get(path, params):
    params = dict(params or {})
    params["apiKey"] = ODDS_API_KEY
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Accept":"application/json"})
    with urllib.request.urlopen(req, timeout=35) as r:
        body = r.read().decode()
        data = json.loads(body) if body else None
        info = {
            "status": r.status,
            "remaining": r.headers.get("x-ratelimit-remaining"),
            "limit": r.headers.get("x-ratelimit-limit"),
            "reset": r.headers.get("x-ratelimit-reset")
        }
        return data, info

def event_home_away(ev):
    # Odds-API.io normalmente usa home/away, pero dejamos tolerancia a otras estructuras.
    h = ev.get("home") or ev.get("homeTeam") or ev.get("local") or ev.get("teamHome")
    a = ev.get("away") or ev.get("awayTeam") or ev.get("visitor") or ev.get("teamAway")
    if isinstance(h, dict):
        h = h.get("name") or h.get("shortName")
    if isinstance(a, dict):
        a = a.get("name") or a.get("shortName")
    return h, a

def map_event(ev):
    h, a = event_home_away(ev)
    ch, ca = canon(h), canon(a)
    if not ch or not ca:
        return None
    hit = PAIR.get(frozenset((ch, ca)))
    if not hit:
        return None
    idx, fh, fa = hit
    reversed_home = ch != fh
    return {
        "idx": idx,
        "event_home_canon": ch,
        "event_away_canon": ca,
        "home": h,
        "away": a,
        "reversed": reversed_home
    }

def status_priority(st):
    s=str(st or '').lower()
    if s in ("live","in_play","in-play","inplay"):
        return 0
    if s in ("pending","scheduled","upcoming"):
        return 1
    if s in ("settled","finished","complete","completed"):
        return 3
    return 2

def choose_event(existing, candidate):
    if existing is None:
        return candidate
    ps = status_priority(candidate["event"].get("status")) - status_priority(existing["event"].get("status"))
    if ps < 0:
        return candidate
    if ps > 0:
        return existing
    # Si tienen mismo estado, preferimos el evento más cercano al presente/futuro.
    def dt_score(x):
        d=x["event"].get("date") or ""
        try:
            ts=datetime.fromisoformat(d.replace("Z","+00:00")).timestamp()
            return abs(ts - datetime.now(timezone.utc).timestamp())
        except Exception:
            return 10**18
    return candidate if dt_score(candidate) < dt_score(existing) else existing

def fetch_candidate_events():
    events=[]
    errors=[]
    infos=[]
    # 1) En vivo
    try:
        data, info = api_get("/events/live", {})
        infos.append(info)
        if isinstance(data, list):
            events.extend(data)
    except Exception as e:
        errors.append(f"events/live: {str(e)[:220]}")
    # 2) Próximos 14 días / próximos del deporte football
    try:
        to=(datetime.now(timezone.utc)+timedelta(days=14)).isoformat().replace("+00:00","Z")
        data, info = api_get("/events", {"sport":"football","limit":5000,"to":to})
        infos.append(info)
        if isinstance(data, list):
            events.extend(data)
    except Exception as e:
        errors.append(f"events football: {str(e)[:220]}")
    # dedupe por id
    out={}
    for ev in events:
        eid=str(ev.get("id") or "")
        if eid:
            out[eid]=ev
    return list(out.values()), errors, infos

def market_ml(markets):
    if not isinstance(markets, list):
        return None
    names = {"ml","moneyline","match winner","match result","1x2","winner","full time result"}
    for m in markets:
        name=norm(m.get("name") or m.get("market") or "")
        if name in names or name.replace(" ","") in {"1x2","ml"}:
            odds=m.get("odds") or []
            if isinstance(odds, list) and odds:
                return odds[0], m.get("updatedAt")
            if isinstance(odds, dict):
                return odds, m.get("updatedAt")
    return None

def num(x):
    try:
        if x is None or x == "":
            return None
        return float(x)
    except Exception:
        return None

def parse_odds_payload(payload, mapped):
    """
    Devuelve objeto limpio para Firebase.
    Si el evento viene invertido respecto del fixture de la polla, intercambiamos home/away.
    """
    bookies = payload.get("bookmakers") or {}
    rows = {}
    best = {
        "home": {"odds": None, "bookmaker": None},
        "draw": {"odds": None, "bookmaker": None},
        "away": {"odds": None, "bookmaker": None},
    }
    avg_acc = {"home": [], "draw": [], "away": []}
    latest = None

    for bookmaker, markets in bookies.items():
        ml = market_ml(markets)
        if not ml:
            continue
        odds, upd = ml
        oh, od, oa = num(odds.get("home")), num(odds.get("draw")), num(odds.get("away"))
        if mapped.get("reversed"):
            oh, oa = oa, oh
        if oh is None and od is None and oa is None:
            continue
        rows[bookmaker] = {"home": oh, "draw": od, "away": oa, "updatedAt": upd}
        if upd and (latest is None or str(upd) > str(latest)):
            latest = upd
        for key, val in (("home", oh), ("draw", od), ("away", oa)):
            if val is None:
                continue
            avg_acc[key].append(val)
            if best[key]["odds"] is None or val > best[key]["odds"]:
                best[key] = {"odds": val, "bookmaker": bookmaker}

    if not rows:
        return None

    avg = {}
    for key, vals in avg_acc.items():
        avg[key] = round(sum(vals)/len(vals), 3) if vals else None

    implied_raw = {}
    source_for_prob = {}
    for key in ("home","draw","away"):
        source_for_prob[key] = best[key]["odds"] or avg[key]
        implied_raw[key] = (1 / source_for_prob[key]) if source_for_prob[key] else None
    total = sum(v for v in implied_raw.values() if v)
    implied = {k: round((v/total)*100, 1) if v and total else None for k,v in implied_raw.items()}

    # Favorito por menor cuota promedio/best
    fav = None
    fav_val = None
    for k,v in source_for_prob.items():
        if v is not None and (fav_val is None or v < fav_val):
            fav, fav_val = k, v

    return {
        "eventId": payload.get("id"),
        "status": payload.get("status"),
        "date": payload.get("date"),
        "homeApi": payload.get("home"),
        "awayApi": payload.get("away"),
        "bookmakers": rows,
        "best": best,
        "average": avg,
        "implied": implied,
        "favorite": fav,
        "market": "ML",
        "bookmakersRequested": BOOKMAKERS,
        "updatedAt": latest or datetime.now(timezone.utc).isoformat(),
        "fetchedAt": datetime.now(timezone.utc).isoformat()
    }

def chunks(items, n):
    for i in range(0, len(items), n):
        yield items[i:i+n]

def fetch_odds_multi(event_ids):
    if not event_ids:
        return []
    params = {"eventIds": ",".join(map(str,event_ids)), "bookmakers": BOOKMAKERS}
    data, info = api_get("/odds/multi", params)
    if isinstance(data, list):
        return data, info
    if isinstance(data, dict):
        # Algunas APIs devuelven mapa por eventId
        return list(data.values()), info
    return [], info

def main():
    events, errors, infos = fetch_candidate_events()
    print(f"Eventos recibidos Odds-API.io: {len(events)}")

    mapped_by_idx = {}
    unmapped_sample=[]
    for ev in events:
        mp = map_event(ev)
        if not mp:
            if len(unmapped_sample)<12:
                h,a=event_home_away(ev)
                league=ev.get("league") or {}
                if isinstance(league, dict):
                    league=league.get("name") or league.get("slug")
                unmapped_sample.append({"id":ev.get("id"),"home":h,"away":a,"league":league,"status":ev.get("status")})
            continue
        rec = {"event": ev, "map": mp}
        idx = mp["idx"]
        mapped_by_idx[idx] = choose_event(mapped_by_idx.get(idx), rec)

    print(f"Eventos mapeados a partidos de la polla: {len(mapped_by_idx)}")

    event_to_idx = {}
    event_ids=[]
    for idx, rec in mapped_by_idx.items():
        eid = rec["event"].get("id")
        if eid is not None:
            event_to_idx[str(eid)] = idx
            event_ids.append(str(eid))

    written=0
    odds_empty=0
    odds_errors=[]
    rate_infos=list(infos)

    for group in chunks(event_ids, 10):
        try:
            payloads, info = fetch_odds_multi(group)
            rate_infos.append(info)
        except Exception as e:
            odds_errors.append(f"odds/multi {group}: {str(e)[:220]}")
            payloads = []
            # fallback single
            for eid in group:
                try:
                    p, info = api_get("/odds", {"eventId": eid, "bookmakers": BOOKMAKERS})
                    rate_infos.append(info)
                    payloads.append(p)
                except Exception as ee:
                    odds_errors.append(f"odds {eid}: {str(ee)[:220]}")
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            eid = str(payload.get("id") or "")
            idx = event_to_idx.get(eid)
            if idx is None:
                continue
            mapped = mapped_by_idx[idx]["map"]
            clean = parse_odds_payload(payload, mapped)
            if not clean:
                odds_empty += 1
                continue
            clean["idx"] = idx
            clean["fixtureHome"] = mapped_by_idx[idx]["map"].get("event_home_canon")
            clean["fixtureAway"] = mapped_by_idx[idx]["map"].get("event_away_canon")
            fb_put(f"polla/odds/{idx}", clean)
            written += 1
            print(f"  odds idx {idx}: event {eid} escrito")

    fb_put("polla/oddsLastUpdate", {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "eventsFetched": len(events),
        "eventsMapped": len(mapped_by_idx),
        "eventIdsRequested": len(event_ids),
        "oddsWritten": written,
        "oddsEmpty": odds_empty,
        "bookmakers": BOOKMAKERS,
        "errors": errors + odds_errors,
        "rate": rate_infos[-3:],
        "unmappedSample": unmapped_sample,
    })

    print(f"Odds escritos: {written}")
    if errors or odds_errors:
        print("Errores:")
        for e in errors + odds_errors:
            print(" -", e)

if __name__ == "__main__":
    main()
