#!/usr/bin/env python3
"""
Actualiza los resultados reales del Mundial 2026 en tu Firebase Realtime Database.
Consulta football-data.org (tier gratis, competencia WC) y escribe los partidos
FINALIZADOS en /polla/results/<idx>.json — tu HTML los muestra en vivo.

Variables de entorno (las pone GitHub Actions):
  FD_TOKEN  -> tu token gratis de football-data.org   (OBLIGATORIO)
Config fija abajo: DB_URL (tu base de Firebase).
"""
import os, json, re, unicodedata, urllib.request
from datetime import datetime, timezone, timedelta

# === TU BASE DE FIREBASE (cambiala si alguna vez cambia el proyecto) ===
DB_URL = "https://polla-gol-jateam-default-rtdb.firebaseio.com"
# =======================================================================

FD_TOKEN = os.environ.get("FD_TOKEN", "").strip()
if not FD_TOKEN:
    raise SystemExit("Falta FD_TOKEN (token de football-data.org).")

# Mapeo idx -> (equipo local, equipo visita) en nombres normalizados
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

# Alias: nombre de la API (en ingles, normalizado) -> nombre canonico (el de FIX)
ALIAS = {
 "mexico":"mexico","south africa":"sudafrica","korea republic":"corea del sur",
 "south korea":"corea del sur","republic of korea":"corea del sur","korea, republic of":"corea del sur",
 "czechia":"republica checa","czech republic":"republica checa","switzerland":"suiza",
 "bosnia and herzegovina":"bosnia y herzegovina","bosniaherzegovina":"bosnia y herzegovina",
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
}

def norm(s):
    s=''.join(c for c in unicodedata.normalize('NFD',str(s or '')) if unicodedata.category(c)!='Mn').lower()
    s=re.sub(r'[^a-z ]','',s); return re.sub(r'\s+',' ',s).strip()

def canon(*names):
    for n in names:
        k=norm(n)
        if not k: continue
        if k in ALIAS: return ALIAS[k]
        # tal cual (cubre nombres ya iguales)
        for _,h,a in FIX:
            if k==h or k==a: return k
    return None

# indice por par {local,visita}
PAIR={}
for idx,h,a in FIX:
    PAIR[frozenset((h,a))]=(idx,h,a)

# equipo canonico -> [nombre_es, iso, emoji]
TEAMS = {"republica checa": ["República Checa","cz","🇨🇿"],"sudafrica": ["Sudáfrica","za","🇿🇦"],"mexico": ["México","mx","🇲🇽"],"corea del sur": ["Corea del Sur","kr","🇰🇷"],"suiza": ["Suiza","ch","🇨🇭"],"bosnia y herzegovina": ["Bosnia y Herzegovina","ba","🇧🇦"],"canada": ["Canadá","ca","🇨🇦"],"qatar": ["Qatar","qa","🇶🇦"],"estados unidos": ["Estados Unidos","us","🇺🇸"],"australia": ["Australia","au","🇦🇺"],"turquia": ["Turquía","tr","🇹🇷"],"paraguay": ["Paraguay","py","🇵🇾"],"escocia": ["Escocia","gb-sct","🏴󠁧󠁢󠁳󠁣󠁴󠁿"],"marruecos": ["Marruecos","ma","🇲🇦"],"brasil": ["Brasil","br","🇧🇷"],"haiti": ["Haití","ht","🇭🇹"],"paises bajos": ["Países Bajos","nl","🇳🇱"],"suecia": ["Suecia","se","🇸🇪"],"tunez": ["Túnez","tn","🇹🇳"],"japon": ["Japón","jp","🇯🇵"],"alemania": ["Alemania","de","🇩🇪"],"costa de marfil": ["Costa de Marfil","ci","🇨🇮"],"ecuador": ["Ecuador","ec","🇪🇨"],"curazao": ["Curazao","cw","🇨🇼"],"espana": ["España","es","🇪🇸"],"arabia saudita": ["Arabia Saudita","sa","🇸🇦"],"uruguay": ["Uruguay","uy","🇺🇾"],"cabo verde": ["Cabo Verde","cv","🇨🇻"],"belgica": ["Bélgica","be","🇧🇪"],"iran": ["Irán","ir","🇮🇷"],"nueva zelanda": ["Nueva Zelanda","nz","🇳🇿"],"egipto": ["Egipto","eg","🇪🇬"],"argentina": ["Argentina","ar","🇦🇷"],"austria": ["Austria","at","🇦🇹"],"jordania": ["Jordania","jo","🇯🇴"],"argelia": ["Argelia","dz","🇩🇿"],"francia": ["Francia","fr","🇫🇷"],"irak": ["Irak","iq","🇮🇶"],"noruega": ["Noruega","no","🇳🇴"],"senegal": ["Senegal","sn","🇸🇳"],"portugal": ["Portugal","pt","🇵🇹"],"uzbekistan": ["Uzbekistán","uz","🇺🇿"],"colombia": ["Colombia","co","🇨🇴"],"rd del congo": ["RD del Congo","cd","🇨🇩"],"inglaterra": ["Inglaterra","gb-eng","🏴󠁧󠁢󠁥󠁮󠁧󠁿"],"ghana": ["Ghana","gh","🇬🇭"],"panama": ["Panamá","pa","🇵🇦"],"croacia": ["Croacia","hr","🇭🇷"]}

