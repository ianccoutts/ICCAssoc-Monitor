#!/usr/bin/env python3
"""ICC Associates Deal Flow Monitor — Auto-builder + Morning Email"""
import os, json, datetime, urllib.request, urllib.error, sys, smtplib
from email.mime.text import MIMEText

TOKEN         = os.environ["HUBSPOT_TOKEN"]
PORTAL        = "6564339"
SNAPSHOT_DATE = datetime.date.today().strftime("%b %d, %Y")
TODAY         = datetime.date.today()

STAGE_MAP = {
    "1064826":"Prospect","1064827":"Pre-Qual","33350473":"Hold",
    "1064828":"Agreement","1064829":"Submission","1240317":"Term Sheet",
    "1064830":"UW","1064831":"Approved","1064832":"CTC",
    "1064833":"Closed","1394113":"Stalled","1148641":"Dead"
}
ACTIVE_STAGES  = {"Prospect","Pre-Qual","Agreement","Submission","Term Sheet","UW","Approved","CTC"}
EXCLUDE_STAGES = ["1064833","1148641","33350473","1394113"]

def hs_search(payload):
    url  = "https://api.hubapi.com/crm/v3/objects/deals/search"
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type":  "application/json"
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"HubSpot API error {e.code}: {body}", file=sys.stderr)
        raise

def fetch_deals(filter_groups):
    props = ["dealname","dealstage","amount","closedate","hs_lastmodifieddate",
             "lender_name","property_address","hubspot_owner_id","createdate",
             "description","hs_next_step"]
    all_deals, after = [], None
    for page in range(15):
        payload = {
            "filterGroups": filter_groups,
            "properties":   props,
            "sorts": [{"propertyName":"hs_lastmodifieddate","direction":"DESCENDING"}],
            "limit": 100
        }
        if after:
            payload["after"] = after
        resp    = hs_search(payload)
        results = resp.get("results", [])
        print(f"  Page {page+1}: {len(results)} deals")
        for d in results:
            p   = d["properties"]
            cl  = (p.get("closedate") or "")[:10] or None
            mod = (p.get("hs_lastmodifieddate") or "")[:10]
            all_deals.append({
                "id":      d["id"],
                "name":    (p.get("dealname") or "").strip(),
                "addr":    (p.get("property_address") or "").strip(),
                "amt":     float(p.get("amount") or 0),
                "stg":     p.get("dealstage",""),
                "cl":      cl,
                "mod":     mod,
                "lnd":     (p.get("lender_name") or "").strip(),
                "own":     p.get("hubspot_owner_id",""),
                "desc":    (p.get("description") or "").strip(),
                "next":    (p.get("hs_next_step") or "").strip(),
                "created": (p.get("createdate") or "")[:10],
            })
        nxt = resp.get("paging",{}).get("next",{}).get("after")
        if not nxt:
            break
        after = nxt
    return all_deals

def days_since(date_str):
    if not date_str:
        return 999
    try:
        d = datetime.date.fromisoformat(date_str[:10])
        return (TODAY - d).days
    except:
        return 999

print("Fetching active + prospect deals...")
active = fetch_deals([{"filters":[
    {"propertyName":"pipeline","operator":"EQ","value":"1064825"},
    {"propertyName":"dealstage","operator":"NOT_IN","values":EXCLUDE_STAGES}
]}])
active = [d for d in active if STAGE_MAP.get(d["stg"],"") in ACTIVE_STAGES]

print(f"\nFetching closed/dead sample (recent 60)...")
closed = fetch_deals([{"filters":[
    {"propertyName":"pipeline","operator":"EQ","value":"1064825"},
    {"propertyName":"dealstage","operator":"IN","values":["1064833","1148641"]}
]}])[:60]

print(f"\nActive/prospect deals: {len(active)}")
print(f"Closed/dead sample:    {len(closed)}")

ACTIVE_JSON = json.dumps(active, separators=(",",":"))
CLOSED_JSON = json.dumps(closed, separators=(",",":"))

HERE     = os.path.dirname(os.path.abspath(__file__))
logo_path= os.path.join(HERE, "logo_b64.txt")
tpl_path = os.path.join(HERE, "monitor_template.html")
out_path = os.path.join(HERE, "index.html")

with open(logo_path) as f: LOGO = f.read().strip()
with open(tpl_path) as f: html = f.read()

html = html.replace("%%LOGO%%",          LOGO)
html = html.replace("%%ACTIVE_DATA%%",   ACTIVE_JSON)
html = html.replace("%%CLOSED_DATA%%",   CLOSED_JSON)
html = html.replace("%%SNAPSHOT_DATE%%", SNAPSHOT_DATE)

with open(out_path, "w") as f: f.write(html)
print(f"index.html written ({len(html):,} chars)")

# ── MORNING BRIEFING (optional — only runs if SMTP_PASS secret is set) ─────────
smtp_pass = os.environ.get("SMTP_PASS","")
if smtp_pass:
    try:
        overdue=[d for d in active if d.get("cl") and d["cl"]<TODAY.isoformat() and STAGE_MAP.get(d["stg"])!="Prospect"]
        stale30=[d for d in active if days_since(d.get("mod",""))>30]
        closing7=[d for d in active if d.get("cl") and TODAY.isoformat()<=d["cl"]<=(TODAY+datetime.timedelta(7)).isoformat()]

        lines=["ICC Associates — Deal Flow Briefing","="*48,f"Date: {SNAPSHOT_DATE}",f"Active deals: {len(active)}  |  Pipeline volume: ${sum(d['amt'] for d in active)/1e6:.1f}M",""]
        if closing7:
            lines+=["CLOSING THIS WEEK:"]+[f"  • {d['name']} — {d['cl']} — {d['lnd'] or 'No lender'}" for d in closing7]+[""]
        if overdue:
            lines+=["OVERDUE CLOSE DATES:"]+[f"  ⚠ {d['name']} — was {d['cl']}" for d in overdue[:5]]+[""]
        if stale30:
            lines+=["STALLED (30d+ no activity):"]+[f"  • {d['name']} — {days_since(d.get('mod',''))}d — {STAGE_MAP.get(d['stg'],'')}" for d in stale30[:5]]+[""]
        lines+=["View monitor: https://ianccoutts.github.io/ICCAssoc-Monitor"]

        msg=MIMEText("\n".join(lines))
        msg["Subject"]=f"ICC Deal Briefing — {SNAPSHOT_DATE}"
        msg["From"]="iancoutts@icc-associates.com"
        msg["To"]="iancoutts@icc-associates.com"
        with smtplib.SMTP_SSL("smtp.gmail.com",465) as s:
            s.login("iancoutts@icc-associates.com", smtp_pass)
            s.send_message(msg)
        print("Morning briefing email sent")
    except Exception as e:
        print(f"Email skipped: {e}")
