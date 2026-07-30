#!/usr/bin/env python3
"""
LumeWorks · bonusdashboard voor Daan (Creative Strategist, Meta Ads).

Los van het interne break-even dashboard (breakeven_day.py): dit dashboard
is uitsluitend Meta, toont de dynamische break-even ROAS (BEROAS) i.p.v. de
vaste 1,72 uit het contract, en rekent de maandelijkse performance-bonus voor
(adspend x (ROAS - dynamische BEROAS) x 10%), conform de samenwerkings-
overeenkomst met Daan Demes (Demes Electronic Marketing).

Hergebruikt de Shopify-ophaal- en kostprijslogica uit breakeven_day.py; bouwt
een eigen, sterk vereenvoudigde HTML-render omdat doel en doelgroep afwijken
(1 kanaal, geen incl/excl-toggle, maandbasis, bonussimulator i.p.v.
kanaalvergelijking).
"""
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import breakeven_day as bd

SCALE_TARGET_MARGIN_PCT = 12  # schaaldrempel: vanaf hier kan er opgeschaald worden
SCALE_HAPPY_MARGIN_PCT = 15  # comfortabele marge: hier zijn we echt blij mee
BONUS_PCT = 0.10
CONTRACT_START_ISO = "2026-07-16"  # ingangsdatum samenwerkingsovereenkomst - deze maand = maand 1