STAGE = {  # stage de la API -> (etiqueta, orden)
 "LAST_32":("16vos de final",1),"ROUND_OF_32":("16vos de final",1),
 "LAST_16":("8vos de final",2),"ROUND_OF_16":("8vos de final",2),
 "QUARTER_FINALS":("4tos de final",3),"QUARTER_FINAL":("4tos de final",3),
 "SEMI_FINALS":("Semifinal",4),"SEMI_FINAL":("Semifinal",4),
 "THIRD_PLACE":("3er puesto",5),"3RD_PLACE":("3er puesto",5),
 "FINAL":("Final",6),
}

# Overrides manuales de marcador al término del segundo tiempo cuando la API no entrega regularTime
# o cuando ya sabemos el marcador correcto 90' + descuentos.
# Formato: par canonico -> goles por equipo canonico.
KO_90_OVERRIDES = {
    frozenset(("belgica", "senegal")): {"belgica": 2, "senegal": 2, "source": "manual_belgica_senegal_90_descuentos"},
}

def manual_ko_90_override(m):
    ht=m.get("homeTeam",{}) or {}
    at=m.get("awayTeam",{}) or {}
    ch=canon(ht.get("name"), ht.get("shortName"), ht.get("tla"))
    ca=canon(at.get("name"), at.get("shortName"), at.get("tla"))
    if not ch or not ca:
        return None
    ov=KO_90_OVERRIDES.get(frozenset((ch, ca)))
    if not ov:
        return None
    h=ov.get(ch)
    a=ov.get(ca)
    if h is None or a is None:
        return None
    return int(h), int(a), ov.get("source", "manual_override")
def team_obj(tm):
    """{name,iso,flag} a partir de un equipo de la API (o placeholder)."""
    if not tm: return {"name":"Por definir","iso":"","flag":""}
    c=canon(tm.get("name"),tm.get("shortName"),tm.get("tla"))
    if c and c in TEAMS:
        es,iso,fl=TEAMS[c]; return {"name":es,"iso":iso,"flag":fl}
    return {"name":tm.get("name") or "Por definir","iso":"","flag":""}

