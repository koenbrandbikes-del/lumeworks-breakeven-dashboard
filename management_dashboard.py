#!/usr/bin/env python3
"""Genereert management_dashboard.html: Meta ROAS, Google ROAS en MER per periode.

Input (in dezelfde map):
  trackbee_data.json  — per dag: {"Meta":{"spend":N,"revenue":N},"Google":{"spend":N,"revenue":N}}
                         (wordt al elk uur ververst door de bestaande cloud-routine)
  shopify_daily.json  — per dag: totale Shopify-omzet incl. BTW (total_sales), vers
                         opgehaald via Shopify MCP ShopifyQL door de routine die dit
                         script aanroept.

Output: management_dashboard.html in de huidige map.
"""
import json
import datetime
import sys
from pathlib import Path

HERE = Path(__file__).parent


def load_json(name):
    p = HERE / name
    if not p.exists():
        print(f"FOUT: {name} niet gevonden in {HERE}")
        sys.exit(1)
    return json.loads(p.read_text())


def eur(v):
    s = f"{v:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"€{s}"


def x2(v):
    return f"{v:.2f}×"


def period_bounds(name, today, earliest):
    if name == "vandaag":
        return today, today
    if name == "gisteren":
        y = today - datetime.timedelta(days=1)
        return y, y
    if name == "week":
        start = today - datetime.timedelta(days=today.weekday())
        return start, today
    if name == "maand":
        start = today.replace(day=1)
        return start, today
    if name == "totaal":
        return earliest, today
    raise ValueError(name)


def sum_in_range(daily, frm, to, picker):
    total = 0.0
    for d, v in daily.items():
        dd = datetime.date.fromisoformat(d)
        if dd < frm or dd > to:
            continue
        total += picker(v)
    return round(total, 2)


def build_period(name, label, today, earliest, trackbee, shopify_daily):
    frm, to = period_bounds(name, today, earliest)
    meta_spend = sum_in_range(trackbee, frm, to, lambda v: v["Meta"]["spend"])
    meta_rev = sum_in_range(trackbee, frm, to, lambda v: v["Meta"]["revenue"])
    google_spend = sum_in_range(trackbee, frm, to, lambda v: v["Google"]["spend"])
    google_rev = sum_in_range(trackbee, frm, to, lambda v: v["Google"]["revenue"])
    shopify_rev = sum_in_range(
        {d: {"v": v} for d, v in shopify_daily.items()}, frm, to, lambda v: v["v"]
    )

    total_spend = round(meta_spend + google_spend, 2)
    meta_roas = round(meta_rev / meta_spend, 3) if meta_spend > 0 else None
    google_roas = round(google_rev / google_spend, 3) if google_spend > 0 else None
    mer = round(shopify_rev / total_spend, 3) if total_spend > 0 else None

    days = (to - frm).days + 1
    return {
        "key": name,
        "label": label,
        "from": frm.isoformat(),
        "to": to.isoformat(),
        "days": days,
        "metaSpend": meta_spend,
        "metaRev": meta_rev,
        "metaRoas": meta_roas,
        "googleSpend": google_spend,
        "googleRev": google_rev,
        "googleRoas": google_roas,
        "totalSpend": total_spend,
        "shopifyRev": shopify_rev,
        "mer": mer,
    }


def main():
    trackbee_raw = load_json("trackbee_data.json")
    trackbee = {k: v for k, v in trackbee_raw.items() if k != "_meta"}
    shopify_daily = load_json("shopify_daily.json")

    today = datetime.date.today()
    earliest = min(datetime.date.fromisoformat(d) for d in trackbee.keys())

    periods = [
        build_period("vandaag", "Vandaag", today, earliest, trackbee, shopify_daily),
        build_period("gisteren", "Gisteren", today, earliest, trackbee, shopify_daily),
        build_period("week", "Deze week", today, earliest, trackbee, shopify_daily),
        build_period("maand", "Deze maand", today, earliest, trackbee, shopify_daily),
        build_period("totaal", "Sinds start tracking", today, earliest, trackbee, shopify_daily),
    ]

    refreshed = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    periods_json = json.dumps(periods)

    html = HTML_TEMPLATE.format(
        periods_json=periods_json,
        refreshed=refreshed,
        earliest=earliest.isoformat(),
    )
    out_path = HERE / "management_dashboard.html"
    out_path.write_text(html)
    print(f"✓ Geschreven: {out_path}")
    for p in periods:
        mer_s = x2(p["mer"]) if p["mer"] is not None else "—"
        print(f"  {p['label']:<22} MER={mer_s:<8} spend={eur(p['totalSpend'])}")