def render_daan_dashboard(events_meta, today_iso, earliest_iso, trackbee_data=None):
    events_json = json.dumps(events_meta, default=str)
    trackbee_json = json.dumps(trackbee_data or {}, default=str)

    return f"""<!doctype html>
<html lang="nl">
<head>
<meta charset="utf-8">
<title>Daan · Meta bonusdashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600;700&family=Newsreader:ital,wght@0,400;0,500;0,600;1,400;1,500;1,600&display=swap" rel="stylesheet">
<style>
  :root {{
    --c-navy:#121985; --c-navy-dark:#0D1433; --c-navy-hover:#2A31A0; --c-navy-soft:#E8E9F4;
    --c-paper:#FAFAFA; --c-surface:#F3F4F6; --c-ink:#27272A; --c-muted:#6B7280;
    --c-border:#E5E7EB; --c-success:#1E5B3A; --c-success-bg:#E6F4EC;
    --c-danger:#8B3A2E; --c-danger-bg:#FBEAE7; --c-warn:#8A5A12; --c-warn-bg:#FBF1DF;
    --ff-display:'Newsreader','Georgia','Times New Roman',serif;
    --ff-sans:'Hanken Grotesk',-apple-system,'Helvetica Neue',sans-serif;
    --r-md:14px; --r-lg:20px; --r-xl:28px; --r-pill:999px;
    --shadow-2: 0 4px 14px rgba(18,25,133,.06), 0 1px 3px rgba(18,25,133,.03);
    --shadow-3: 0 14px 40px rgba(18,25,133,.09), 0 4px 10px rgba(18,25,133,.04);
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--c-paper); color:var(--c-ink); font-family:var(--ff-sans); font-size:14px; line-height:1.5; padding: 24px 24px 60px; }}
  .wrap {{ max-width: 980px; margin: 0 auto; }}
  h1 {{ font-family:var(--ff-display); font-weight:600; font-size:21px; margin:0 0 2px; color:var(--c-navy-dark); }}
  .page-subtitle {{ font-size:13px; color:var(--c-muted); }}
  .page-header {{ display:flex; align-items:flex-start; justify-content:space-between; gap:16px; flex-wrap:wrap; margin-bottom:16px; }}

  .toolbar {{ display:flex; align-items:center; justify-content:flex-end; gap:8px; margin-bottom:0; flex-shrink:0; padding-top:2px; }}
  select {{ font-family:var(--ff-sans); font-size:12px; padding:7px 12px; border-radius:var(--r-pill); border:1px solid var(--c-border); background:#fff; color:var(--c-ink); cursor:pointer; }}
  .custom-range {{ display:none; gap:6px; align-items:center; }}
  .custom-range.show {{ display:flex; }}
  input[type=date] {{ font-family:var(--ff-sans); font-size:12px; padding:7px 10px; border-radius:var(--r-pill); border:1px solid var(--c-border); }}

  /* Hero: 1 dominant antwoord (bonus €) bovenaan, daaronder een compacte
     vergelijkingsregel (ROAS/BEROAS/drempel) - kleiner, ondersteunend, geen
     concurrerende hero-cijfers meer. */
  .hero {{
    background:
      radial-gradient(70% 60% at 70% 80%, rgba(42,49,160,.4), transparent 65%),
      radial-gradient(50% 40% at 10% 10%, rgba(20,166,241,.12), transparent 60%),
      linear-gradient(160deg, #0A0D26 0%, #0D1433 50%, #161A3C 100%);
    color:#fff; border-radius:var(--r-xl); padding:26px 30px; margin-bottom:14px; box-shadow:var(--shadow-3);
  }}
  .hero-scope {{ font-size:13px; color:rgba(255,255,255,.55); margin-bottom:18px; }}

  .headline-label {{ font-size:12px; text-transform:uppercase; letter-spacing:.06em; color:rgba(255,255,255,.5); margin-bottom:8px; }}
  .headline-row {{ display:flex; align-items:baseline; gap:14px; flex-wrap:wrap; margin-bottom:6px; }}
  .headline-value {{ font-family:var(--ff-display); font-size:52px; font-weight:600; line-height:1; }}
  .headline-value.placeholder {{ font-size:20px; font-weight:500; color:rgba(255,255,255,.5); font-family:var(--ff-sans); }}
  .headline-trend {{ display:inline-flex; align-items:center; gap:4px; font-size:13px; font-weight:600; padding:4px 10px; border-radius:var(--r-pill); }}
  .headline-trend.up {{ background:rgba(92,169,122,.18); color:#9FDBB8; }}
  .headline-trend.down {{ background:rgba(217,168,78,.18); color:#F0CB84; }}
  .headline-trend.flat {{ background:rgba(255,255,255,.1); color:rgba(255,255,255,.6); }}
  .headline-sub {{ font-size:13px; color:rgba(255,255,255,.65); margin-bottom:4px; }}
  .headline-coverage {{ font-size:12px; color:rgba(255,255,255,.5); margin-bottom:22px; }}
  .headline-coverage strong {{ color:rgba(255,255,255,.75); font-weight:600; }}

  .compare-row {{ display:flex; gap:24px; flex-wrap:wrap; padding:14px 0; border-top:1px solid rgba(255,255,255,.1); border-bottom:1px solid rgba(255,255,255,.1); margin-bottom:8px; }}
  .compare-item {{ }}
  .compare-label {{ font-size:11px; text-transform:uppercase; letter-spacing:.05em; color:rgba(255,255,255,.45); margin-bottom:3px; display:flex; align-items:center; gap:5px; }}
  .compare-value {{ font-family:var(--ff-display); font-size:20px; font-weight:600; color:#fff; }}

  /* Info-icoon: simpel oppervlak, detail alleen op hover - zo blijft de
     eerste blik minimaal maar is er meer te zien wie het wil. */
  .info-icon {{ display:inline-flex; align-items:center; justify-content:center; width:14px; height:14px; border-radius:50%; border:1px solid rgba(255,255,255,.4); color:rgba(255,255,255,.65); font-size:10px; line-height:1; font-family:Georgia,serif; font-style:italic; font-weight:400; cursor:default; position:relative; flex-shrink:0; text-transform:none; }}
  .info-icon[data-tip]::after {{
    content:attr(data-tip); position:absolute; bottom:22px; left:50%; transform:translateX(-50%) translateY(4px);
    background:#fff; color:var(--c-navy-dark); font-family:var(--ff-sans); font-size:12px; font-weight:400; font-style:normal; line-height:1.45; text-transform:none;
    padding:9px 11px; border-radius:8px; width:240px; white-space:normal; text-align:left;
    box-shadow:0 4px 14px rgba(0,0,0,.25); opacity:0; pointer-events:none;
    transition:opacity .15s ease, transform .15s ease; z-index:6;
  }}
  .info-icon[data-tip]:hover::after {{ opacity:1; transform:translateX(-50%) translateY(0); }}
  .compare-value.placeholder {{ font-size:13px; font-weight:500; color:rgba(255,255,255,.4); font-family:var(--ff-sans); }}
  .compare-sub {{ font-size:11px; color:rgba(255,255,255,.4); }}

  /* Gekoppelde hover: het cijfer bovenin en zijn punt in de balk lichten
     samen op, zodat de link tussen de twee direct duidelijk is. */
  .compare-value {{ cursor:default; transition:text-shadow .15s ease, transform .15s ease; display:inline-block; }}
  .compare-value.linked-hi {{ text-shadow:0 0 14px rgba(255,255,255,.8); transform:scale(1.04); transform-origin:left center; }}
  .gauge-marker.linked-hi, .gauge-refline.linked-hi {{ box-shadow:0 0 0 2px var(--c-navy-dark), 0 0 10px 3px rgba(255,255,255,.75); transition:box-shadow .15s ease; }}
  .gauge-refline-target.linked-hi::before {{ box-shadow:0 0 10px 3px rgba(255,255,255,.75); }}
  .gauge-legend-item {{ cursor:default; transition:color .15s ease; border-radius:4px; }}
  .gauge-legend-item.linked-hi {{ color:#fff; }}
  .gauge-legend-item.linked-hi .gauge-legend-swatch {{ background:#fff; }}
  .gauge-legend-item.linked-hi .gauge-legend-swatch.target::before {{ background:#fff; box-shadow:0 0 6px 2px rgba(255,255,255,.7); }}
  .gauge-legend-item.linked-hi .gauge-legend-swatch.dashed {{ border-top-color:#fff; }}

  /* Gauge: as begint bij 0 zodat de positie niet onnodig alarmerend oogt;
     break-even/drempel/comfortabel krijgen elk een referentielijn los van de
     bewegende ROAS-marker. Kleuren bewust zacht - "onder break-even" is in
     een vroege periode normaal, geen brandalarm. */
  .gauge-wrap {{ margin:30px 0 8px; }}
  .gauge-track {{ position:relative; height:10px; border-radius:5px; overflow:visible; display:flex; }}
  .gauge-seg {{ height:100%; }}
  .gauge-seg.zone-below {{ background:#C6553F; border-radius:5px 0 0 5px; }}
  .gauge-seg.zone-mid {{ background:#DDA23D; }}
  .gauge-seg.zone-target {{ background:#5CA97A; border-radius:0 5px 5px 0; }}
  .gauge-marker {{ position:absolute; top:-6px; width:3px; height:22px; background:#fff; border-radius:1px; box-shadow:0 0 0 2px var(--c-navy-dark); z-index:2; cursor:default; }}
  .gauge-marker-label {{ position:absolute; top:-26px; transform:translateX(-50%); font-size:12px; font-weight:700; color:#fff; white-space:nowrap; }}
  .gauge-refline {{ position:absolute; top:-4px; width:2px; height:18px; background:rgba(255,255,255,.5); cursor:default; }}
  .gauge-refline-label {{ position:absolute; top:24px; transform:translateX(-50%); font-size:11px; font-weight:600; color:rgba(255,255,255,.7); white-space:nowrap; }}
  /* Drie visueel verschillende stijlen zodat break-even/drempel/comfortabel
     niet op dezelfde streep lijken: dun-effen / dik-met-bolletje / gestippeld. */
  .gauge-refline-target {{ width:3px; }}
  .gauge-refline-target::before {{ content:''; position:absolute; top:-5px; left:50%; transform:translateX(-50%); width:7px; height:7px; border-radius:50%; background:#fff; }}
  .gauge-refline-happy {{ background:transparent; border-left:2px dashed rgba(255,255,255,.6); width:0; }}
  .gauge-legend {{ display:flex; gap:24px; flex-wrap:wrap; font-size:12px; color:rgba(255,255,255,.6); margin-top:32px; }}
  .gauge-legend-item {{ display:flex; align-items:center; gap:8px; }}
  .gauge-legend-swatch {{ display:inline-block; width:16px; height:2px; background:rgba(255,255,255,.6); }}
  .gauge-legend-swatch.target {{ height:0; border-top:3px solid rgba(255,255,255,.6); position:relative; }}
  .gauge-legend-swatch.target::before {{ content:''; position:absolute; top:-4px; left:50%; transform:translateX(-50%); width:7px; height:7px; border-radius:50%; background:rgba(255,255,255,.85); }}
  .gauge-legend-swatch.dashed {{ background:transparent; border-top:2px dashed rgba(255,255,255,.5); }}

  /* Hover-tooltip op de referentielijnen en de marker: volledige uitleg
     verschijnt onder de balk bij hover, met een korte fade/slide-animatie. */
  .gauge-refline[data-tip]::after, .gauge-marker[data-tip]::after {{
    content: attr(data-tip); position:absolute; top:52px; left:50%; transform:translateX(-50%) translateY(-4px);
    background:#fff; color:var(--c-navy-dark); font-size:11px; font-weight:500; line-height:1.4;
    padding:7px 10px; border-radius:8px; white-space:nowrap; box-shadow:0 4px 14px rgba(0,0,0,.25);
    opacity:0; pointer-events:none; transition:opacity .15s ease, transform .15s ease; z-index:5;
  }}
  .gauge-refline[data-tip]:hover::after, .gauge-marker[data-tip]:hover::after {{ opacity:1; transform:translateX(-50%) translateY(0); }}

  .hl-dot {{ position:relative; display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:7px; vertical-align:middle; background:currentColor; }}
  .hl-dot::after {{ content:''; position:absolute; inset:0; border-radius:50%; background:currentColor; animation:dot-pulse 1.8s ease-out infinite; }}
  .hl-dot.dot-below {{ color:#C6553F; }}
  .hl-dot.dot-mid {{ color:#DDA23D; }}
  .hl-dot.dot-target {{ color:#5CA97A; }}
  @keyframes dot-pulse {{ 0% {{ transform:scale(1); opacity:.55; }} 100% {{ transform:scale(2.6); opacity:0; }} }}

  .quality-row {{ display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px; }}
  .quality-badge {{ display:inline-flex; align-items:center; gap:6px; padding:5px 12px; border-radius:var(--r-pill); font-size:11px; font-weight:600; }}
  .quality-volledig {{ background:var(--c-success-bg); color:var(--c-success); }}
  .quality-grotendeels, .quality-onvolledig {{ background:var(--c-warn-bg); color:var(--c-warn); }}
  .quality-geen {{ background:var(--c-surface); color:var(--c-muted); }}

  /* Simulator */
  .sim-sub {{ font-size:12px; color:var(--c-muted); margin-bottom:16px; }}
  .sim-row {{ margin-bottom:16px; }}
  .sim-row-label {{ font-size:12px; color:var(--c-muted); margin-bottom:6px; display:flex; justify-content:space-between; }}
  .sim-row-label span.val {{ color:var(--c-navy-dark); font-weight:700; }}
  .input-euro {{ display:flex; align-items:center; border:1px solid var(--c-border); border-radius:var(--r-md); overflow:hidden; }}
  .input-euro span {{ padding:9px 0 9px 12px; font-weight:600; color:var(--c-muted); }}
  #simAdspend {{ flex:1; width:100%; font-family:var(--ff-sans); font-size:15px; font-weight:600; padding:9px 12px 9px 6px; border:none; outline:none; color:var(--c-ink); }}
  #simRoas {{ -webkit-appearance:none; width:100%; height:4px; border-radius:2px; background:var(--c-border); outline:none; cursor:pointer; }}
  #simRoas::-webkit-slider-thumb {{ -webkit-appearance:none; width:16px; height:16px; border-radius:50%; background:var(--c-navy); cursor:pointer; }}
  #simRoas::-moz-range-thumb {{ width:16px; height:16px; border-radius:50%; background:var(--c-navy); border:none; cursor:pointer; }}
  .sim-result {{ background:var(--c-navy-soft); border-radius:var(--r-md); padding:14px 16px; font-size:13px; }}
  .sim-result strong {{ font-family:var(--ff-display); font-size:16px; color:var(--c-navy-dark); font-weight:600; }}
  .sim-caption {{ font-size:11px; color:var(--c-muted); margin-top:8px; }}

  /* Onderbouwing */
  details.control-section {{ background:#fff; border:1px solid var(--c-border); border-radius:var(--r-lg); margin-bottom:10px; box-shadow:var(--shadow-2); }}
  details.control-section > summary {{ cursor:pointer; padding:13px 20px; font-weight:600; color:var(--c-navy-dark); font-size:13px; list-style:none; display:flex; justify-content:space-between; align-items:center; outline:none; }}
  details.control-section > summary::-webkit-details-marker {{ display:none; }}
  details.control-section > summary::after {{ content:'▸'; color:var(--c-muted); transition:transform .15s ease; }}
  details.control-section[open] > summary::after {{ transform:rotate(90deg); }}
  .control-section-body {{ padding:0 20px 18px; font-size:13px; }}
  .control-section-body p {{ margin:0 0 10px; color:var(--c-ink); }}
  .control-section-body p.muted {{ color:var(--c-muted); font-size:12px; }}
  .waterfall {{ display:flex; flex-wrap:wrap; align-items:center; gap:6px; font-size:13px; margin-bottom:12px; }}
  .waterfall .step {{ display:flex; flex-direction:column; align-items:center; min-width:78px; }}
  .waterfall .step-label {{ font-size:10px; color:var(--c-muted); text-transform:uppercase; letter-spacing:.04em; margin-bottom:2px; }}
  .waterfall .step-value {{ font-family:var(--ff-display); font-weight:600; font-size:15px; color:var(--c-navy-dark); }}
  .waterfall .arrow {{ color:var(--c-muted); font-size:15px; }}
  .waterfall .step.clickable {{ cursor:pointer; }}
  .waterfall .step.clickable .step-value {{ text-decoration:underline; text-decoration-style:dotted; text-underline-offset:3px; }}
  .expand-toggle {{ background:none; border:none; color:var(--c-navy); font-size:12px; cursor:pointer; font-family:var(--ff-sans); padding:0; margin:0 0 12px; text-decoration:underline; }}
  .cost-breakdown {{ display:none; margin-bottom:12px; padding-top:12px; border-top:1px solid var(--c-border); grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:12px; }}
  .cost-breakdown.show {{ display:grid; }}
  .cost-item-label {{ color:var(--c-muted); font-size:11px; text-transform:uppercase; letter-spacing:.04em; margin-bottom:2px; }}
  .cost-item-value {{ font-weight:600; color:var(--c-ink); font-size:14px; }}
  table {{ width:100%; border-collapse:collapse; background:#fff; border-radius:var(--r-md); overflow:hidden; margin-top:8px; }}
  th, td {{ padding:8px 9px; border-bottom:1px solid var(--c-border); font-size:12px; text-align:left; white-space:nowrap; }}
  th {{ background:var(--c-surface); font-size:10px; text-transform:uppercase; letter-spacing:.04em; color:var(--c-muted); }}
  td.num, th.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .row-total td {{ font-weight:700; background:var(--c-navy-soft); }}
  .row-excluded td {{ color:var(--c-muted); font-style:italic; }}
  td.trend-up {{ color:var(--c-success); }}
  td.trend-down {{ color:var(--c-warn); }}
  td.trend-flat {{ color:var(--c-muted); }}
  td.pct-neg {{ color:var(--c-danger); font-weight:600; }}
  td.pct-low {{ color:var(--c-warn); font-weight:600; }}
  td.pct-good {{ color:var(--c-success); font-weight:600; }}
  .table-wrap {{ overflow-x:auto; border:1px solid var(--c-border); border-radius:var(--r-md); }}
  .callout {{ background:var(--c-warn-bg); border-radius:var(--r-md); padding:12px 14px; font-size:12px; color:var(--c-warn); margin-bottom:12px; }}
  .callout-neutral {{ background:var(--c-navy-soft); border-radius:var(--r-md); padding:12px 14px; font-size:12px; color:var(--c-ink); margin-bottom:12px; }}
  .callout-neutral strong {{ color:var(--c-navy-dark); }}
</style>
</head>
<body>
<div class="wrap">
  <div class="page-header">
    <div>
      <h1>Meta bonusdashboard</h1>
      <div class="page-subtitle">Hoeveel bonus Daan nu verdient met Meta-advertenties</div>
    </div>
    <div class="toolbar">
      <select id="periodSelect" onchange="onPeriodChange(this.value)">
        <option value="deze_maand" selected>Deze maand</option>
        <option value="vorige_maand">Vorige maand</option>
        <option value="aangepast">Aangepaste periode</option>
      </select>
      <div class="custom-range" id="customRange">
        <input type="date" id="customStart">
        <span style="color:var(--c-muted);font-size:12px;">t/m</span>
        <input type="date" id="customEnd">
      </div>
    </div>
  </div>

  <div class="hero">
    <div class="hero-scope" id="heroScope"></div>

    <div class="headline-label">Bonus tot nu toe</div>
    <div class="headline-row">
      <div class="headline-value placeholder" id="hlBonus">—</div>
      <div class="headline-trend" id="hlTrend" style="display:none;"></div>
    </div>
    <div class="headline-sub" id="hlSub"></div>
    <div class="headline-coverage" id="hlCoverage"></div>

    <div class="compare-row">
      <div class="compare-item">
        <div class="compare-label">Meta ROAS <span class="info-icon" id="mRoasInfo">i</span></div>
        <div class="compare-value placeholder" id="mRoas">—</div>
        <div class="compare-sub" id="mRoasTrend"></div>
      </div>
      <div class="compare-item">
        <div class="compare-label">Break-even <span class="info-icon" id="mBeroasInfo">i</span></div>
        <div class="compare-value placeholder" id="mBeroas">—</div>
      </div>
      <div class="compare-item">
        <div class="compare-label">Schaaldrempel <span class="info-icon" id="mTargetInfo">i</span></div>
        <div class="compare-value placeholder" id="mTarget">—</div>
      </div>
    </div>

    <div class="gauge-wrap">
      <div class="gauge-track" id="gaugeTrack">
        <div class="gauge-seg zone-below" id="gzBelow"></div>
        <div class="gauge-seg zone-mid" id="gzMid"></div>
        <div class="gauge-seg zone-target" id="gzTarget"></div>
        <div class="gauge-refline" id="gaugeRefBe"><span class="gauge-refline-label" id="gaugeRefBeLabel"></span></div>
        <div class="gauge-refline gauge-refline-target" id="gaugeRefTgt"><span class="gauge-refline-label" id="gaugeRefTgtLabel"></span></div>
        <div class="gauge-refline gauge-refline-happy" id="gaugeRefHappy"><span class="gauge-refline-label" id="gaugeRefHappyLabel"></span></div>
        <div class="gauge-marker" id="gaugeMarker"><div class="gauge-marker-label" id="gaugeMarkerLabel"></div></div>
      </div>
      <div class="gauge-legend">
        <span class="gauge-legend-item" id="legendBe"><span class="gauge-legend-swatch"></span>break-even</span>
        <span class="gauge-legend-item" id="legendTgt"><span class="gauge-legend-swatch target"></span>schaaldrempel ({SCALE_TARGET_MARGIN_PCT}%)</span>
        <span class="gauge-legend-item" id="legendHappy"><span class="gauge-legend-swatch dashed"></span>comfortabel ({SCALE_HAPPY_MARGIN_PCT}%)</span>
      </div>
    </div>
  </div>

  <details class="control-section">
    <summary>Bonussimulator</summary>
    <div class="control-section-body">
      <div class="sim-sub">Fictief scenario: dezelfde kosten- en bonusformule als hierboven, maar met een zelf ingevoerde adspend en margedoel i.p.v. de werkelijke cijfers van deze periode. Geen voorspelling.</div>
      <div class="sim-row">
        <div class="sim-row-label">Adspend (fictief scenario)</div>
        <div class="input-euro"><span>€</span><input type="number" id="simAdspend" step="100" min="0" value="25000" oninput="onSimInput()"></div>
      </div>
      <div class="sim-row">
        <div class="sim-row-label">ROAS <span class="val" id="simRoasVal">—</span> <span class="info-icon" id="simRoasInfo" data-tip="">i</span></div>
        <input type="range" id="simRoas" min="0" max="5" step="0.05" value="0" oninput="onSimInput()">
      </div>
      <div class="sim-result" id="simResult"></div>
      <div class="sim-caption">Gebaseerd op de dynamische BEROAS van de huidige periode (zie Onderbouwing) — verandert de werkelijke bonus hierboven niet.</div>
    </div>
  </details>

  <details class="control-section">
    <summary>Onderbouwing BEROAS</summary>
    <div class="control-section-body">
      <p><strong>Wat is de dynamische BEROAS?</strong><br>De ROAS waarbij de omzet precies alle kosten dekt (inkoop, verzending, fulfilment, betaal-/platformkosten, overhead) zonder winst of verlies. Vanaf {SCALE_TARGET_MARGIN_PCT}% marge daarboven kan er opgeschaald worden; vanaf {SCALE_HAPPY_MARGIN_PCT}% is dat comfortabel.</p>
      <p><strong>Hoe wordt hij berekend?</strong><br>Shopify levert de orders, aantallen en omzet deze periode; de kostprijs per product (inkoop, verzending, fulfilment) komt uit de kostprijscalculatie. Rekenkern (excl. btw, C = kosten excl. ads): adspend = omzet × (1 − marge) − C → ROAS = omzet / adspend.</p>
      <div class="callout-neutral">
        <strong>Waarom verandert hij door de ordermix?</strong> Koopt iemand een LumeWorks Prime mét projectiescherm, dan stijgt de gemiddelde orderwaarde (AOV) en de absolute marge — maar omdat het scherm een dunnere marge% heeft dan de projector, kan de <em>gemiddelde marge% van de omzet</em> licht dalen. Dat duwt de dynamische BEROAS omhoog. Dat is geen slecht teken: de absolute winst per order is hoger, alleen is er relatief iets meer omzet-efficiëntie (ROAS) nodig om diezelfde winst%-drempel te halen. Kijk dus niet alleen naar de BEROAS-trend, maar ook naar de absolute marge hieronder.
      </div>
      <p class="muted"><strong>Welke data wordt gebruikt?</strong> De BEROAS hieronder is berekend op de volledige ordermix van de winkel (alle orders, niet uitgesplitst naar kanaal) — Shopify herkent zelf niet betrouwbaar welk kanaal een order heeft opgeleverd, dus wordt hier alleen gebruikt voor wat het wél zeker weet: kosten en marge. De werkelijke ROAS hierboven komt volledig uit TrackBee, dat wél op attributie is gebouwd.</p>
      <p style="margin-bottom:6px;"><strong>Concrete berekening voor deze periode</strong></p>
      <div class="waterfall" id="waterfall"></div>
      <p class="muted" id="waterfallPlain" style="margin-top:6px;"></p>
      <button class="expand-toggle" id="costToggle" onclick="toggleCostBreakdown()">Kostenopbouw bekijken</button>
      <div class="cost-breakdown" id="costBreakdown"></div>
    </div>
  </details>

  <details class="control-section">
    <summary>Kerncijfers</summary>
    <div class="control-section-body">
      <p class="muted" id="coreCount"></p>
      <div class="table-wrap">
        <table>
          <thead><tr id="coreThead"><th></th><th>Deze periode</th><th>Vorige periode</th><th>Verschil</th></tr></thead>
          <tbody id="coreTable"></tbody>
        </table>
      </div>
      <p class="muted" style="margin-top:10px;">"Vorige periode" is een even lange periode direct ervoor (bijv. bij "deze maand" de laatste dagen van vorige maand tot en met dezelfde dag-van-de-maand) — zo blijft de vergelijking eerlijk, ook midden in een lopende maand.</p>
      <p class="muted" style="margin-top:16px; font-weight:600; color:var(--c-ink);">Adspend per dag (Meta)</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Dag</th><th class="num">Adspend</th><th class="num">Omzet (TrackBee)</th><th class="num">ROAS</th><th class="num">Winst</th><th class="num">Marge %</th></tr></thead>
          <tbody id="dailySpendTable"></tbody>
        </table>
      </div>
    </div>
  </details>

  <details class="control-section">
    <summary>Orderdetail (alle orders)</summary>
    <div class="control-section-body">
      <p class="muted" id="orderQualityNote"></p>
      <div class="table-wrap">
        <table>
          <thead><tr>
            <th>Order</th><th>Datum</th><th>Producten</th><th>Kortingscode</th>
            <th class="num">Omzet excl. btw</th><th class="num">Kosten excl. ads</th><th class="num">Marge</th><th class="num">Break-even ROAS (incl. btw)</th>
          </tr></thead>
          <tbody id="orderTable"></tbody>
        </table>
      </div>
    </div>
  </details>
</div>

<script>
const LW_EVENTS = {events_json};
const LW_TRACKBEE = {trackbee_json};
const LW_TODAY = "{today_iso}";
const LW_EARLIEST = "{earliest_iso}";
const CONTRACT_START = "{CONTRACT_START_ISO}";
const SCALE_TARGET_MARGIN_FRAC = {SCALE_TARGET_MARGIN_PCT} / 100;
const SCALE_HAPPY_MARGIN_FRAC = {SCALE_HAPPY_MARGIN_PCT} / 100;
const BONUS_PCT = {BONUS_PCT};
const BTW = 1.21;

let state = {{ period: 'deze_maand', customStart: null, customEnd: null, simAdspend: 25000, simRoasIncl: null, simInitialized: false }};

function jsEur(x) {{
  if (x === null || x === undefined) return '-';
  var sign = x < 0 ? '-' : '';
  var v = Math.abs(x).toFixed(2);
  var parts = v.split('.');
  var intPart = parts[0].replace(/\\B(?=(\\d{{3}})+(?!\\d))/g, '.');
  return sign + '€' + intPart + ',' + parts[1];
}}
function jsPct(x) {{ return (x * 100).toFixed(1).replace('.', ',') + '%'; }}
function jsRoas(x) {{ return (x === null || x === undefined) ? 'n.v.t.' : x.toFixed(2).replace('.', ',') + 'x'; }}

function toDate(iso) {{ var p = iso.split('-'); return new Date(Date.UTC(+p[0], +p[1] - 1, +p[2])); }}
function toIso(d) {{ return d.toISOString().slice(0, 10); }}
function addDays(iso, n) {{ var d = toDate(iso); d.setUTCDate(d.getUTCDate() + n); return toIso(d); }}
function firstOfMonth(iso) {{ var p = iso.split('-'); return p[0] + '-' + p[1] + '-01'; }}
function monthNumber(iso) {{
  var d = toDate(iso), c = toDate(CONTRACT_START);
  return (d.getUTCFullYear() - c.getUTCFullYear()) * 12 + (d.getUTCMonth() - c.getUTCMonth()) + 1;
}}
function lastOfMonth(iso) {{ var d = toDate(firstOfMonth(iso)); d.setUTCMonth(d.getUTCMonth() + 1); d.setUTCDate(d.getUTCDate() - 1); return toIso(d); }}

function periodRange() {{
  var t = LW_TODAY;
  switch (state.period) {{
    case 'deze_maand': return [firstOfMonth(t), t];
    case 'vorige_maand': var pm = addDays(firstOfMonth(t), -1); return [firstOfMonth(pm), lastOfMonth(pm)];
    case 'aangepast': return [state.customStart || LW_EARLIEST, state.customEnd || t];
    default: return [firstOfMonth(t), t];
  }}
}}

function filterRows(start, end) {{
  return LW_EVENTS.filter(function(e) {{ return e.status === 'ok' && e.day >= start && e.day <= end; }});
}}

// Vergelijkbare voorgaande periode (zelfde lengte, direct ervoor) - voor het
// enige trendsignaal dat het dashboard toont: gaat de bonus vooruit of
// achteruit t.o.v. de vorige keer. Een dagelijkse sparkline zou bij dit
// ordervolume vooral ruis laten zien, geen trend.
function previousPeriodRange(range) {{
  var days = Math.round((toDate(range[1]) - toDate(range[0])) / 86400000) + 1;
  var prevEnd = addDays(range[0], -1);
  var prevStart = addDays(prevEnd, -(days - 1));
  return [prevStart, prevEnd];
}}

// Twee soorten orders worden buiten de berekening gelaten i.p.v. meegeteld
// met een "indicatief"-label: onbekende SKU (kostprijs ontbreekt, dus de
// kostenregel is onvolledig) en testorders (kortingscode eindigt op "100",
// bijv. JOB100/Koen100 - vrijwel gratis, geen echte klant).
function isTestOrder(r) {{
  if (!r.discount_codes || r.discount_codes === '-') return false;
  return r.discount_codes.split(',').some(function(c) {{ return /100$/i.test(c.trim()); }});
}}

function summarize(rows) {{
  var agg = {{ n_orders: 0, omzet_incl: 0, omzet_excl: 0, inkoop: 0, shipping: 0, fulfilment: 0, shopify_fee: 0, overhead: 0 }};
  var excludedUnknownSku = 0, excludedTestOrder = 0;
  rows.forEach(function(r) {{
    if (r.has_unknown_sku) {{ excludedUnknownSku++; return; }}
    if (isTestOrder(r)) {{ excludedTestOrder++; return; }}
    agg.n_orders++;
    agg.omzet_incl += r.omzet_incl; agg.omzet_excl += r.omzet_excl;
    agg.inkoop += r.inkoop; agg.shipping += r.shipping; agg.fulfilment += r.fulfilment;
    agg.shopify_fee += r.shopify_fee; agg.overhead += r.overhead;
  }});
  var kosten_excl_ads = agg.inkoop + agg.shipping + agg.fulfilment + agg.shopify_fee + agg.overhead;
  var marge = agg.omzet_excl - kosten_excl_ads;
  var breakeven_roas = marge > 0 ? agg.omzet_excl / marge : null;
  var breakeven_roas_incl = marge > 0 ? agg.omzet_incl / marge : null;
  var quality = agg.n_orders > 0 ? 'volledig' : 'geen';
  return Object.assign(agg, {{
    kosten_excl_ads: kosten_excl_ads, marge: marge, breakeven_roas: breakeven_roas, breakeven_roas_incl: breakeven_roas_incl,
    quality: quality, excluded_orders: excludedUnknownSku + excludedTestOrder,
    excluded_unknown_sku: excludedUnknownSku, excluded_test_order: excludedTestOrder,
  }});
}}

function requiredRoasForMargin(g, marginFrac) {{
  var adspend = g.omzet_excl * (1 - marginFrac) - g.kosten_excl_ads;
  if (adspend <= 0) return null;
  var roas = g.omzet_excl / adspend;
  var ratio = g.omzet_excl > 0 ? g.omzet_incl / g.omzet_excl : 1;
  return {{ roas: roas, roasIncl: roas * ratio, adspend: adspend }};
}}

function getRealizedMeta(start, end) {{
  var s = toDate(start), e = toDate(end);
  var daysTotal = Math.round((e - s) / 86400000) + 1;
  var spend = 0, revenue = 0, covered = 0;
  for (var i = 0; i < daysTotal; i++) {{
    var d = addDays(start, i);
    var v = LW_TRACKBEE[d] && LW_TRACKBEE[d]['Meta'];
    if (v) {{ spend += v.spend; revenue += v.revenue; covered++; }}
  }}
  if (spend <= 0 || covered === 0) return null;
  // TrackBee/Meta rapporteren omzet incl. btw (zelfde grondslag als Shopify's
  // order-totalen); voor een eerlijke vergelijking met de excl.-btw BEROAS
  // wordt hier teruggerekend naar excl. btw. roasIncl blijft beschikbaar zodat
  // Daan het kan matchen met wat hij in Meta Ads Manager zelf ziet.
  return {{
    spend: spend, revenue: revenue,
    roas: (revenue / BTW) / spend, roasIncl: revenue / spend,
    daysCovered: covered, daysTotal: daysTotal,
  }};
}}

function onPeriodChange(val) {{
  state.period = val;
  document.getElementById('customRange').classList.toggle('show', val === 'aangepast');
  if (val === 'aangepast' && !state.customStart) {{
    var r = periodRange();
    document.getElementById('customStart').value = r[0];
    document.getElementById('customEnd').value = r[1];
    state.customStart = r[0]; state.customEnd = r[1];
  }}
  render();
}}
document.getElementById('customStart').addEventListener('change', function() {{ state.customStart = this.value; render(); }});
document.getElementById('customEnd').addEventListener('change', function() {{ state.customEnd = this.value; render(); }});

function onSimInput() {{
  state.simAdspend = +document.getElementById('simAdspend').value || 0;
  state.simRoasIncl = +document.getElementById('simRoas').value;
  renderSim();
}}

function toggleCostBreakdown() {{
  document.getElementById('costBreakdown').classList.toggle('show');
}}

let lastG = null, lastRange = null;

// Bonus (of null als er onvoldoende data is) volgens de contractformule:
// adspend x (ROAS - dynamische BEROAS) x 10%, nooit negatief.
function computeBonus(g, realized, targetRes) {{
  if (!realized || !g || g.breakeven_roas === null || !targetRes) return null;
  var be = g.breakeven_roas, r = realized.roas;
  return Math.max(0, realized.spend * (r - be)) * BONUS_PCT;
}}

function render() {{
  var range = periodRange();
  lastRange = range;
  var periodLabel = range[0] === range[1] ? range[0] : range[0] + ' t/m ' + range[1];
  var mNum = monthNumber(range[0]);
  var monthTip = mNum === 1
    ? 'Maand 1 sinds de start (16 juli 2026) — deze maand draait het vooral om break-even, winst volgt vanaf maand 2.'
    : 'Maand ' + mNum + ' sinds de start van de samenwerking (16 juli 2026).';
  var monthNote = mNum >= 1
    ? ' · Maand ' + mNum + ' <span class="info-icon" data-tip="' + monthTip + '">i</span>'
    : '';
  document.getElementById('heroScope').innerHTML = 'Meta · ' + periodLabel + monthNote;

  var rows = filterRows(range[0], range[1]);
  var g = summarize(rows);
  lastG = g;

  var realized = getRealizedMeta(range[0], range[1]);
  var roasEl = document.getElementById('mRoas');
  var beroasEl = document.getElementById('mBeroas');
  var targetRes = (g.breakeven_roas !== null) ? requiredRoasForMargin(g, SCALE_TARGET_MARGIN_FRAC) : null;
  var targetResHappy = (g.breakeven_roas !== null) ? requiredRoasForMargin(g, SCALE_HAPPY_MARGIN_FRAC) : null;
  var bonus = computeBonus(g, realized, targetRes);

  // Voorgaande, even lange periode - eenmalig berekend, hergebruikt voor de
  // bonus-trendchip, de ROAS-vergelijking en de Kerncijfers-tabel.
  var prevRange = previousPeriodRange(range);
  var prevG = summarize(filterRows(prevRange[0], prevRange[1]));
  var prevRealized = getRealizedMeta(prevRange[0], prevRange[1]);
  var prevTargetRes = (prevG.breakeven_roas !== null) ? requiredRoasForMargin(prevG, SCALE_TARGET_MARGIN_FRAC) : null;
  var prevBonus = computeBonus(prevG, prevRealized, prevTargetRes);

  // --- Headline: het enige antwoord dat er echt toe doet - de bonus. ---
  var hlBonusEl = document.getElementById('hlBonus');
  var hlSubEl = document.getElementById('hlSub');
  var hlCoverageEl = document.getElementById('hlCoverage');
  var hlTrendEl = document.getElementById('hlTrend');

  if (bonus === null) {{
    hlBonusEl.textContent = g.n_orders === 0 ? 'Nog geen orders deze periode' : 'Onvoldoende advertentiedata';
    hlBonusEl.classList.add('placeholder');
    hlSubEl.textContent = '';
    hlCoverageEl.textContent = '';
    hlTrendEl.style.display = 'none';
  }} else {{
    hlBonusEl.textContent = jsEur(bonus);
    hlBonusEl.classList.remove('placeholder');
    var be = g.breakeven_roas, tgt = targetRes.roas, r = realized.roas;
    var happy = targetResHappy ? targetResHappy.roas : tgt;
    // Gat berekenen op dezelfde grondslag (incl. btw) als de zichtbare cijfers
    // in de vergelijkingsregel hierboven - anders klopt het getal hier niet
    // met wat je zelf uitrekent door de twee zichtbare cijfers af te trekken.
    var beL2 = g.breakeven_roas_incl, rL2 = realized.roasIncl, tgtL2 = targetRes.roasIncl;
    var happyL2 = targetResHappy ? targetResHappy.roasIncl : tgtL2;
    var dotClass, subText;
    if (r < be) {{ dotClass = 'dot-below'; subText = 'Nog ' + jsRoas(beL2 - rL2) + ' ROAS nodig voor break-even — geen bonus'; }}
    else if (r < tgt) {{ dotClass = 'dot-mid'; subText = 'Boven break-even, nog ' + jsRoas(tgtL2 - rL2) + ' ROAS tot de schaaldrempel'; }}
    else if (!targetResHappy || r < happy) {{ dotClass = 'dot-target'; subText = 'Schaaldrempel gehaald'; }}
    else {{ dotClass = 'dot-target'; subText = 'Comfortabel boven de schaaldrempel'; }}
    hlSubEl.innerHTML = '<span class="hl-dot ' + dotClass + '"></span>' + subText;
    var coverageNote = realized.daysCovered < realized.daysTotal
      ? 'Datadekking TrackBee: <strong>' + realized.daysCovered + ' van ' + realized.daysTotal + ' dagen</strong> deze periode'
      : 'Datadekking TrackBee: volledig';
    hlCoverageEl.innerHTML = 'Adspend ' + jsEur(realized.spend) + ' · ' + coverageNote;

    // Trend: bonus t.o.v. een even lange voorgaande periode (geen dagelijkse
    // sparkline - bij dit ordervolume is dat vooral ruis, geen signaal).
    if (prevBonus !== null) {{
      var delta = bonus - prevBonus;
      var band = Math.max(5, Math.abs(prevBonus) * 0.05);
      hlTrendEl.style.display = 'inline-flex';
      if (delta > band) {{ hlTrendEl.className = 'headline-trend up'; hlTrendEl.textContent = '▲ ' + jsEur(delta) + ' t.o.v. vorige periode'; }}
      else if (delta < -band) {{ hlTrendEl.className = 'headline-trend down'; hlTrendEl.textContent = '▼ ' + jsEur(Math.abs(delta)) + ' t.o.v. vorige periode'; }}
      else {{ hlTrendEl.className = 'headline-trend flat'; hlTrendEl.textContent = '± gelijk aan vorige periode'; }}
    }} else {{
      hlTrendEl.style.display = 'none';
    }}
  }}

  // --- Compacte vergelijkingsregel: incl. btw primair (herkenbaar); excl.
  // btw en toelichting zitten achter het info-icoontje (hover). ---
  var mRoasTrendEl = document.getElementById('mRoasTrend');
  if (realized) {{
    roasEl.textContent = jsRoas(realized.roasIncl);
    roasEl.classList.remove('placeholder');
    document.getElementById('mRoasInfo').setAttribute('data-tip', 'Gemeten tot nu toe via TrackBee, deze periode. ' + jsRoas(realized.roas) + ' excl. btw is de rekenbasis voor de bonus.');
    if (prevRealized) {{
      var roasPctDelta = (realized.roasIncl - prevRealized.roasIncl) / prevRealized.roasIncl * 100;
      var sign = roasPctDelta > 0.5 ? '+' : (roasPctDelta < -0.5 ? '' : '±');
      mRoasTrendEl.textContent = sign + roasPctDelta.toFixed(0) + '% t.o.v. vorige periode';
    }} else {{
      mRoasTrendEl.textContent = '';
    }}
  }} else {{
    roasEl.textContent = 'Geen data';
    roasEl.classList.add('placeholder');
    document.getElementById('mRoasInfo').setAttribute('data-tip', 'TrackBee heeft nog geen advertentiedata voor deze periode gemeten.');
    mRoasTrendEl.textContent = '';
  }}
  if (g.breakeven_roas !== null && g.n_orders > 0) {{
    beroasEl.textContent = jsRoas(g.breakeven_roas_incl);
    beroasEl.classList.remove('placeholder');
    document.getElementById('mBeroasInfo').setAttribute('data-tip', 'Shopify levert de orders, aantallen en omzet deze periode; de kostprijs per product (inkoop, verzending, fulfilment) komt uit de kostprijscalculatie. Geen advertentiedata nodig. ' + jsRoas(g.breakeven_roas) + ' excl. btw is de rekenbasis.');
  }} else {{
    beroasEl.textContent = 'Onvoldoende orders';
    beroasEl.classList.add('placeholder');
    document.getElementById('mBeroasInfo').setAttribute('data-tip', 'Nog te weinig orders deze periode om een break-even ROAS te berekenen.');
  }}
  if (targetRes) {{
    document.getElementById('mTarget').textContent = jsRoas(targetRes.roasIncl);
    document.getElementById('mTarget').classList.remove('placeholder');
    document.getElementById('mTargetInfo').setAttribute('data-tip', 'De ROAS die nodig is om ' + SCALE_TARGET_MARGIN_FRAC * 100 + '% marge boven break-even te halen — vanaf hier kan er opgeschaald worden. ' + jsRoas(targetRes.roas) + ' excl. btw is de rekenbasis.');
  }} else {{
    document.getElementById('mTarget').textContent = 'n.v.t.';
    document.getElementById('mTarget').classList.add('placeholder');
    document.getElementById('mTargetInfo').setAttribute('data-tip', 'Nog niet te berekenen — te weinig orders deze periode.');
  }}

  // --- Gauge: as begint bij 0, break-even/schaaldrempel/comfortabel krijgen
  // elk een vaste referentielijn (excl. btw - de rekenbasis van de bonus-
  // formule). Marker = werkelijke ROAS. ---
  if (!realized || g.breakeven_roas === null || !targetRes) {{
    document.getElementById('gzBelow').style.flex = '1'; document.getElementById('gzMid').style.flex = '0'; document.getElementById('gzTarget').style.flex = '0';
    document.getElementById('gaugeMarker').style.display = 'none';
    document.getElementById('gaugeRefBe').style.display = 'none';
    document.getElementById('gaugeRefTgt').style.display = 'none';
    document.getElementById('gaugeRefHappy').style.display = 'none';
  }} else {{
    var be = g.breakeven_roas, tgt = targetRes.roas, r = realized.roas;
    var happy = targetResHappy ? targetResHappy.roas : tgt;
    // Labels tonen incl. btw (consistent met de vergelijkingsregel erboven);
    // de as, zones en posities blijven op excl. btw gerekend - incl./excl.
    // schalen allebei met exact dezelfde btw-factor, dus de verhoudingen op
    // de balk veranderen niet, alleen het bijschrift.
    var beL = g.breakeven_roas_incl, tgtL = targetRes.roasIncl, rL = realized.roasIncl;
    var happyL = targetResHappy ? targetResHappy.roasIncl : tgtL;
    var pad = Math.max((tgt - be) * 0.4, happy * 0.1);
    var lo = 0, hi = Math.max(happy + pad, r * 1.05);
    var belowW = be / hi;
    var midW = (tgt - be) / hi;
    var targetW = 1 - belowW - midW;
    document.getElementById('gzBelow').style.flex = belowW;
    document.getElementById('gzMid').style.flex = midW;
    document.getElementById('gzTarget').style.flex = targetW;

    var bePct = be / hi * 100, tgtPct = tgt / hi * 100;
    var refBe = document.getElementById('gaugeRefBe'), refTgt = document.getElementById('gaugeRefTgt');
    refBe.style.display = 'block'; refBe.style.left = 'calc(' + bePct + '% - 1px)';
    refTgt.style.display = 'block'; refTgt.style.left = 'calc(' + tgtPct + '% - 1px)';
    document.getElementById('gaugeRefBeLabel').textContent = jsRoas(beL);
    document.getElementById('gaugeRefTgtLabel').textContent = jsRoas(tgtL);
    refBe.setAttribute('data-tip', 'Break-even: ' + jsRoas(beL) + ' — hieronder is er verlies');
    refTgt.setAttribute('data-tip', 'Schaaldrempel (' + SCALE_TARGET_MARGIN_FRAC * 100 + '% marge): ' + jsRoas(tgtL) + ' — vanaf hier kan er opgeschaald worden');

    var refHappy = document.getElementById('gaugeRefHappy');
    if (targetResHappy) {{
      var happyPct = happy / hi * 100;
      refHappy.style.display = 'block'; refHappy.style.left = 'calc(' + happyPct + '% - 1px)';
      document.getElementById('gaugeRefHappyLabel').textContent = jsRoas(happyL);
      refHappy.setAttribute('data-tip', 'Comfortabel (' + SCALE_HAPPY_MARGIN_FRAC * 100 + '% marge): ' + jsRoas(happyL));
    }} else {{
      refHappy.style.display = 'none';
    }}

    var rawPct = r / hi * 100;
    var markerPct = Math.max(1, Math.min(99, rawPct));
    var marker = document.getElementById('gaugeMarker');
    marker.style.display = 'block';
    marker.style.left = 'calc(' + markerPct + '% - 1px)';
    var markerLabel = jsRoas(rL);
    if (rawPct > 99) markerLabel = markerLabel + ' ▸';
    document.getElementById('gaugeMarkerLabel').textContent = markerLabel;
    marker.setAttribute('data-tip', 'Meta ROAS nu: ' + jsRoas(rL));
  }}

  // --- Kerncijfers: kernbedragen deze periode vs. even lange vorige periode. ---
  function pctDelta(cur, prev) {{
    if (prev === null || prev === undefined || prev === 0) return null;
    return (cur - prev) / Math.abs(prev) * 100;
  }}
  function deltaCell(cur, prev, fmt) {{
    var d = pctDelta(cur, prev);
    if (d === null) return '<td class="num">—</td>';
    var sign = d > 0.5 ? '+' : (d < -0.5 ? '' : '±');
    var cls = d > 0.5 ? 'trend-up' : (d < -0.5 ? 'trend-down' : 'trend-flat');
    return '<td class="num ' + cls + '">' + sign + d.toFixed(0) + '%</td>';
  }}
  var coreRows = [
    ['Omzet excl. btw', g.omzet_excl, prevG.omzet_excl, jsEur],
    ['Adspend (Meta)', realized ? realized.spend : null, prevRealized ? prevRealized.spend : null, jsEur],
    ['Max. adspend zonder verlies', g.marge, prevG.marge, jsEur],
    ['Meta ROAS', realized ? realized.roasIncl : null, prevRealized ? prevRealized.roasIncl : null, jsRoas],
    ['Bonus', bonus, prevBonus, jsEur],
  ];
  var hasPrevComparison = prevG.n_orders > 0 || !!prevRealized;
  var coreThead = document.getElementById('coreThead');
  if (hasPrevComparison) {{
    coreThead.innerHTML = '<th></th><th class="num">Deze periode</th><th class="num">Vorige periode</th><th class="num">Verschil</th>';
    document.getElementById('coreTable').innerHTML = coreRows.map(function(row) {{
      var label = row[0], cur = row[1], prev = row[2], fmt = row[3];
      return '<tr><td>' + label + '</td><td class="num">' + (cur === null ? '—' : fmt(cur)) + '</td>' +
        '<td class="num">' + (prev === null || prev === undefined ? '—' : fmt(prev)) + '</td>' +
        deltaCell(cur, prev) + '</tr>';
    }}).join('');
  }} else {{
    coreThead.innerHTML = '<th></th><th class="num">Deze periode</th>';
    document.getElementById('coreTable').innerHTML = coreRows.map(function(row) {{
      var label = row[0], cur = row[1], fmt = row[3];
      return '<tr><td>' + label + '</td><td class="num">' + (cur === null ? '—' : fmt(cur)) + '</td></tr>';
    }}).join('') + '<tr><td colspan="2" class="muted" style="font-style:italic;">Nog geen vergelijkbare vorige periode beschikbaar.</td></tr>';
  }}
  document.getElementById('coreCount').textContent = '— ' + periodLabel + ' vs. vorige periode';

  // --- Adspend per dag (Meta) - adspend/omzet rechtstreeks uit TrackBee, geen
  // afgeleide ratio zoals ROAS dus geen ruis-risico bij weinig orders. Winst
  // per dag komt uit Shopify-marge van diezelfde dag (excl. ads, excl. btw,
  // zelfde uitsluitingen als de rest van het dashboard) min de TrackBee-
  // adspend van die dag - zodat Daan als mediabuyer de winstgevendheid per
  // dag kan volgen, niet alleen adspend/omzet los van elkaar.
  (function() {{
    var s = toDate(range[0]), e = toDate(range[1]);
    var nDays = Math.round((e - s) / 86400000) + 1;
    var dayRowsHtml = '';
    for (var i = nDays - 1; i >= 0; i--) {{
      var d = addDays(range[0], i);
      var v = LW_TRACKBEE[d] && LW_TRACKBEE[d]['Meta'];
      var dayMarge = 0;
      LW_EVENTS.forEach(function(r) {{
        if (r.status === 'ok' && r.day === d && !r.has_unknown_sku && !isTestOrder(r)) dayMarge += r.marge;
      }});
      var winst = v ? (dayMarge - v.spend) : null;
      var margePct = (v && v.revenue > 0) ? (winst / v.revenue * 100) : null;
      var dayRoas = (v && v.spend > 0) ? (v.revenue / v.spend) : null;
      var margeCls = margePct === null ? '' : (margePct < 0 ? 'pct-neg' : (margePct < 12 ? 'pct-low' : 'pct-good'));
      dayRowsHtml += '<tr' + (v ? '' : ' class="row-excluded"') + '><td>' + d + '</td>' +
        '<td class="num">' + (v ? jsEur(v.spend) : 'geen data') + '</td>' +
        '<td class="num">' + (v ? jsEur(v.revenue) : '—') + '</td>' +
        '<td class="num">' + (dayRoas === null ? '—' : jsRoas(dayRoas)) + '</td>' +
        '<td class="num ' + (winst === null ? '' : (winst >= 0 ? 'trend-up' : 'trend-down')) + '">' + (winst === null ? '—' : jsEur(winst)) + '</td>' +
        '<td class="num ' + margeCls + '">' + (margePct === null ? '—' : margePct.toFixed(0) + '%') + '</td></tr>';
    }}
    document.getElementById('dailySpendTable').innerHTML = dayRowsHtml;
  }})();

  // --- Ordertabel-toelichting: welke orders zijn buiten de berekening gelaten en waarom. ---
  var noteParts = [];
  if (g.excluded_unknown_sku > 0) noteParts.push(g.excluded_unknown_sku + ' met onbekende SKU (kostprijs ontbreekt)');
  if (g.excluded_test_order > 0) noteParts.push(g.excluded_test_order + ' testorder(s) (kortingscode op "100")');
  document.getElementById('orderQualityNote').textContent = noteParts.length
    ? g.n_orders + ' orders meegeteld in de berekening — ' + noteParts.join(' en ') + ' niet.'
    : 'Alle ' + g.n_orders + ' orders zijn meegeteld in de berekening.';

  // Waterfall (onderbouwing) - "Kosten excl. ads" is aanklikbaar en klapt de
  // volledige kostenopbouw uit (inkoop/verzending/fulfilment/betaalkosten/
  // overhead), voor wie dat wil zien.
  document.getElementById('waterfall').innerHTML =
    '<div class="step"><div class="step-label">Omzet excl. btw</div><div class="step-value">' + jsEur(g.omzet_excl) + '</div></div>' +
    '<div class="arrow">−</div>' +
    '<div class="step clickable" onclick="toggleCostBreakdown()"><div class="step-label">Kosten excl. ads</div><div class="step-value">' + jsEur(g.kosten_excl_ads) + '</div></div>' +
    '<div class="arrow">=</div>' +
    '<div class="step"><div class="step-label">Max. adspend zonder verlies</div><div class="step-value">' + jsEur(g.marge) + '</div></div>' +
    '<div class="arrow">→</div>' +
    '<div class="step"><div class="step-label">Dynamische BEROAS</div><div class="step-value">' + jsRoas(g.breakeven_roas) + '</div></div>';
  document.getElementById('waterfallPlain').textContent = g.marge > 0
    ? jsEur(g.omzet_excl) + ' omzet − ' + jsEur(g.kosten_excl_ads) + ' kosten = ' + jsEur(g.marge) + ' beschikbaar voor advertenties. ' +
      jsEur(g.omzet_excl) + ' ÷ ' + jsEur(g.marge) + ' = ' + jsRoas(g.breakeven_roas) + ' dynamische BEROAS.'
    : '';
  document.getElementById('costBreakdown').innerHTML =
    '<div><div class="cost-item-label">Inkoop</div><div class="cost-item-value">' + jsEur(g.inkoop) + '</div></div>' +
    '<div><div class="cost-item-label">Verzending</div><div class="cost-item-value">' + jsEur(g.shipping) + '</div></div>' +
    '<div><div class="cost-item-label">Fulfilment</div><div class="cost-item-value">' + jsEur(g.fulfilment) + '</div></div>' +
    '<div><div class="cost-item-label">Betaal-/platformkosten</div><div class="cost-item-value">' + jsEur(g.shopify_fee) + '</div></div>' +
    '<div><div class="cost-item-label">Overhead</div><div class="cost-item-value">' + jsEur(g.overhead) + '</div></div>';

  // Orderdetail - orders met onbekende SKU blijven zichtbaar (audit-doel) maar
  // met een duidelijke markering dat ze buiten de BEROAS-berekening vallen,
  // want hun kostenregel is onvolledig.
  var rowsHtml = rows.map(function(r) {{
    if (r.has_unknown_sku) {{
      return '<tr class="row-excluded"><td>' + r.name + '</td><td>' + r.day + '</td><td>' + r.products + '</td><td>' + r.discount_codes + '</td>' +
        '<td class="num">' + jsEur(r.omzet_excl) + '</td><td colspan="3">Uitgesloten: onbekende SKU — ' + r.unknown_lines.join(', ') + ' (kostprijs ontbreekt in de kostprijscalculatie)</td></tr>';
    }}
    if (isTestOrder(r)) {{
      return '<tr class="row-excluded"><td>' + r.name + '</td><td>' + r.day + '</td><td>' + r.products + '</td><td>' + r.discount_codes + '</td>' +
        '<td class="num">' + jsEur(r.omzet_excl) + '</td><td colspan="3">Uitgesloten: testorder — kortingscode "' + r.discount_codes + '" eindigt op "100"</td></tr>';
    }}
    return '<tr><td>' + r.name + '</td><td>' + r.day + '</td><td>' + r.products + '</td><td>' + r.discount_codes + '</td>' +
      '<td class="num">' + jsEur(r.omzet_excl) + '</td><td class="num">' + jsEur(r.kosten_totaal) + '</td>' +
      '<td class="num">' + jsEur(r.marge) + '</td><td class="num">' + jsRoas(r.roas_incl) + '</td></tr>';
  }}).join('');
  var totalRow = '<tr class="row-total"><td colspan="4">Totaal</td>' +
    '<td class="num">' + jsEur(g.omzet_excl) + '</td><td class="num">' + jsEur(g.kosten_excl_ads) + '</td>' +
    '<td class="num">' + jsEur(g.marge) + '</td><td class="num">' + jsRoas(g.breakeven_roas_incl) + '</td></tr>';
  document.getElementById('orderTable').innerHTML = rowsHtml + totalRow;

  renderSim();
}}

function renderSim() {{
  var g = lastG;
  var resEl = document.getElementById('simResult');
  var slider = document.getElementById('simRoas');
  if (!g || g.breakeven_roas === null || g.omzet_excl <= 0) {{
    resEl.textContent = 'Onvoldoende data deze periode om te simuleren.';
    slider.disabled = true;
    return;
  }}
  slider.disabled = false;

  // Slider begint bij de dynamische break-even ROAS zelf (het punt waarop
  // Daan volgens hem/haar begint te verdienen) en loopt daarboven door - niet
  // vanaf 0, dat is niet het relevante bereik.
  var beIncl = g.breakeven_roas_incl;
  var inclRatio = g.omzet_incl / g.omzet_excl;
  var sliderMin = Math.floor(beIncl * 20) / 20;
  var sliderMax = Math.ceil((beIncl + 3) * 20) / 20; // rond af op 0,05x
  slider.min = sliderMin; slider.max = sliderMax; slider.step = 0.05;

  // Eerste keer (of bij periodewissel): slider start op de schaaldrempel als
  // zinvol ankerpunt, niet op break-even zelf.
  if (!state.simInitialized || state.simRoasIncl === null || state.simRoasIncl < sliderMin || state.simRoasIncl > sliderMax) {{
    var targetRes = requiredRoasForMargin(g, SCALE_TARGET_MARGIN_FRAC);
    state.simRoasIncl = targetRes ? targetRes.roasIncl : sliderMin;
    state.simInitialized = true;
  }}
  slider.value = state.simRoasIncl;
  document.getElementById('simRoasVal').textContent = jsRoas(state.simRoasIncl);

  var roasExcl = state.simRoasIncl / inclRatio;
  var adspend = state.simAdspend || 0;
  var bonus = Math.max(0, adspend * (roasExcl - g.breakeven_roas)) * BONUS_PCT;

  // Impliciete winstmarge bij deze ROAS, o.b.v. de huidige kostenverhouding
  // (kosten excl. ads als % van omzet) - secundaire info, geen rekenbasis
  // voor de bonus zelf.
  var costRatio = g.kosten_excl_ads / g.omzet_excl;
  var marginPct = roasExcl > 0 ? (1 - costRatio - 1 / roasExcl) * 100 : null;
  var marginTip = marginPct === null ? '' :
    (marginPct >= 0 ? '+' : '') + marginPct.toFixed(0) + '% winstmarge boven break-even bij deze ROAS (o.b.v. de huidige kostenverhouding — geen rekenbasis voor de bonus).';
  document.getElementById('simRoasInfo').setAttribute('data-tip', marginTip);

  resEl.innerHTML = 'Bij <strong>' + jsEur(adspend) + '</strong> adspend en <strong>' + jsRoas(state.simRoasIncl) + '</strong> ROAS is de bonus: <strong>' + jsEur(bonus) + '</strong>.';
}}

// Gekoppelde hover: cijfer bovenin, punt in de balk, én de legenda-regel
// eronder lichten samen op - dat hele setje hoort bij elkaar. Eenmalig bij
// laden binden (element-ID's zijn statisch, alleen posities/labels wijzigen
// per render()).
function linkHover(ids) {{
  var els = ids.map(function(id) {{ return document.getElementById(id); }}).filter(Boolean);
  if (els.length < 2) return;
  function on() {{ els.forEach(function(el) {{ el.classList.add('linked-hi'); }}); }}
  function off() {{ els.forEach(function(el) {{ el.classList.remove('linked-hi'); }}); }}
  els.forEach(function(el) {{ el.addEventListener('mouseenter', on); el.addEventListener('mouseleave', off); }});
}}
linkHover(['mRoas', 'gaugeMarker']);
linkHover(['mBeroas', 'gaugeRefBe', 'legendBe']);
linkHover(['mTarget', 'gaugeRefTgt', 'legendTgt']);
linkHover(['gaugeRefHappy', 'legendHappy']);

render();
</script>
</body>
</html>
"""


def main():
    days_back = int(sys.argv[1]) if len(sys.argv) > 1 else 70
    end_day = datetime.now(bd.AMS).date()
    start_day = end_day - timedelta(days=days_back - 1)

    env = bd.load_env()
    token = bd.get_access_token(env)
    orders = bd.fetch_orders_for_range(env, token, start_day, end_day)
    cost_prices = bd.load_cost_prices()

    raw_events = bd.build_events(orders, cost_prices)
    events = [bd.serialize_event(e) for e in raw_events]

    trackbee_data = bd.load_trackbee_data()

    out_dir = os.path.dirname(__file__)
    out_path = os.path.join(out_dir, "daan_dashboard.html")
    html = render_daan_dashboard(events, end_day.isoformat(), start_day.isoformat(), trackbee_data)
    with open(out_path, "w") as f:
        f.write(html)

    n_ok = sum(1 for e in events if e["status"] == "ok")
    print(json.dumps(dict(out_path=out_path, n_orders_raw=len(orders), n_ok=n_ok,
                           range=[start_day.isoformat(), end_day.isoformat()]), indent=2, default=str))


if __name__ == "__main__":
    main()