def fetch():
    req=urllib.request.Request("https://api.football-data.org/v4/competitions/WC/matches",
        headers={"X-Auth-Token":FD_TOKEN})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def fb_put(path, obj):
    """Escribe un objeto JSON en Firebase y devuelve el status HTTP."""
    data=json.dumps(obj, ensure_ascii=False).encode()
    req=urllib.request.Request(f"{DB_URL}/{path}.json", data=data, method="PUT",
        headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status

def put(idx,l,v):
    return fb_put(f"polla/results/{idx}", {"l":l,"v":v})

def score_goals(m):
    """Devuelve el mejor marcador disponible de football-data.org para vivo/final."""
    sc=(m.get("score") or {})
    ft=sc.get("fullTime") or {}
    ht=sc.get("halfTime") or {}
    # Para partidos en juego, football-data suele ir llenando score.fullTime como marcador actual.
    # Si no viene, dejamos respaldo con halfTime.
    h=ft.get("home")
    a=ft.get("away")
    if h is None or a is None:
        h=ht.get("home")
        a=ht.get("away")
    if h is None or a is None:
        return None, None
    return int(h), int(a)

def score_regular_90(m):
    """Resultado válido para la polla en eliminatorias: final del segundo tiempo.

    Regla real:
      - Cuenta hasta el término del segundo tiempo: 90' + descuentos.
      - Alargue y penales NO cuentan para puntos.
      - Si hay regularTime, se usa regularTime.
      - Si no hay regularTime y hay override manual, se usa el override.
      - Si no hay regularTime ni override, pero extraTime viene como goles del alargue,
        se infiere: marcador_90 = fullTime - extraTime.
      - Si no se puede saber el marcador a los 90' + descuentos, no se cierra puntaje
        para evitar entregar puntos con el resultado de alargue.
    """
    sc=(m.get("score") or {})
    ft=sc.get("fullTime") or {}
    rt=sc.get("regularTime") or {}
    et=sc.get("extraTime") or {}
    dur=str(sc.get("duration") or "").upper()

    # 1) Fuente ideal: regularTime, que football-data v4 define como marcador tras 90'.
    h=rt.get("home")
    a=rt.get("away")
    if h is not None and a is not None:
        return int(h), int(a), "regularTime", True

    # 2) Override manual conocido, útil cuando la API no entrega regularTime.
    ov=manual_ko_90_override(m)
    if ov:
        h,a,src=ov
        return h, a, src, True

    # 3) Si hubo alargue/penales y extraTime es DELTA de goles en alargue, inferir.
    fh=ft.get("home"); fa=ft.get("away")
    eh=et.get("home"); ea=et.get("away")
    overtime_like = ("EXTRA" in dur) or ("PENAL" in dur) or eh is not None or ea is not None
    if overtime_like:
        if fh is not None and fa is not None and eh is not None and ea is not None:
            try:
                fh,fa,eh,ea = int(fh), int(fa), int(eh), int(ea)
                # Solo inferir si extraTime parece goles DEL alargue, no marcador acumulado.
                if 0 <= eh <= fh and 0 <= ea <= fa and (eh < fh or ea < fa):
                    return fh-eh, fa-ea, "fullTime_minus_extraTime", False
            except Exception:
                pass
        # Si hubo alargue/penales y no tengo 90', no uso fullTime: sería incorrecto.
        return None, None, "missing_regularTime", False

    # 4) Partido resuelto dentro del segundo tiempo: fullTime es válido al estar FINISHED.
    if fh is None or fa is None:
        return None, None, "fullTime", False
    return int(fh), int(fa), "fullTime", False

def should_close_ko_polla(m):
    """True solo cuando ya corresponde asignar puntos de KO."""
    raw = str(m.get("status") or "").upper()
    sc = (m.get("score") or {})
    rt = sc.get("regularTime") or {}
    has_regular = rt.get("home") is not None and rt.get("away") is not None

    if raw in ("EXTRA_TIME", "PENALTY_SHOOTOUT") and (has_regular or manual_ko_90_override(m)):
        return True

    if raw == "FINISHED":
        return True

    return False

def parse_utc(dt):
    if not dt:
        return None
    try:
        return datetime.fromisoformat(str(dt).replace("Z", "+00:00"))
    except Exception:
        return None

def effective_status(m):
    """
    football-data.org a veces mantiene partidos como TIMED/SCHEDULED aunque ya empezó.
    Para que el HTML muestre el partido en vivo, forzamos estado IN_PLAY por horario
    si el partido está entre su hora de inicio y una ventana razonable de duración.
    """
    raw = str(m.get("status") or "").upper()
    if raw in ("IN_PLAY", "PAUSED", "LIVE", "EXTRA_TIME", "PENALTY_SHOOTOUT", "FINISHED"):
        return raw, False

    kick = parse_utc(m.get("utcDate"))
    now = datetime.now(timezone.utc)
    if kick and kick <= now <= (kick + timedelta(hours=2, minutes=45)):
        return "IN_PLAY", True

    return raw, False

def live_rec(m, idx, ch, ca, fh, fa):
    """Registro liviano para /polla/live/<idx>: status + marcador actual/final si existe."""
    gh,ga=score_goals(m)
    l=v=None
    if gh is not None and ga is not None:
        # Ajustar marcador al orden local/visita del HTML si la API trae el partido al revés.
        if ch==fh:
            l,v=gh,ga
        else:
            l,v=ga,gh
    st_eff, forced = effective_status(m)
    return {
        "status": st_eff,
        "rawStatus": m.get("status"),
        "forcedLiveByTime": forced,
        "l": l,
        "v": v,
        "date": m.get("utcDate"),
        "venue": m.get("venue"),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }

def main():
    out=fetch(); ms=out.get("matches",[])
    print(f"Partidos en la API: {len(ms)}")
    wrote=0; meta=0; meta_venue=0; meta_no_venue=0; live_written=0; live_active=0; forced_live_by_time=0; unmatched=[]
    for m in ms:
        st=(m.get("stage") or "").upper()
        if st and "GROUP" not in st: continue
        ht=m.get("homeTeam",{}) or {}; at=m.get("awayTeam",{}) or {}
        ch=canon(ht.get("name"),ht.get("shortName"),ht.get("tla"))
        ca=canon(at.get("name"),at.get("shortName"),at.get("tla"))
        hit=PAIR.get(frozenset((ch,ca))) if (ch and ca) else None
        if not hit:
            if m.get("status")=="FINISHED": unmatched.append(f"{ht.get('name')} vs {at.get('name')}")
            continue
        idx,fh,fa=hit
        # meta (fecha + estadio) siempre, aunque no se haya jugado
        venue=m.get("venue")
        fb_put(f"polla/meta/{idx}", {"date":m.get("utcDate"),"venue":venue})
        meta+=1
        if venue: meta_venue+=1
        else: meta_no_venue+=1

        # estado + marcador vivo/provisional/final para el HTML
        rec_live=live_rec(m, idx, ch, ca, fh, fa)
        fb_put(f"polla/live/{idx}", rec_live)
        live_written+=1
        if str(rec_live.get("status") or "").upper() in ("IN_PLAY","PAUSED","LIVE","EXTRA_TIME","PENALTY_SHOOTOUT"):
            live_active+=1
        if rec_live.get("forcedLiveByTime"):
            forced_live_by_time+=1

        # resultado final: solo se escribe en /polla/results cuando football-data marca FINISHED
        if m.get("status")!="FINISHED": continue
        l,v=rec_live.get("l"),rec_live.get("v")
        if l is None or v is None: continue
        put(idx,int(l),int(v)); wrote+=1
        print(f"  idx {idx}: {ch} {l}-{v} {ca}")
    print(f"Meta (fecha/estadio) escritas: {meta}")
    # --- ELIMINATORIAS -> polla/ko ---
    ko=0
    ko_live_active=0
    ko_polla_closed=0
    for m in ms:
        st=(m.get("stage") or "").upper()
        if not st or "GROUP" in st: continue
        lab,order=STAGE.get(st,(st.replace("_"," ").title(),9))
        sc=(m.get("score") or {}); ft=sc.get("fullTime") or {}; rt=sc.get("regularTime") or {}; et=sc.get("extraTime") or {}; pen=sc.get("penalties") or {}

        st_eff, forced = effective_status(m)
        live_h, live_a = score_goals(m)
        close_polla = should_close_ko_polla(m)

        p90h=p90a=score_used=None
        regular_available=False
        if close_polla:
            p90h,p90a,score_used,regular_available=score_regular_90(m)
            if p90h is not None and p90a is not None:
                ko_polla_closed += 1

        if st_eff in ("IN_PLAY","PAUSED","LIVE","EXTRA_TIME","PENALTY_SHOOTOUT"):
            ko_live_active += 1

        official_h = ft.get("home") if str(m.get("status") or "").upper()=="FINISHED" else None
        official_a = ft.get("away") if str(m.get("status") or "").upper()=="FINISHED" else None

        rec={
          "id":m.get("id"),"stage":lab,"stageRaw":st,"order":order,"date":m.get("utcDate"),
          "status":st_eff,"rawStatus":m.get("status"),"forcedLiveByTime":forced,
          "venue":m.get("venue"),
          "home":team_obj(m.get("homeTeam")),"away":team_obj(m.get("awayTeam")),

          # Marcador vivo/provisional. Sirve solo para mostrar, NO para puntuar.
          "liveHg":live_h,"liveAg":live_a,

          # hg/ag y pollaHg/pollaAg se escriben solo cuando terminó el segundo tiempo.
          # Es decir: FINISHED en tiempo regular, o regularTime disponible al pasar a alargue/penales.
          "hg":p90h,"ag":p90a,
          "pollaHg":p90h,"pollaAg":p90a,
          "pollaClosed": bool(p90h is not None and p90a is not None),
          "scoreUsedForPolla":score_used,
          "regularTimeAvailable":regular_available,
          "rule":"90min_mas_descuentos_final_segundo_tiempo",

          "officialHg":official_h,"officialAg":official_a,
          "regularHg":rt.get("home"),"regularAg":rt.get("away"),
          "extraHg":et.get("home"),"extraAg":et.get("away"),
          "ph":pen.get("home"),"pa":pen.get("away"),"winner":sc.get("winner"),"duration":sc.get("duration"),
          "updatedAt": datetime.now(timezone.utc).isoformat(),
        }
        fb_put(f"polla/ko/{m.get('id')}", rec)
        ko+=1
    fb_put("polla/lastUpdate", {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "apiMatches": len(ms),
        "groupMetaWritten": meta,
        "groupMetaWithVenue": meta_venue,
        "groupMetaWithoutVenue": meta_no_venue,
        "finishedResultsWritten": wrote,
        "liveRowsWritten": live_written,
        "liveMatchesActive": live_active,
        "forcedLiveByTime": forced_live_by_time,
        "knockoutWritten": ko,
        "knockoutLiveActive": ko_live_active,
        "knockoutPollaClosed": ko_polla_closed,
        "unmatchedFinished": unmatched,
    })
    print(f"Eliminatorias escritas: {ko}")
    print(f"Escritos: {wrote}")
    print(f"Meta con estadio: {meta_venue} / {meta} (sin estadio: {meta_no_venue})")
    print(f"Live escritos: {live_written} (en juego: {live_active}, forzados por horario: {forced_live_by_time})")
    if unmatched:
        print("SIN MAPEAR (avisar para agregar alias):")
        for u in unmatched: print("  -",u)

if __name__=="__main__":
    main()