HTML_TEMPLATE = """<!doctype html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Management dashboard · Meta / Google / MER</title>
<style>
:root {{
  --c-navy:#121985; --c-navy-dark:#0D1433; --c-navy-hover:#2A31A0; --c-navy-soft:#E8E9F4;
  --c-paper:#FAFAFA; --c-surface:#F3F4F6; --c-ink:#27272A; --c-muted:#6B7280;
  --c-border:#E5E7EB; --c-success:#1E5B3A; --c-success-bg:#E6F4EC;
  --c-danger:#8B3A2E; --c-danger-bg:#FBEAE7; --c-warn:#8A5A12; --c-warn-bg:#FBF1DF;
  --ff-display:'Newsreader','Georgia','Times New Roman',serif;
  --ff-sans:'Hanken Grotesk',-apple-system,'Helvetica Neue',sans-serif;
  --r-md:14px; --r-lg:20px; --r-xl:28px; --r-pill:999px;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--c-paper); color:var(--c-ink); font-family:var(--ff-sans);
        font-size:14px; line-height:1.5; padding:24px 24px 60px; }}
.wrap {{ max-width:920px; margin:0 auto; }}
h1 {{ font-family:var(--ff-display); font-weight:600; font-size:22px; margin:0 0 2px; color:var(--c-navy-dark); }}
.page-subtitle {{ font-size:13px; color:var(--c-muted); margin-bottom:18px; }}
.tabs {{ display:flex; gap:6px; flex-wrap:wrap; margin-bottom:18px; }}
.tab {{ font-family:var(--ff-sans); font-size:13px; font-weight:500; padding:8px 14px;
        border-radius:var(--r-pill); border:1px solid var(--c-border); background:#fff;
        color:var(--c-ink); cursor:pointer; }}
.tab.active {{ background:var(--c-navy); color:#fff; border-color:var(--c-navy); }}
.kpi-row {{ display:grid; grid-template-columns:repeat(3,1fr); gap:14px; margin-bottom:18px; }}
@media (max-width:720px) {{ .kpi-row {{ grid-template-columns:1fr; }} }}
.kpi-card {{ background:var(--c-navy-dark); color:#fff; border-radius:var(--r-xl);
             padding:22px 24px; }}
.kpi-lbl {{ font-size:12px; letter-spacing:.04em; text-transform:uppercase; color:rgba(255,255,255,.6); margin-bottom:8px; }}
.kpi-val {{ font-family:var(--ff-display); font-size:40px; font-weight:600; line-height:1; }}
.kpi-val.na {{ font-size:18px; font-weight:500; color:rgba(255,255,255,.5); font-family:var(--ff-sans); }}
.kpi-sub {{ font-size:12px; color:rgba(255,255,255,.65); margin-top:8px; }}
.kpi-card.good .kpi-val {{ color:#9FDBB8; }}
.kpi-card.warn .kpi-val {{ color:#F0CB84; }}
.kpi-card.bad  .kpi-val {{ color:#F0A99E; }}
.detail {{ background:#fff; border:1px solid var(--c-border); border-radius:var(--r-lg); padding:4px 0; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th {{ text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.03em;
      color:var(--c-muted); font-weight:600; padding:10px 16px; border-bottom:1px solid var(--c-border); }}
th.r, td.r {{ text-align:right; }}
td {{ padding:12px 16px; border-bottom:1px solid var(--c-border); }}
tr:last-child td {{ border-bottom:none; }}
tr.tot td {{ font-weight:700; }}
.footer {{ text-align:center; color:var(--c-muted); font-size:11px; margin-top:22px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Management dashboard</h1>
  <div class="page-subtitle">Meta ROAS · Google ROAS · MER — dezelfde brondata als het bonus- en break-even-dashboard</div>

  <div class="tabs" id="tabs"></div>
  <div class="kpi-row" id="kpiRow"></div>
  <div class="detail"><table id="detailTable"></table></div>

  <div class="footer">Bijgewerkt: {refreshed} · Data sinds {earliest} · Bron: Meta Marketing API, Google Ads (via TrackBee), Shopify</div>
</div>

<script>
const PERIODS = {periods_json};
let active = "maand";

function eur(v) {{
  return "€" + v.toLocaleString("nl-NL", {{minimumFractionDigits:2, maximumFractionDigits:2}});
}}
function x2(v) {{ return v === null ? "—" : v.toFixed(2) + "×"; }}

function roasClass(roas) {{
  if (roas === null) return "";
  if (roas >= 2.5) return "good";
  if (roas >= 1.5) return "warn";
  return "bad";
}}

function render() {{
  const p = PERIODS.find(x => x.key === active);

  document.getElementById("tabs").innerHTML = PERIODS.map(x =>
    `<button class="tab${{x.key===active?" active":""}}" onclick="setPeriod('${{x.key}}')">${{x.label}}</button>`
  ).join("");

  const cards = [
    {{lbl:"META ROAS", val:x2(p.metaRoas), cls:roasClass(p.metaRoas),
      sub:`${{eur(p.metaSpend)}} spend → ${{eur(p.metaRev)}} omzet (Meta-toegeschreven)`}},
    {{lbl:"GOOGLE ROAS", val:x2(p.googleRoas), cls:roasClass(p.googleRoas),
      sub:`${{eur(p.googleSpend)}} spend → ${{eur(p.googleRev)}} omzet (Google-toegeschreven)`}},
    {{lbl:"MER (blended)", val:x2(p.mer), cls:roasClass(p.mer),
      sub:`${{eur(p.shopifyRev)}} totale omzet / ${{eur(p.totalSpend)}} totale adspend`}},
  ];
  document.getElementById("kpiRow").innerHTML = cards.map(c => `
    <div class="kpi-card ${{c.cls}}">
      <div class="kpi-lbl">${{c.lbl}}</div>
      <div class="kpi-val${{c.val==='—'?' na':''}}">${{c.val}}</div>
      <div class="kpi-sub">${{c.sub}}</div>
    </div>`).join("");

  document.getElementById("detailTable").innerHTML = `
    <thead><tr><th>Kanaal</th><th class="r">Spend</th><th class="r">Omzet</th><th class="r">ROAS</th><th class="r">% van adspend</th></tr></thead>
    <tbody>
      <tr><td>Meta</td><td class="r">${{eur(p.metaSpend)}}</td><td class="r">${{eur(p.metaRev)}}</td><td class="r">${{x2(p.metaRoas)}}</td><td class="r">${{p.totalSpend>0?(p.metaSpend/p.totalSpend*100).toFixed(1):"0.0"}}%</td></tr>
      <tr><td>Google</td><td class="r">${{eur(p.googleSpend)}}</td><td class="r">${{eur(p.googleRev)}}</td><td class="r">${{x2(p.googleRoas)}}</td><td class="r">${{p.totalSpend>0?(p.googleSpend/p.totalSpend*100).toFixed(1):"0.0"}}%</td></tr>
      <tr class="tot"><td>Totaal adspend</td><td class="r">${{eur(p.totalSpend)}}</td><td class="r">—</td><td class="r">—</td><td class="r">100%</td></tr>
      <tr class="tot"><td>Totale Shopify-omzet</td><td class="r">—</td><td class="r">${{eur(p.shopifyRev)}}</td><td class="r">—</td><td class="r">—</td></tr>
    </tbody>`;
}}

function setPeriod(key) {{ active = key; render(); }}
render();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
