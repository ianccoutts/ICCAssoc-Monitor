#!/usr/bin/env python3
"""
ICC Associates Deal Flow Monitor — Auto-builder
Runs on GitHub Actions schedule, pulls HubSpot, writes index.html
"""
import os, json, datetime, urllib.request, urllib.error

TOKEN   = os.environ["HUBSPOT_TOKEN"]
PORTAL  = "6564339"
FEE_PCT = 0.01
SNAPSHOT_DATE = datetime.date.today().strftime("%b %d, %Y")

STAGE_MAP = {
    "1064826":"Prospect","1064827":"Pre-Qual","33350473":"Hold",
    "1064828":"Agreement","1064829":"Submission","1240317":"Term Sheet",
    "1064830":"UW","1064831":"Approved","1064832":"CTC",
    "1064833":"Closed","1394113":"Stalled","1148641":"Dead"
}
ACTIVE_STAGES = {"Prospect","Pre-Qual","Agreement","Submission","Term Sheet","UW","Approved","CTC"}
EXCLUDE_VALS  = ["1064833","1148641","1064826","33350473","1394113"]  # active query excludes these

def hs_search(payload):
    url  = "https://api.hubapi.com/crm/v3/objects/deals/search"
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type":  "application/json"
    })
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def fetch_deals(filter_groups, exclude_stages=None):
    props = ["dealname","dealstage","amount","closedate","hs_lastmodifieddate",
             "lender_name","property_address","hubspot_owner_id","createdate",
             "description","hs_next_step"]
    all_deals, after = [], None
    for _ in range(15):          # max 15 pages = 1,500 deals
        payload = {
            "filterGroups": filter_groups,
            "properties":   props,
            "sorts": [{"propertyName":"hs_lastmodifieddate","direction":"DESCENDING"}],
            "limit": 100
        }
        if after:
            payload["after"] = after
        resp = hs_search(payload)
        results = resp.get("results", [])
        for d in results:
            p  = d["properties"]
            sn = STAGE_MAP.get(p.get("dealstage",""), "Pre-Qual")
            if exclude_stages and sn in exclude_stages:
                continue
            cl_raw = p.get("closedate") or ""
            mod_raw= p.get("hs_lastmodifieddate") or ""
            all_deals.append({
                "id":      d["id"],
                "name":    (p.get("dealname") or "").strip(),
                "addr":    (p.get("property_address") or "").strip(),
                "amt":     float(p.get("amount") or 0),
                "stg":     p.get("dealstage",""),
                "cl":      cl_raw[:10] if cl_raw else None,
                "mod":     mod_raw[:10] if mod_raw else "",
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

# Fetch active + prospect deals
active = fetch_deals([{
    "filters":[
        {"propertyName":"pipeline","operator":"EQ","value":"1064825"},
        {"propertyName":"dealstage","operator":"NOT_IN","values":EXCLUDE_VALS}
    ]
}])

# Fetch closed/dead sample
closed = fetch_deals([{
    "filters":[
        {"propertyName":"pipeline","operator":"EQ","value":"1064825"},
        {"propertyName":"dealstage","operator":"IN","values":["1064833","1148641"]}
    ]
}])[:50]  # cap at 50 for the file

print(f"Active/prospect deals: {len(active)}")
print(f"Closed/dead sample:    {len(closed)}")

ACTIVE_JSON = json.dumps(active, separators=(',',':'))
CLOSED_JSON = json.dumps(closed, separators=(',',':'))

# ── Read logo ──────────────────────────────────────────────────────────────────
logo_path = os.path.join(os.path.dirname(__file__), "logo_b64.txt")
with open(logo_path) as f:
    LOGO = f.read().strip()

# ── Read template, inject data ─────────────────────────────────────────────────
tpl_path = os.path.join(os.path.dirname(__file__), "monitor_template.html")
with open(tpl_path) as f:
    html = f.read()

html = html.replace("%%LOGO%%",         LOGO)
html = html.replace("%%ACTIVE_DATA%%",  ACTIVE_JSON)
html = html.replace("%%CLOSED_DATA%%",  CLOSED_JSON)
html = html.replace("%%SNAPSHOT_DATE%%",SNAPSHOT_DATE)

out = os.path.join(os.path.dirname(__file__), "index.html")
with open(out, "w") as f:
    f.write(html)

print(f"index.html written ({len(html):,} chars)")
