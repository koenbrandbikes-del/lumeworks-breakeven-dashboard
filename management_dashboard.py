#!/usr/bin/env python3
"""Genereert management_dashboard.html: Meta ROAS, Google ROAS (branded/non-branded) en MER per periode.

Visueel en functioneel bewust 1-op-1 afgestemd op daan-bonus-dashboard/index.html
(zelfde kleuren, fonts, periode-dropdown+kalender-component, kaartstijl) zodat het
aanvoelt als een verlengstuk van hetzelfde dashboard-systeem.

Input (in dezelfde map):
  trackbee_data.json        — per dag Meta spend/revenue (Google-velden hier NIET meer
                               gebruikt voor dit dashboard, zie google_campaigns_raw.json).
                               Wordt al elk uur ververst door de bestaande cloud-routine.
  shopify_daily.json        — per dag totale Shopify-omzet incl. BTW (total_sales), vers
                               opgehaald via Shopify MCP ShopifyQL door de routine.
  google_campaigns_raw.json — per vaste periode (vandaag/gisteren/week/maand/totaal) de
                               ruwe campagnes uit TrackBee's get_google_campaign_insights.
                               Alleen beschikbaar voor deze 5 periodes — een aangepaste
                               (custom) periode toont daarom geen branded/non-branded
                               Google-split, wel Meta ROAS en MER (die komen uit de
                               dagelijkse data, dus wel bruikbaar voor elke datumrange).

Branded/non-branded classificatie:
  - SEARCH-campagnes hebben een branded_search_analysis-veld van Google/TrackBee zelf.
  - PMAX/Shopping-campagnes classificeren we op naam ("Branded" in naam = branded).
  - Campagnes met "B2B" in de naam vormen een aparte derde emmer, telt niet mee in de
    branded/non-branded-ROAS-kaarten, wel in de totale Google-adspend voor MER.

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


def classify_google_campaigns(campaigns):
    """Splitst campagnes in branded / non-branded / b2b. Retourneert dict met
    spend + revenue per emmer, samen gelijk aan de som van alle campagnes."""
    buckets = {
        "branded": {"spend": 0.0, "rev": 0.0},
        "nonbranded": {"spend": 0.0, "rev": 0.0},
        "b2b": {"spend": 0.0, "rev": 0.0},
    }
    for c in campaigns:
        name = c["campaign_name"]
        spend = float(c["spend"])
        revenue = float(c["conversions_value"])
        bsa = c.get("branded_search_analysis")

        if "B2B" in name.upper():
            buckets["b2b"]["spend"] += spend
            buckets["b2b"]["rev"] += revenue
            continue

        if bsa:
            b_spend = float(bsa["branded_spend"])
            nb_spend = float(bsa["non_branded_spend"])
            b_conv = bsa["branded_conversions"]
            nb_conv = bsa["non_branded_conversions"]
            total_conv = b_conv + nb_conv
            if total_conv > 0:
                b_share = b_conv / total_conv
            elif spend > 0:
                b_share = b_spend / spend
            else:
                b_share = 0
            b_rev = revenue * b_share
            nb_rev = revenue - b_rev
        else:
            branded = "BRANDED" in name.upper()
            b_spend = spend if branded else 0.0
            nb_spend = 0.0 if branded else spend
            b_rev = revenue if branded else 0.0
            nb_rev = 0.0 if branded else revenue

        buckets["branded"]["spend"] += b_spend
        buckets["branded"]["rev"] += b_rev
        buckets["nonbranded"]["spend"] += nb_spend
        buckets["nonbranded"]["rev"] += nb_rev

    for b in buckets.values():
        b["spend"] = round(b["spend"], 2)
        b["rev"] = round(b["rev"], 2)
    return buckets


def build_period(name, label, frm, to, trackbee, shopify_daily, google_campaigns_raw):
    meta_spend = sum_in_range(trackbee, frm, to, lambda v: v["Meta"]["spend"])
    meta_rev = sum_in_range(trackbee, frm, to, lambda v: v["Meta"]["revenue"])
    shopify_rev = sum_in_range(
        {d: {"v": v} for d, v in shopify_daily.items()}, frm, to, lambda v: v["v"]
    )

    campaigns = google_campaigns_raw.get(name, []) if name else []
    g = classify_google_campaigns(campaigns)
    has_google = name in google_campaigns_raw
    google_spend = round(g["branded"]["spend"] + g["nonbranded"]["spend"] + g["b2b"]["spend"], 2)
    google_rev = round(g["branded"]["rev"] + g["nonbranded"]["rev"] + g["b2b"]["rev"], 2)

    total_spend = round(meta_spend + (google_spend if has_google else 0), 2)
    meta_roas = round(meta_rev / meta_spend, 3) if meta_spend > 0 else None
    branded_roas = round(g["branded"]["rev"] / g["branded"]["spend"], 3) if g["branded"]["spend"] > 0 else None
    nonbranded_roas = round(g["nonbranded"]["rev"] / g["nonbranded"]["spend"], 3) if g["nonbranded"]["spend"] > 0 else None
    b2b_roas = round(g["b2b"]["rev"] / g["b2b"]["spend"], 3) if g["b2b"]["spend"] > 0 else None
    mer = round(shopify_rev / total_spend, 3) if total_spend > 0 else None

    days = (to - frm).days + 1
    return {
        "key": name,
        "label": label,
        "from": frm.isoformat(),
        "to": to.isoformat(),
        "days": days,
        "hasGoogle": has_google,
        "metaSpend": meta_spend,
        "metaRev": meta_rev,
        "metaRoas": meta_roas,
        "brandedSpend": g["branded"]["spend"],
        "brandedRev": g["branded"]["rev"],
        "brandedRoas": branded_roas,
        "nonbrandedSpend": g["nonbranded"]["spend"],
        "nonbrandedRev": g["nonbranded"]["rev"],
        "nonbrandedRoas": nonbranded_roas,
        "b2bSpend": g["b2b"]["spend"],
        "b2bRev": g["b2b"]["rev"],
        "b2bRoas": b2b_roas,
        "googleSpend": google_spend if has_google else 0,
        "googleRev": google_rev if has_google else 0,
        "totalSpend": total_spend,
        "shopifyRev": shopify_rev,
        "mer": mer,
    }


def main():
    trackbee_raw = load_json("trackbee_data.json")
    trackbee = {k: v for k, v in trackbee_raw.items() if k != "_meta"}
    shopify_daily = load_json("shopify_daily.json")
    google_campaigns_raw = load_json("google_campaigns_raw.json")

    today = datetime.date.today()
    earliest = min(datetime.date.fromisoformat(d) for d in trackbee.keys())

    period_defs = [
        ("vandaag", "Vandaag"),
        ("gisteren", "Gisteren"),
        ("week", "Deze week"),
        ("maand", "Deze maand"),
        ("totaal", "Sinds start tracking"),
    ]
    periods = [
        build_period(key, label, *period_bounds(key, today, earliest), trackbee, shopify_daily, google_campaigns_raw)
        for key, label in period_defs
    ]

    # Ruwe dagcijfers, ingebed voor client-side aggregatie van een custom
    # (aangepaste) periode via de kalender — zelfde patroon als DAILY_META
    # in het bonusdashboard.
    daily_trackbee = [
        {"d": d, "metaSpend": v["Meta"]["spend"], "metaRev": v["Meta"]["revenue"]}
        for d, v in sorted(trackbee.items())
    ]
    daily_shopify = [{"d": d, "rev": v} for d, v in sorted(shopify_daily.items())]

    refreshed = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    html = HTML_TEMPLATE.format(
        periods_json=json.dumps(periods),
        daily_trackbee_json=json.dumps(daily_trackbee),
        daily_shopify_json=json.dumps(daily_shopify),
        refreshed=refreshed,
        earliest=earliest.isoformat(),
        today=today.isoformat(),
    )
    out_dir = HERE / "management"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "index.html"
    out_path.write_text(html)
    print(f"✓ Geschreven: {out_path}")
    for p in periods:
        mer_s = x2(p["mer"]) if p["mer"] is not None else "—"
        br_s = x2(p["brandedRoas"]) if p["brandedRoas"] is not None else "—"
        nb_s = x2(p["nonbrandedRoas"]) if p["nonbrandedRoas"] is not None else "—"
        print(f"  {p['label']:<22} MER={mer_s:<7} Google branded={br_s:<7} non-branded={nb_s:<7} spend={eur(p['totalSpend'])}")


HTML_TEMPLATE = """<!doctype html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Management dashboard · Meta / Google / MER</title>
<link rel="icon" type="image/png" href="favicon-management.png">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html,body{{min-height:100vh;overflow-x:hidden}}
body{{background:#090d1a;color:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;font-size:14px;line-height:1.5}}
.wrap{{max-width:820px;margin:0 auto;padding:0 20px 48px}}
.hd{{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;padding:32px 0 20px}}
.hd h1{{font-size:clamp(15px,4vw,22px);font-weight:700;margin-bottom:3px;white-space:nowrap}}
.hd p{{font-size:13px;color:#64748b}}
.card{{background:#111827;border:1px solid #1f2d45;border-radius:16px;padding:24px;margin-bottom:12px}}

.period-wrap{{position:relative}}
.period-btn{{display:flex;align-items:center;gap:8px;background:#141e33;border:1px solid #1f3050;color:#f1f5f9;font-size:13px;font-weight:500;padding:8px 12px;border-radius:8px;cursor:pointer;outline:none;white-space:nowrap}}
.period-menu{{display:none;position:absolute;right:0;top:calc(100% + 4px);background:#0d1829;border:1px solid #1f3050;border-radius:10px;min-width:230px;z-index:200;box-shadow:0 8px 32px rgba(0,0,0,.6);padding:6px 0}}
.period-menu.open{{display:block}}
.pm-grp{{font-size:10px;font-weight:700;letter-spacing:.08em;color:#475569;text-transform:uppercase;padding:8px 14px 3px}}
.pm-opt{{padding:7px 14px;cursor:pointer;font-size:13px;color:#94a3b8}}
.pm-opt:hover{{background:#1a2844;color:#f1f5f9}}
.pm-opt.active{{color:#f1f5f9;font-weight:600}}
.pm-opt.active::before{{content:"✓  ";color:#60a5fa}}
.pm-div{{border-top:1px solid #1f2d45;margin:5px 0}}
.cal-pad{{padding:6px 12px 12px}}
.cal-nav{{display:flex;align-items:center;justify-content:space-between;margin-bottom:6px}}
.cal-nb{{background:none;border:none;color:#64748b;cursor:pointer;font-size:18px;padding:0 6px;line-height:1}}
.cal-nb:hover{{color:#f1f5f9}}
.cal-mlbl{{font-size:12px;font-weight:600;color:#cbd5e1}}
.cal-grid{{display:grid;grid-template-columns:repeat(7,1fr);gap:1px;text-align:center}}
.cal-dow{{color:#475569;font-weight:700;font-size:9px;letter-spacing:.04em;padding:3px 0}}
.cal-day{{padding:5px 2px;cursor:pointer;border-radius:3px;color:#94a3b8;font-size:11px}}
.cal-day:hover:not(.cd-off){{background:#1a2844;color:#f1f5f9}}
.cd-off{{color:#1f2d45!important;cursor:default}}
.cd-s,.cd-e{{background:#2563eb!important;color:#fff!important;font-weight:700;border-radius:4px}}
.cd-r{{background:#1e3050;color:#cbd5e1}}
.cd-today{{color:#60a5fa}}
.cal-hint{{font-size:10px;color:#475569;text-align:center;margin:5px 0}}
.cal-apply{{width:100%;padding:6px;background:#2563eb;border:none;color:#fff;border-radius:5px;font-size:12px;font-weight:600;cursor:pointer;margin-top:2px}}
.cal-apply:disabled{{background:#1a2844;color:#374151;cursor:default}}

.kpi-strip{{display:grid;grid-template-columns:repeat(6,1fr);gap:1px;background:#1a2844;border:1px solid #1e3050;border-radius:12px;overflow:hidden;margin-bottom:12px}}
.kpi-item{{padding:11px 12px;background:#0d1829;min-width:0}}
.kpi-lbl{{font-size:9px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#475569;margin-bottom:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.kpi-val{{font-size:16px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.1}}
.kpi-item.good .kpi-val{{color:#4ade80}}
.kpi-item.bad .kpi-val{{color:#f87171}}
.kpi-item.warn .kpi-val{{color:#fbbf24}}
.kpi-item.accent{{background:#0e1f30}}

.roas-hero{{margin-bottom:18px}}
.roas-hero-lbl{{font-size:10px;font-weight:600;letter-spacing:.1em;color:#64748b;text-transform:uppercase;margin-bottom:6px}}
.roas-hero-val{{font-size:52px;font-weight:800;line-height:1;font-variant-numeric:tabular-nums;letter-spacing:-.02em}}
.rdelta{{display:inline-flex;align-items:center;gap:4px;font-size:13px;font-weight:600;padding:5px 11px;border-radius:6px;margin-top:10px}}
.rdelta.neg{{background:rgba(248,113,113,.12);color:#f87171}}
.rdelta.mid{{background:rgba(245,158,11,.12);color:#f59e0b}}
.rdelta.pos{{background:rgba(74,222,128,.12);color:#4ade80}}

.mrow{{display:grid;grid-template-columns:1fr 1fr 1fr;border:1px solid #1f3050;border-radius:10px;overflow:hidden;margin-bottom:14px}}
.mc{{padding:14px 16px;border-right:1px solid #1f3050}}
.mc:last-child{{border-right:none}}
.mc-lbl{{font-size:10px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:#64748b;margin-bottom:4px}}
.mc-val{{font-size:24px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.1}}
.mc-val.na{{font-size:14px;font-weight:500;color:#475569}}
.mc-val.good{{color:#4ade80}}
.mc-val.warn{{color:#fbbf24}}
.mc-val.bad{{color:#f87171}}
.mc-sub{{font-size:11px;color:#64748b;margin-top:2px}}

.note{{font-size:12px;color:#64748b;margin-bottom:16px;line-height:1.5}}
.meta-info{{font-size:12px;color:#64748b;margin-top:14px}}

.acc{{display:flex;flex-direction:column;gap:4px}}
.acc-item{{background:#111827;border:1px solid #1f2d45;border-radius:14px;overflow:hidden}}
.acc-hd{{display:flex;justify-content:space-between;align-items:center;padding:16px 20px;cursor:pointer;font-weight:600;font-size:14px}}
.acc-chv{{color:#64748b;font-size:18px;transition:transform .2s;line-height:1}}
.acc-item.open .acc-chv{{transform:rotate(90deg)}}
.acc-body{{display:none;border-top:1px solid #1f2d45}}
.acc-item.open .acc-body{{display:block}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{padding:9px 14px;text-align:left;font-size:10px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:#64748b;border-bottom:1px solid #1f2d45;white-space:nowrap}}
th.r,td.r{{text-align:right}}
td{{padding:11px 14px;border-bottom:1px solid #1f2d45}}
tbody tr:hover{{background:rgba(255,255,255,.02)}}
tr:last-child td{{border-bottom:none}}
tr.tot td{{font-weight:700}}
tr.sub td:first-child{{padding-left:28px;color:#64748b;font-size:12px}}

.footer{{text-align:center;color:#475569;font-size:11px;margin-top:22px;padding-bottom:20px}}
@media (max-width:540px){{
  .mrow{{grid-template-columns:1fr}}
  .mc{{border-right:none;border-bottom:1px solid #1f3050}}
  .mc:last-child{{border-bottom:none}}
  .kpi-strip{{grid-template-columns:repeat(3,1fr)}}
  .kpi-item:last-child{{grid-column:span 3;border-top:1px solid #1a2844}}
  .roas-hero-val{{font-size:38px}}
}}
</style>
</head>
<body>
<div class="wrap">

<div class="hd">
  <div>
    <h1>Management dashboard</h1>
    <p>Meta ROAS · Google ROAS (branded/non-branded) · MER</p>
  </div>
  <div class="period-wrap">
    <button class="period-btn" onclick="event.stopPropagation();togglePM()">
      <span id="periodBtnTxt">Deze maand</span>
      <svg width="10" height="6" viewBox="0 0 10 6" fill="none"><path d="M1 1l4 4 4-4" stroke="#64748b" stroke-width="1.5" stroke-linecap="round"/></svg>
    </button>
    <div class="period-menu" id="periodMenu" onclick="event.stopPropagation()">
      <div class="pm-grp">Actueel</div>
      <div class="pm-opt" data-p="vandaag" onclick="selectP('vandaag')">Vandaag</div>
      <div class="pm-opt" data-p="gisteren" onclick="selectP('gisteren')">Gisteren</div>
      <div class="pm-opt" data-p="week" onclick="selectP('week')">Deze week</div>
      <div class="pm-opt active" data-p="maand" onclick="selectP('maand')">Deze maand</div>
      <div class="pm-div"></div>
      <div class="pm-opt" data-p="totaal" onclick="selectP('totaal')">Sinds start tracking</div>
      <div class="pm-div"></div>
      <div class="pm-grp">Aangepaste periode</div>
      <div class="cal-pad">
        <div class="cal-nav">
          <button class="cal-nb" onclick="calPrev()">‹</button>
          <span class="cal-mlbl" id="calMlbl"></span>
          <button class="cal-nb" onclick="calNext()">›</button>
        </div>
        <div class="cal-grid" id="calGrid"></div>
        <div class="cal-hint" id="calHint">Klik een startdatum</div>
        <button class="cal-apply" id="calApply" onclick="applyCustom()" disabled>Toepassen</button>
      </div>
    </div>
  </div>
</div>

<div class="kpi-strip" id="kpiStrip"></div>

<div class="card">
  <div class="roas-hero">
    <div class="roas-hero-lbl">MER — MARKETING EFFICIENCY RATIO</div>
    <div class="roas-hero-val" id="merVal">—</div>
    <div id="merDelta"></div>
  </div>

  <div class="mrow" id="mrow"></div>

  <div class="note" id="googleNote">Meta = nieuwe omzet buiten de bestaande funnel. Google non-branded = vergelijkbare rol (vangt nieuwe vraag). Google branded = het laatste zetje voor mensen die al naar het merk zochten — hoge ROAS, maar minder incrementeel. B2B (relatiegeschenken) staat apart, andere doelgroep.</div>

  <div class="meta-info" id="metaInfo"></div>
</div>

<div class="acc">
  <div class="acc-item open" id="acc-detail">
    <div class="acc-hd" onclick="tog('acc-detail')"><span>Detail per kanaal</span><span class="acc-chv">›</span></div>
    <div class="acc-body"><table id="detailTable"></table></div>
  </div>
</div>

<div class="footer">Bijgewerkt: {refreshed} · Data sinds {earliest} · Bron: Meta Marketing API, Google Ads (via TrackBee, campagne-niveau), Shopify</div>
</div>

<script>
const PERIODS = {{}};
{periods_json}.forEach(p => PERIODS[p.key] = p);
const DAILY_TRACKBEE = {daily_trackbee_json};
const DAILY_SHOPIFY = {daily_shopify_json};
const CAL_MIN = "{earliest}";
const TODAY_S = "{today}";
let P = "maand";
let _cS = null, _cE = null;
const _todayD = new Date(TODAY_S + "T00:00:00");
let _cY = _todayD.getFullYear(), _cM = _todayD.getMonth();

function tog(id) {{ document.getElementById(id).classList.toggle("open"); }}
function eur(v) {{ return "€" + v.toLocaleString("nl-NL", {{minimumFractionDigits:2, maximumFractionDigits:2}}); }}
function x2(v) {{ return (v === null || v === undefined) ? "—" : v.toFixed(2) + "×"; }}
const mo = ["jan","feb","mrt","apr","mei","jun","jul","aug","sep","okt","nov","dec"];
const fmtS = s => {{ const [,m,d] = s.split("-"); return `${{+d}} ${{mo[+m-1]}}`; }};
const ymd = d => `${{d.getFullYear()}}-${{String(d.getMonth()+1).padStart(2,"0")}}-${{String(d.getDate()).padStart(2,"0")}}`;

function roasClass(v) {{
  if (v === null || v === undefined) return "";
  if (v >= 2.5) return "good";
  if (v >= 1.5) return "warn";
  return "bad";
}}

function togglePM() {{
  const m = document.getElementById("periodMenu");
  const opening = !m.classList.contains("open");
  m.classList.toggle("open");
  if (opening) calRender();
}}
document.addEventListener("click", () => document.getElementById("periodMenu")?.classList.remove("open"));

function selectP(v) {{
  if (!PERIODS[v]) return;
  P = v;
  document.querySelectorAll(".pm-opt").forEach(el => el.classList.toggle("active", el.dataset.p === v));
  document.getElementById("periodMenu").classList.remove("open");
  render();
}}

function calRender() {{
  const MN = ["jan","feb","mrt","apr","mei","jun","jul","aug","sep","okt","nov","dec"];
  document.getElementById("calMlbl").textContent = `${{MN[_cM]}} ${{_cY}}`;
  const fd = new Date(_cY, _cM, 1).getDay();
  const off = (fd + 6) % 7;
  const dim = new Date(_cY, _cM + 1, 0).getDate();
  let h = '<div class="cal-dow">M</div><div class="cal-dow">D</div><div class="cal-dow">W</div><div class="cal-dow">D</div><div class="cal-dow">V</div><div class="cal-dow">Z</div><div class="cal-dow">Z</div>';
  for (let i = 0; i < off; i++) h += '<div></div>';
  for (let d = 1; d <= dim; d++) {{
    const ds = `${{_cY}}-${{String(_cM+1).padStart(2,'0')}}-${{String(d).padStart(2,'0')}}`;
    const isOff = ds < CAL_MIN || ds > TODAY_S;
    const iS = ds === _cS, iE = ds === _cE;
    const iR = _cS && _cE && ds > _cS && ds < _cE;
    const iT = ds === TODAY_S && !iS && !iE;
    const cls = "cal-day" + (isOff?" cd-off":"") + (iS?" cd-s":"") + (iE?" cd-e":"") + (iR?" cd-r":"") + (iT?" cd-today":"");
    h += `<div class="${{cls}}"${{!isOff?` onclick="calClick('${{ds}}')"`:""}}>${{d}}</div>`;
  }}
  document.getElementById("calGrid").innerHTML = h;
  const hint = document.getElementById("calHint"), apply = document.getElementById("calApply");
  if (!_cS) {{ hint.textContent = "Klik een startdatum"; apply.disabled = true; }}
  else if (!_cE) {{ hint.textContent = `Van ${{fmtS(_cS)}} · klik einddatum`; apply.disabled = true; }}
  else {{ hint.textContent = `${{fmtS(_cS)}} t/m ${{fmtS(_cE)}}`; apply.disabled = false; }}
}}
function calClick(ds) {{
  if (!_cS || (_cS && _cE)) {{ _cS = ds; _cE = null; }}
  else if (ds === _cS) {{ _cS = null; }}
  else if (ds < _cS) {{ _cE = _cS; _cS = ds; }}
  else {{ _cE = ds; }}
  calRender();
}}
function calPrev() {{
  if (_cY === CAL_MIN.slice(0,4)*1 && _cM < CAL_MIN.slice(5,7)*1 - 1) return;
  _cM--; if (_cM < 0) {{ _cM = 11; _cY--; }}
  calRender();
}}
function calNext() {{
  if (_cY > _todayD.getFullYear() || (_cY === _todayD.getFullYear() && _cM >= _todayD.getMonth())) return;
  _cM++; if (_cM > 11) {{ _cM = 0; _cY++; }}
  calRender();
}}
function applyCustom() {{
  if (!_cS || !_cE) return;
  const tb = DAILY_TRACKBEE.filter(d => d.d >= _cS && d.d <= _cE);
  const sh = DAILY_SHOPIFY.filter(d => d.d >= _cS && d.d <= _cE);
  const metaSpend = round2(tb.reduce((s,d)=>s+d.metaSpend,0));
  const metaRev = round2(tb.reduce((s,d)=>s+d.metaRev,0));
  const shopifyRev = round2(sh.reduce((s,d)=>s+d.rev,0));
  const days = Math.round((new Date(_cE)-new Date(_cS))/86400000)+1;
  PERIODS.custom = {{
    key:"custom", label:`${{fmtS(_cS)}}–${{fmtS(_cE)}}`, from:_cS, to:_cE, days,
    hasGoogle:false,
    metaSpend, metaRev, metaRoas: metaSpend>0? round3(metaRev/metaSpend): null,
    brandedSpend:0, brandedRev:0, brandedRoas:null,
    nonbrandedSpend:0, nonbrandedRev:0, nonbrandedRoas:null,
    b2bSpend:0, b2bRev:0, b2bRoas:null,
    googleSpend:0, googleRev:0,
    totalSpend: metaSpend, shopifyRev,
    mer: metaSpend>0? round3(shopifyRev/metaSpend): null,
  }};
  selectP("custom");
}}
function round2(v) {{ return Math.round(v*100)/100; }}
function round3(v) {{ return Math.round(v*1000)/1000; }}

function render() {{
  const p = PERIODS[P];
  document.getElementById("periodBtnTxt").textContent = p.label;

  const kpis = [
    {{lbl:"TOTALE ADSPEND", val: eur(p.totalSpend), cls:""}},
    {{lbl:"TOTALE OMZET", val: eur(p.shopifyRev), cls:""}},
    {{lbl:"MER", val: x2(p.mer), cls: roasClass(p.mer)}},
    {{lbl:"META ROAS", val: x2(p.metaRoas), cls: roasClass(p.metaRoas)}},
    {{lbl:"GOOGLE NON-BRANDED", val: p.hasGoogle? x2(p.nonbrandedRoas):"—", cls: p.hasGoogle? roasClass(p.nonbrandedRoas):""}},
    {{lbl:"GOOGLE BRANDED", val: p.hasGoogle? x2(p.brandedRoas):"—", cls: p.hasGoogle? roasClass(p.brandedRoas):""}},
  ];
  document.getElementById("kpiStrip").innerHTML = kpis.map(k =>
    `<div class="kpi-item ${{k.cls}}"><div class="kpi-lbl">${{k.lbl}}</div><div class="kpi-val">${{k.val}}</div></div>`
  ).join("");

  document.getElementById("merVal").textContent = x2(p.mer);
  document.getElementById("merDelta").innerHTML = "";

  const mc = (lbl, val, sub, cls) => `<div class="mc"><div class="mc-lbl">${{lbl}}</div><div class="mc-val ${{val==='—'?'na':(cls||'')}}">${{val}}</div><div class="mc-sub">${{sub}}</div></div>`;
  document.getElementById("mrow").innerHTML =
    mc("META ROAS", x2(p.metaRoas), `${{eur(p.metaSpend)}} → ${{eur(p.metaRev)}}`, roasClass(p.metaRoas)) +
    mc("GOOGLE NON-BRANDED", p.hasGoogle?x2(p.nonbrandedRoas):"—", p.hasGoogle?`${{eur(p.nonbrandedSpend)}} → ${{eur(p.nonbrandedRev)}}`:"niet beschikbaar voor aangepaste periode", p.hasGoogle?roasClass(p.nonbrandedRoas):"") +
    mc("GOOGLE BRANDED", p.hasGoogle?x2(p.brandedRoas):"—", p.hasGoogle?`${{eur(p.brandedSpend)}} → ${{eur(p.brandedRev)}}`:"niet beschikbaar voor aangepaste periode", p.hasGoogle?roasClass(p.brandedRoas):"");

  document.getElementById("googleNote").style.display = p.hasGoogle ? "" : "none";
  document.getElementById("metaInfo").textContent = `${{fmtS(p.from)}} t/m ${{fmtS(p.to)}} · ${{p.days}} dag${{p.days!==1?"en":""}}`;

  const pct = part => p.totalSpend > 0 ? (part / p.totalSpend * 100).toFixed(1) : "0.0";
  document.getElementById("detailTable").innerHTML = `
    <thead><tr><th>Kanaal</th><th class="r">Spend</th><th class="r">Omzet</th><th class="r">ROAS</th><th class="r">% van adspend</th></tr></thead>
    <tbody>
      <tr><td>Meta</td><td class="r">${{eur(p.metaSpend)}}</td><td class="r">${{eur(p.metaRev)}}</td><td class="r">${{x2(p.metaRoas)}}</td><td class="r">${{pct(p.metaSpend)}}%</td></tr>
      ${{p.hasGoogle ? `
      <tr><td>Google totaal</td><td class="r">${{eur(p.googleSpend)}}</td><td class="r">${{eur(p.googleRev)}}</td><td class="r">${{x2(p.googleSpend>0?p.googleRev/p.googleSpend:null)}}</td><td class="r">${{pct(p.googleSpend)}}%</td></tr>
      <tr class="sub"><td>↳ non-branded</td><td class="r">${{eur(p.nonbrandedSpend)}}</td><td class="r">${{eur(p.nonbrandedRev)}}</td><td class="r">${{x2(p.nonbrandedRoas)}}</td><td class="r">${{pct(p.nonbrandedSpend)}}%</td></tr>
      <tr class="sub"><td>↳ branded</td><td class="r">${{eur(p.brandedSpend)}}</td><td class="r">${{eur(p.brandedRev)}}</td><td class="r">${{x2(p.brandedRoas)}}</td><td class="r">${{pct(p.brandedSpend)}}%</td></tr>
      <tr class="sub"><td>↳ B2B (apart)</td><td class="r">${{eur(p.b2bSpend)}}</td><td class="r">${{eur(p.b2bRev)}}</td><td class="r">${{x2(p.b2bRoas)}}</td><td class="r">${{pct(p.b2bSpend)}}%</td></tr>` : `
      <tr><td>Google</td><td class="r">—</td><td class="r">—</td><td class="r">—</td><td class="r">niet beschikbaar voor aangepaste periode</td></tr>`}}
      <tr class="tot"><td>Totaal adspend</td><td class="r">${{eur(p.totalSpend)}}</td><td class="r">—</td><td class="r">—</td><td class="r">100%</td></tr>
      <tr class="tot"><td>Totale Shopify-omzet</td><td class="r">—</td><td class="r">${{eur(p.shopifyRev)}}</td><td class="r">—</td><td class="r">—</td></tr>
    </tbody>`;
}}

render();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
