#!/usr/bin/env python3
"""
update_odds.py v2 diagnóstico/robusto para Odds-API.io

Qué corrige respecto de la versión anterior:
- Evita consultar 50+ partidos y quemar rate limit.
- Usa filtro bookmaker en /events para traer eventos que sí deberían tener cuotas.
- Pide como máximo ODDS_MAX_EVENTS partidos por ejecución, default 10.
- Si /odds/multi falla, guarda el cuerpo real del error HTTP en Firebase.
- Prueba con bookmakers configurados y, si falla, sin filtro de bookmakers.
- No hace fallback masivo que termine en 429.

Variables de entorno:
  ODDS_API_KEY          obligatorio
  ODDS_BOOKMAKERS      opcional. Default: Bet365,Unibet
  ODDS_EVENT_BOOKMAKER opcional. Default: primer bookmaker de ODDS_BOOKMAKERS
  ODDS_MAX_EVENTS      opcional. Default: 10

Firebase:
  /polla/odds
  /polla/oddsLastUpdate
"""
import os, json, re, unicodedata, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone, timedelta

DB_URL = "https://polla-gol-jateam-default-rtdb.firebaseio.com"
BASE = "https://api.odds-api.io/v3"

ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "").strip()
BOOKMAKERS = os.environ.get("ODDS_BOOKMAKERS", "Bet365,Unibet").strip() or "Bet365,Unibet"
EVENT_BOOKMAKER = os.environ.get("ODDS_EVENT_BOOKMAKER", "").strip() or BOOKMAKERS.split(",")[0].strip()
MAX_EVENTS = int(os.environ.get("ODDS_MAX_EVENTS", "10") or "10")

if not ODDS_API_KEY:
    raise SystemExit("Falta ODDS_API_KEY.")

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
    [71, "ghana", "panama"],
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
    "congo democratic republic":"rd del congo","dr congo kinshasa":"rd del congo",
    "korea republic":"corea del sur","south korea":"corea del sur","republic of korea":"corea del sur",
    "korea, republic of":"corea del sur"
}

PAIR = {frozenset((h, a)): (idx, h, a) for idx, h, a in FIX}

class ApiError(Exception):
    def __init__(self, url, status, body, reason=""):
        self.url = sanitize_url(url)
        self.status = status
        self.body = body
        self.reason = reason
        super().__init__(f"HTTP {status} {reason}: {body[:500]}")

def sanitize_url(url):
    return re.sub(r"apiKey=[^&]+", "apiKey=***", url)

def norm(s):
    s = ''.join(c for c in unicodedata.normalize('NFD', str(s or '')) if unicodedata.category(c) != 'Mn').lower()
    s = re.sub(r'[^a-z ]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()

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

def fb_put(path, obj):
    data = json.dumps(obj, ensure_ascii=False).encode()
    req = urllib.request.Request(
        f"{DB_URL}/{path}.json",
        data=data,
        method="PUT",
        headers={"Content-Type":"application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status

def build_url(path, params):
    params = dict(params or {})
    params["apiKey"] = ODDS_API_KEY
    # safe=',' evita que la lista Bet365,Unibet quede codificada como Bet365%2CUnibet.
    return f"{BASE}{path}?{urllib.parse.urlencode(params, safe=',')}"

def api_get(path, params):
    url = build_url(path, params)
    req = urllib.request.Request(url, headers={"Accept":"application/json"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            body = r.read().decode()
            data = json.loads(body) if body else None
            info = {
                "status": r.status,
                "remaining": r.headers.get("x-ratelimit-remaining"),
                "limit": r.headers.get("x-ratelimit-limit"),
                "reset": r.headers.get("x-ratelimit-reset"),
                "url": sanitize_url(url),
            }
            return data, info
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise ApiError(url, e.code, body, getattr(e, "reason", ""))

def event_home_away(ev):
    h = ev.get("home") or ev.get("homeTeam") or ev.get("local") or ev.get("teamHome")
    a = ev.get("away") or ev.get("awayTeam") or ev.get("visitor") or ev.get("teamAway")
    if isinstance(h, dict): h = h.get("name") or h.get("shortName")
    if isinstance(a, dict): a = a.get("name") or a.get("shortName")
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
    return {
        "idx": idx,
        "event_home_canon": ch,
        "event_away_canon": ca,
        "home": h,
        "away": a,
        "reversed": ch != fh
    }

def status_rank(ev):
    s = str(ev.get("status") or "").lower()
    if s in ("live", "in_play", "in-play", "inplay"):
        return 0
    try:
        d = datetime.fromisoformat(str(ev.get("date") or "").replace("Z","+00:00"))
        now = datetime.now(timezone.utc)
        if d >= now:
            return 1 + min(100000, int((d-now).total_seconds() // 3600))
        return 200000
    except Exception:
        return 150000

def choose_event(existing, candidate):
    if existing is None:
        return candidate
    return candidate if status_rank(candidate["event"]) < status_rank(existing["event"]) else existing

def fetch_events():
    errors, infos, events = [], [], []
    event_params_base = {"sport":"football", "limit":5000, "bookmaker":EVENT_BOOKMAKER}
    try:
        data, info = api_get("/events/live", {"sport":"football", "bookmaker":EVENT_BOOKMAKER})
        infos.append(info)
        if isinstance(data, list):
            events.extend(data)
    except Exception as e:
        errors.append(err_obj("events/live", e))
    try:
        to = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat().replace("+00:00","Z")
        data, info = api_get("/events", {**event_params_base, "to":to})
        infos.append(info)
        if isinstance(data, list):
            events.extend(data)
    except Exception as e:
        errors.append(err_obj("events", e))
    # Fallback sin bookmaker si no devuelve eventos.
    if not events:
        try:
            to = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat().replace("+00:00","Z")
            data, info = api_get("/events", {"sport":"football", "limit":1000, "to":to})
            infos.append(info)
            if isinstance(data, list):
                events.extend(data)
        except Exception as e:
            errors.append(err_obj("events-no-bookmaker", e))
    # dedupe
    out = {}
    for ev in events:
        eid = str(ev.get("id") or "")
        if eid:
            out[eid] = ev
    return list(out.values()), errors, infos

def unwrap_payloads(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("data", "odds", "events", "results"):
            if isinstance(data.get(k), list):
                return data[k]
        # Si es un dict por eventId
        vals = list(data.values())
        if vals and all(isinstance(x, dict) for x in vals):
            return vals
        return [data]
    return []

def fetch_odds_multi(event_ids):
    # 1) Con bookmakers.
    params = {"eventIds": ",".join(map(str, event_ids))}
    if BOOKMAKERS:
        params["bookmakers"] = BOOKMAKERS
    try:
        data, info = api_get("/odds/multi", params)
        return unwrap_payloads(data), info, None
    except Exception as e:
        first_error = err_obj("odds/multi-with-bookmakers", e)

    # 2) Sin bookmakers, por si algún bookmaker seleccionado no está permitido/disponible.
    try:
        data, info = api_get("/odds/multi", {"eventIds": ",".join(map(str, event_ids))})
        return unwrap_payloads(data), info, first_error
    except Exception as e:
        second_error = err_obj("odds/multi-no-bookmakers", e)
        return [], None, {"withBookmakers": first_error, "withoutBookmakers": second_error}

def fetch_odds_single(event_id):
    tries = []
    params = {"eventId": event_id}
    if BOOKMAKERS:
        tries.append({**params, "bookmakers": BOOKMAKERS})
    tries.append(params)
    errors = []
    for params in tries:
        try:
            data, info = api_get("/odds", params)
            return unwrap_payloads(data)[0] if unwrap_payloads(data) else data, info, errors
        except Exception as e:
            errors.append(err_obj("odds-single", e))
    return None, None, errors

def err_obj(where, e):
    if isinstance(e, ApiError):
        return {"where": where, "status": e.status, "reason": e.reason, "body": e.body[:1000], "url": e.url}
    return {"where": where, "error": str(e)[:1000]}

def market_ml(markets):
    if not isinstance(markets, list):
        return None
    names = {"ml","moneyline","match winner","match result","1x2","winner","full time result"}
    for m in markets:
        name = norm(m.get("name") or m.get("market") or "")
        if name in names or name.replace(" ","") in {"1x2","ml"}:
            odds = m.get("odds") or []
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
    if not isinstance(payload, dict):
        return None
    bookies = payload.get("bookmakers") or {}
    if not isinstance(bookies, dict):
        return None

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

    avg = {k: (round(sum(v)/len(v), 3) if v else None) for k, v in avg_acc.items()}

    implied_raw = {}
    source_for_prob = {}
    for key in ("home","draw","away"):
        source_for_prob[key] = best[key]["odds"] or avg[key]
        implied_raw[key] = (1 / source_for_prob[key]) if source_for_prob[key] else None
    total = sum(v for v in implied_raw.values() if v)
    implied = {k: round((v/total)*100, 1) if v and total else None for k,v in implied_raw.items()}

    fav, fav_val = None, None
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
        "eventBookmakerFilter": EVENT_BOOKMAKER,
        "updatedAt": latest or datetime.now(timezone.utc).isoformat(),
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
    }

def chunks(items, n):
    for i in range(0, len(items), n):
        yield items[i:i+n]

def main():
    run_started = datetime.now(timezone.utc).isoformat()
    events, errors, infos = fetch_events()
    print(f"Eventos recibidos Odds-API.io: {len(events)}")

    mapped_by_idx, unmapped_sample = {}, []
    for ev in events:
        mp = map_event(ev)
        if not mp:
            if len(unmapped_sample) < 15:
                h, a = event_home_away(ev)
                league = ev.get("league") or {}
                if isinstance(league, dict):
                    league = league.get("name") or league.get("slug")
                unmapped_sample.append({"id":ev.get("id"),"home":h,"away":a,"league":league,"status":ev.get("status"),"date":ev.get("date")})
            continue
        idx = mp["idx"]
        mapped_by_idx[idx] = choose_event(mapped_by_idx.get(idx), {"event":ev,"map":mp})

    selected = sorted(mapped_by_idx.items(), key=lambda kv: status_rank(kv[1]["event"]))[:MAX_EVENTS]
    event_to_idx = {str(rec["event"].get("id")): idx for idx, rec in selected}
    event_ids = list(event_to_idx.keys())

    print(f"Eventos mapeados a partidos de la polla: {len(mapped_by_idx)}")
    print(f"Eventos seleccionados para pedir odds: {len(event_ids)} / máximo {MAX_EVENTS}")

    written, odds_empty = 0, 0
    odds_errors, payload_samples = [], []
    rate_infos = list(infos)

    for group in chunks(event_ids, 10):
        payloads, info, err = fetch_odds_multi(group)
        if info:
            rate_infos.append(info)
        if err:
            odds_errors.append(err)

        # Si multi no devolvió nada, probamos single SOLO para este grupo limitado.
        if not payloads:
            for eid in group:
                payload, info, errs = fetch_odds_single(eid)
                if info:
                    rate_infos.append(info)
                if errs:
                    odds_errors.extend(errs)
                if payload:
                    payloads.append(payload)

        for payload in payloads:
            if len(payload_samples) < 3:
                payload_samples.append({
                    "id": payload.get("id") if isinstance(payload, dict) else None,
                    "keys": list(payload.keys())[:12] if isinstance(payload, dict) else str(type(payload)),
                    "bookmakersCount": len(payload.get("bookmakers", {}) or {}) if isinstance(payload, dict) else None,
                    "home": payload.get("home") if isinstance(payload, dict) else None,
                    "away": payload.get("away") if isinstance(payload, dict) else None,
                })
            if not isinstance(payload, dict):
                continue
            eid = str(payload.get("id") or "")
            idx = event_to_idx.get(eid)
            if idx is None:
                # Algunos endpoints podrían devolver id como number o eventId.
                eid2 = str(payload.get("eventId") or "")
                idx = event_to_idx.get(eid2)
            if idx is None:
                continue
            mapped = mapped_by_idx[idx]["map"]
            clean = parse_odds_payload(payload, mapped)
            if not clean:
                odds_empty += 1
                continue
            clean["idx"] = idx
            clean["fixtureHome"] = mapped.get("event_home_canon")
            clean["fixtureAway"] = mapped.get("event_away_canon")
            fb_put(f"polla/odds/{idx}", clean)
            written += 1
            print(f"  odds idx {idx}: event {eid or payload.get('eventId')} escrito")

    diag = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "runStartedAt": run_started,
        "eventsFetched": len(events),
        "eventsMapped": len(mapped_by_idx),
        "eventIdsSelected": len(event_ids),
        "selectedEventIds": event_ids,
        "oddsWritten": written,
        "oddsEmpty": odds_empty,
        "bookmakers": BOOKMAKERS,
        "eventBookmakerFilter": EVENT_BOOKMAKER,
        "maxEvents": MAX_EVENTS,
        "errors": errors + odds_errors,
        "rate": rate_infos[-6:],
        "unmappedSample": unmapped_sample,
        "payloadSamples": payload_samples,
    }
    fb_put("polla/oddsLastUpdate", diag)

    print(f"Odds escritos: {written}")
    if errors or odds_errors:
        print("Errores resumidos:")
        for e in (errors + odds_errors)[:10]:
            print(" -", json.dumps(e, ensure_ascii=False)[:900])

if __name__ == "__main__":
    main()
