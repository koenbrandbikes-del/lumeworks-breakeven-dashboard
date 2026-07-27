#!/usr/bin/env python3
"""
LumeWorks dynamische break-even ROAS - beslissingsdashboard.

Haalt Shopify-orders op, rekent per order de dynamische break-even ROAS uit
o.b.v. de kostprijsdata per SKU, en genereert een interactief HTML-dashboard.
Alle periode- en kanaalaggregatie (dag/week/maand/jaar, Totaal/Meta/Google/...)
gebeurt client-side in JS uit één platte event-lijst (zie build_events),
zodat elke periode/kanaal-combinatie met dezelfde rekenlogica werkt.
"""
import json
import os
import ssl
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CTX = ssl.create_default_context()

CONFIG_DIR = os.path.expanduser("~/.config/lumeworks-shopify")
ENV_FILE = os.path.join(CONFIG_DIR, ".env")
COST_FILE = os.path.join(CONFIG_DIR, "cost_prices.json")
TRACKBEE_FILE = os.path.join(CONFIG_DIR, "trackbee_data.json")
AMS = ZoneInfo("Europe/Amsterdam")
BTW = 1.21


def load_env():
    env = {}
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k] = v
    return env


def get_access_token(env):
    url = f"https://{env['SHOPIFY_SHOP']}/admin/oauth/access_token"
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": env["SHOPIFY_CLIENT_ID"],
        "client_secret": env["SHOPIFY_CLIENT_SECRET"],
    }).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/x-www-form-urlencoded"
    })
    with urllib.request.urlopen(req, context=SSL_CTX) as resp:
        return json.load(resp)["access_token"]


def shopify_get(env, token, path, params):
    qs = urllib.parse.urlencode(params)
    url = f"https://{env['SHOPIFY_SHOP']}/admin/api/2026-07/{path}?{qs}"
    req = urllib.request.Request(url, headers={"X-Shopify-Access-Token": token})
    with urllib.request.urlopen(req, context=SSL_CTX) as resp:
        link_header = resp.headers.get("Link", "")
        return json.load(resp), link_header


def _next_page_url(link_header):
    for part in link_header.split(","):
        if 'rel="next"' in part:
            return part.split(";")[0].strip().strip("<>")
    return None


def shopify_get_paginated(env, token, path, params, item_key="orders"):
    """Volgt Shopify's cursor-paginering (Link-header) tot alle resultaten
    binnen zijn. Nodig zodra een periode meer dan 250 orders bevat."""
    items = []
    data, link_header = shopify_get(env, token, path, params)
    items.extend(data.get(item_key, []))
    next_url = _next_page_url(link_header)
    while next_url:
        req = urllib.request.Request(next_url, headers={"X-Shopify-Access-Token": token})
        with urllib.request.urlopen(req, context=SSL_CTX) as resp:
            link_header = resp.headers.get("Link", "")
            data = json.load(resp)
        items.extend(data.get(item_key, []))
        next_url = _next_page_url(link_header)
    return items


def fetch_orders_for_range(env, token, start_day_ams, end_day_ams_inclusive):
    """Haalt orders op voor een reeks kalenderdagen (Europe/Amsterdam), incl.
    de eindag. Volgt paginering, dus ook geschikt voor bredere periodes
    (bijv. 'dit jaar') met meer dan 250 orders."""
    start = datetime.combine(start_day_ams, datetime.min.time(), tzinfo=AMS).astimezone(timezone.utc)
    end = datetime.combine(end_day_ams_inclusive + timedelta(days=1), datetime.min.time(), tzinfo=AMS).astimezone(timezone.utc)
    fmt = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {
        "status": "any",
        "limit": 250,
        "created_at_min": fmt(start),
        "created_at_max": fmt(end),
    }
    orders = shopify_get_paginated(env, token, "orders.json", params)
    return orders


def build_events(orders, cost_prices):
    """Verwerkt elke order precies 1x tot een 'event': een geldige order_row,
    of een lichte cancelled/no_lines-vermelding (voor de controlelaag). Eén
    platte lijst is de enige bron van waarheid - alle periode- en
    kanaalaggregatie (dag/week/maand/jaar, Totaal/Meta/Google/...) gebeurt
    client-side in JS door deze lijst te filteren en op te tellen. Zo werkt
    elke periode-preset en elk kanaal met exact dezelfde rekenlogica."""
    events = []
    for o in orders:
        day = None
        if o.get("created_at"):
            try:
                day = datetime.fromisoformat(o["created_at"]).astimezone(AMS).date().isoformat()
            except Exception:
                day = None
        if day is None:
            continue

        row, status, _ = process_order(o, cost_prices)
        if status == "cancelled":
            events.append(dict(status="cancelled", day=day, name=o.get("name")))
        elif status == "no_lines":
            events.append(dict(status="no_lines", day=day, name=o.get("name")))
        else:
            row["status"] = "ok"
            events.append(row)
    return events


def load_cost_prices():
    with open(COST_FILE) as f:
        return json.load(f)


def load_trackbee_data():
    """Handmatige snapshot van TrackBee's werkelijke ROAS/spend per dag en
    kanaal (zie trackbee_data.json) - nog geen live koppeling. Ontbreekt het
    bestand, dan draait het dashboard gewoon door zonder werkelijke ROAS."""
    if not os.path.exists(TRACKBEE_FILE):
        return {}
    with open(TRACKBEE_FILE) as f:
        data = json.load(f)
    data.pop("_meta", None)
    return data


def r2(x):
    return round(x + 1e-9, 2)


def classify_channel(order):
    """Grove kanaalclassificatie o.b.v. Shopify's eigen order-attributie
    (referring_site, landing_site UTM/click-ID's, note_attributes).
    Interim-oplossing tot TrackBee's attributiemodel gekoppeld is - retourneert
    (top, sub) zodat de UI kan uitklappen (Meta -> Facebook/Instagram, etc)."""
    landing = order.get("landing_site") or ""
    referring = (order.get("referring_site") or "").lower()
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(landing).query)
    note_attrs = {a.get("name"): a.get("value") for a in (order.get("note_attributes") or [])}

    def qv(key):
        v = qs.get(key)
        return v[0].lower() if v else None

    utm_source = qv("utm_source") or (note_attrs.get("utmSource") or "").lower() or None
    utm_medium = qv("utm_medium")
    has_fbclid = "fbclid" in qs or bool(note_attrs.get("fbc"))
    has_gclid = "gclid" in qs or "gad_source" in qs or "gad_campaignid" in qs
    has_ttclid = "ttclid" in qs or (utm_source == "tiktok")

    # Google
    if has_gclid or (utm_source == "google" and utm_medium in ("cpc", "ppc", "paid")):
        return ("Google", "Google Ads")
    if "google." in referring:
        return ("Google", "Google Organisch")

    # Meta (Facebook + Instagram)
    is_ig = utm_source == "ig" or "instagram.com" in referring
    is_fb = utm_source == "facebook" or "facebook.com" in referring
    if has_fbclid or (utm_medium == "paid" and (is_ig or is_fb)):
        return ("Meta", "Instagram Ads" if is_ig else "Facebook Ads")
    if is_ig:
        return ("Meta", "Instagram Organisch")
    if is_fb:
        return ("Meta", "Facebook Organisch")

    # TikTok
    if has_ttclid:
        return ("TikTok", "TikTok Ads")

    # Direct: geen referrer, geen UTM, kale landingspagina
    if not referring and not utm_source and landing.split("?")[0] in ("", "/"):
        return ("Direct", "Direct")

    label = f"Overig ({referring or utm_source or 'onbekend'})" if (referring or utm_source) else "Overig"
    return ("Overig", label)


def fulfilment_tier_cost(cp, qty):
    """Fulfilmentkosten voor een enkel product-type o.b.v. de staffeltabel
    (1/2/3 stuks). Bij 4+ stuks van hetzelfde product wordt het 3-stuks-tarief
    gebruikt (geen verdere staffel bekend - vereenvoudiging)."""
    tiers = cp.get("fulfilment_tiers", {})
    if qty <= 0:
        return 0.0
    key = str(min(int(round(qty)), 3))
    return tiers.get(key, tiers.get("1", 0.0))


def process_order(o, cost_prices):
    """Verwerkt 1 order tot een order_row (of None als geannuleerd/leeg).
    Retourneert (row_or_None, status, unknown_skus_found) zodat de aanroeper
    dit over dagen/periodes heen kan groeperen en aggregeren."""
    unknown_skus_found = set()

    if o.get("cancelled_at"):
        return None, "cancelled", unknown_skus_found
    line_items = o.get("line_items", [])
    if not line_items:
        return None, "no_lines", unknown_skus_found

    # Build refund map: line_item_id -> daadwerkelijk geretourneerd aantal
    # (korting != refund: een orderregel-korting verlaagt de omzet maar niet
    # de fysiek geleverde/verkochte hoeveelheid; een refund met retour wel)
    refund_qty_by_line = {}
    refund_money_total = 0.0
    for rf in o.get("refunds", []) or []:
        for rli in rf.get("refund_line_items", []) or []:
            li_id = rli.get("line_item_id")
            refund_qty_by_line[li_id] = refund_qty_by_line.get(li_id, 0) + rli.get("quantity", 0)
            refund_money_total += float(rli.get("subtotal", 0)) + float(rli.get("total_tax", 0))

    # Werkelijk betaalde omzet incl. btw op orderniveau: dit is de bron van
    # waarheid (current_total_price houdt al rekening met orderkortingen,
    # ook als die niet als discount_allocation op de orderregel staan).
    order_omzet_incl = float(o.get("current_total_price", o.get("total_price", 0)) or 0)

    # Originele lijstwaarde per regel (vóór korting) - gebruikt om de
    # betaalde omzet naar rato over de regels te verdelen voor de
    # gewogen fee-berekening (Shopify-kosten/overhead).
    original_total = sum(float(li.get("price", 0)) * li.get("quantity", 0) for li in line_items)

    order_inkoop = 0.0
    order_shipping = 0.0
    order_shopify_fee = 0.0
    order_overhead = 0.0
    order_units = 0
    order_problems = []
    eff_qty_by_sku = {}
    line_details = []
    order_has_refund = refund_money_total > 0 or bool(refund_qty_by_line)

    for li in line_items:
        sku = li.get("sku") or ""
        qty = li.get("quantity", 0)
        price = float(li.get("price", 0))
        original_line_value = price * qty
        weight = (original_line_value / original_total) if original_total > 0 else (1 / len(line_items))
        line_omzet_incl = order_omzet_incl * weight
        line_omzet_excl = line_omzet_incl / BTW

        refunded_qty = min(qty, refund_qty_by_line.get(li.get("id"), 0))
        eff_qty = max(0, qty - refunded_qty)
        order_units += eff_qty

        cp = cost_prices.get(sku)
        if not cp:
            unknown_skus_found.add(f"{sku or '(leeg)'} - {li.get('title')}")
            order_problems.append(f"Onbekende SKU: {sku or '(leeg)'} ({li.get('title')})")
            line_details.append(dict(
                sku=sku, title=li.get("title"), qty=qty,
                omzet_incl=line_omzet_incl, omzet_excl=line_omzet_excl,
                inkoop=None, shipping=None,
            ))
            continue

        inkoop = cp["inkoopprijs"] * eff_qty
        shipping = cp["shipping_nl"] * eff_qty
        shopify_fee = cp["shopify_pct"] * line_omzet_incl
        overhead = cp["overhead_pct"] * line_omzet_excl

        order_inkoop += inkoop
        order_shipping += shipping
        order_shopify_fee += shopify_fee
        order_overhead += overhead
        if eff_qty > 0:
            eff_qty_by_sku[sku] = eff_qty_by_sku.get(sku, 0) + eff_qty

        line_details.append(dict(
            sku=sku, title=li.get("title"), qty=qty,
            omzet_incl=line_omzet_incl, omzet_excl=line_omzet_excl,
            inkoop=inkoop, shipping=shipping,
        ))

    order_omzet_excl = order_omzet_incl / BTW

    if order_has_refund:
        order_problems.append("Order heeft (deel)retour - kosten gecorrigeerd op geretourneerd aantal")

    # Fulfilment: per product-type de staffel (1/2/3 stuks) toepassen.
    # Bij meerdere verschillende producten in 1 order: het duurste pakket
    # telt vol mee, elk overig product-pakket voor 50% (1 verzending,
    # 2e+ product goedkoper te verpakken).
    group_fulfilments = sorted(
        (fulfilment_tier_cost(cost_prices[sku], qty) for sku, qty in eff_qty_by_sku.items()),
        reverse=True,
    )
    order_fulfilment = 0.0
    if group_fulfilments:
        order_fulfilment = group_fulfilments[0] + sum(v * 0.5 for v in group_fulfilments[1:])

    order_kosten_totaal = (order_inkoop + order_shipping + order_fulfilment
                            + order_shopify_fee + order_overhead)
    order_marge = order_omzet_excl - order_kosten_totaal
    order_roas = (order_omzet_excl / order_marge) if order_marge > 0 else None
    if order_marge <= 0:
        order_problems.append("Marge vóór ads is nul of negatief - break-even ROAS n.v.t.")

    channel_top, channel_sub = classify_channel(o)
    created_dt_ams = None
    if o.get("created_at"):
        try:
            created_dt_ams = datetime.fromisoformat(o["created_at"]).astimezone(AMS)
        except Exception:
            created_dt_ams = None

    discount_codes = [dc.get("code") for dc in (o.get("discount_codes") or []) if dc.get("code")]

    row = dict(
        name=o.get("name"), created_at=o.get("created_at"),
        day=created_dt_ams.date().isoformat() if created_dt_ams else None,
        lines=line_details, units=order_units,
        omzet_incl=order_omzet_incl, omzet_excl=order_omzet_excl,
        inkoop=order_inkoop, shipping=order_shipping, fulfilment=order_fulfilment,
        shopify_fee=order_shopify_fee, overhead=order_overhead,
        kosten_totaal=order_kosten_totaal, marge=order_marge, roas=order_roas,
        problems=order_problems, channel_top=channel_top, channel_sub=channel_sub,
        has_unknown_sku=bool(unknown_skus_found), has_refund=order_has_refund,
        unknown_lines=sorted(unknown_skus_found), discount_codes=discount_codes,
    )
    return row, "ok", unknown_skus_found


def serialize_event(r):
    if r["status"] != "ok":
        return dict(status=r["status"], day=r["day"], name=r["name"])
    time_str = ""
    if r["created_at"]:
        try:
            time_str = datetime.fromisoformat(r["created_at"]).astimezone(AMS).strftime("%H:%M")
        except Exception:
            time_str = r["created_at"]
    roas_incl = (r["omzet_incl"] / r["marge"]) if r["marge"] > 0 else None
    return dict(
        status="ok", day=r["day"],
        name=r["name"], time=time_str,
        products=", ".join(l["title"] or "-" for l in r["lines"]),
        skus=", ".join(l["sku"] or "-" for l in r["lines"]),
        qtys=", ".join(str(l["qty"]) for l in r["lines"]),
        omzet_incl=r["omzet_incl"], omzet_excl=r["omzet_excl"],
        inkoop=r["inkoop"], shipping=r["shipping"], fulfilment=r["fulfilment"],
        shopify_fee=r["shopify_fee"], overhead=r["overhead"],
        kosten_totaal=r["kosten_totaal"], marge=r["marge"], units=r["units"],
        roas=r["roas"], roas_incl=roas_incl,
        problems="; ".join(r["problems"]) if r["problems"] else "-",
        has_problem=bool(r["problems"]),
        channel_top=r["channel_top"], channel_sub=r["channel_sub"],
        has_unknown_sku=r["has_unknown_sku"], unknown_lines=r["unknown_lines"],
        has_refund=r["has_refund"],
        discount_codes=", ".join(r["discount_codes"]) if r["discount_codes"] else "-",
        has_discount=bool(r["discount_codes"]),
    )


def render_dashboard(events, today_iso, earliest_iso, trackbee_data=None):
    """Beslissingsdashboard: 3 informatielagen (hoofdresultaat / verklaring /
    controle), kanaal+periode-selectie, alles client-side berekend uit 1
    platte event-lijst (zie build_events). TrackBee-werkelijke-ROAS wordt,
    indien beschikbaar, uit een handmatige dag/kanaal-snapshot (trackbee_data)
    getoond; buiten de gedekte dagen/kanalen blijft de placeholder staan
    i.p.v. verzonnen cijfers."""
    events_json = json.dumps(events, default=str)
    trackbee_json = json.dumps(trackbee_data or {}, default=str)

    return f"""<!doctype html>
<html lang="nl">
<head>
<meta charset="utf-8">
<title>Break-even ROAS · beslissingsdashboard</title>
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
    --ff-mono:'SF Mono',Menlo,Consolas,monospace;
    --r-md:14px; --r-lg:20px; --r-pill:999px;
    --shadow-2: 0 4px 14px rgba(18,25,133,.06), 0 1px 3px rgba(18,25,133,.03);
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--c-paper); color:var(--c-ink); font-family:var(--ff-sans); font-size:14px; line-height:1.5; padding: 24px 24px 60px; }}
  .wrap {{ max-width: 1120px; margin: 0 auto; }}
  h1 {{ font-family:var(--ff-display); font-weight:600; font-size:21px; margin:0 0 2px; color:var(--c-navy-dark); }}
  .page-subtitle {{ font-size:13px; color:var(--c-muted); margin-bottom:16px; }}

  /* Toolbar: kanaal + periode (rij 1), subkanaal + weergave (rij 2, alleen indien relevant) */
  .toolbar-row1 {{ display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; margin-bottom:8px; }}
  .toolbar-row2 {{ display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; margin-bottom:16px; min-height:1px; }}
  .channel-select {{ font-weight:600; min-width:160px; }}
  .pill-row {{ display:flex; gap:6px; flex-wrap:wrap; align-items:center; }}
  .pill {{ border:1px solid var(--c-border); background:#fff; color:var(--c-ink); font-size:12px; padding:5px 12px; border-radius:var(--r-pill); cursor:pointer; font-family:var(--ff-sans); }}
  .pill.active {{ background:var(--c-navy-hover); color:#fff; border-color:var(--c-navy-hover); }}
  .pill-empty {{ opacity:.4; cursor:default; }}
  .period-controls {{ display:flex; align-items:center; gap:8px; }}
  select, input[type=date] {{ font-family:var(--ff-sans); font-size:12px; padding:7px 12px; border-radius:var(--r-pill); border:1px solid var(--c-border); background:#fff; color:var(--c-ink); cursor:pointer; }}
  .custom-range {{ display:none; gap:6px; align-items:center; }}
  .custom-range.show {{ display:flex; }}
  .view-toggle {{ display:flex; gap:3px; background:var(--c-surface); border-radius:var(--r-pill); padding:3px; }}
  .view-toggle button {{ border:none; background:transparent; font-size:12px; padding:5px 11px; border-radius:var(--r-pill); cursor:pointer; font-family:var(--ff-sans); color:var(--c-muted); }}
  .view-toggle button.active {{ background:#fff; color:var(--c-navy-dark); font-weight:600; box-shadow:0 1px 2px rgba(0,0,0,.08); }}

  /* Laag 1: hoofdresultaat */
  .hero {{ background:var(--c-navy-dark); color:#fff; border-radius:var(--r-lg); padding:20px 26px; margin-bottom:14px; box-shadow:var(--shadow-2); }}
  .hero-scope-row {{ display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:12px; }}
  .hero-scope {{ font-size:12px; color:rgba(255,255,255,.55); }}
  .btw-toggle {{ display:inline-flex; gap:3px; background:rgba(255,255,255,.08); border-radius:var(--r-pill); padding:3px; flex-shrink:0; }}
  .btw-btn {{ border:none; background:transparent; color:rgba(255,255,255,.6); font-size:11px; padding:5px 11px; border-radius:var(--r-pill); cursor:pointer; font-family:var(--ff-sans); }}
  .btw-btn.active {{ background:#fff; color:var(--c-navy-dark); font-weight:600; }}
  .margin-slider-row {{ background:rgba(255,255,255,.06); border-radius:var(--r-md); padding:12px 16px; margin-bottom:14px; }}
  .margin-slider-label {{ font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:rgba(255,255,255,.55); margin-bottom:8px; }}
  .margin-slider-label span {{ color:#fff; font-weight:700; text-transform:none; letter-spacing:0; font-size:13px; }}
  #lwMarginSlider {{ -webkit-appearance:none; width:100%; height:4px; border-radius:2px; background:rgba(255,255,255,.2); outline:none; cursor:pointer; margin-bottom:8px; }}
  #lwMarginSlider::-webkit-slider-thumb {{ -webkit-appearance:none; width:16px; height:16px; border-radius:50%; background:#fff; cursor:pointer; }}
  #lwMarginSlider::-moz-range-thumb {{ width:16px; height:16px; border-radius:50%; background:#fff; border:none; cursor:pointer; }}
  .margin-slider-result {{ font-size:13px; color:rgba(255,255,255,.85); }}
  .margin-slider-result strong {{ color:#fff; font-family:var(--ff-display); font-size:15px; }}
  .hero-cols {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:20px; margin-bottom:12px; }}
  .hero-col {{ border-left:1px solid rgba(255,255,255,.12); padding-left:16px; }}
  .hero-col:first-child {{ border-left:none; padding-left:0; }}
  .hero-metric-label {{ font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:rgba(255,255,255,.5); margin-bottom:4px; }}
  .hero-metric-value {{ font-family:var(--ff-display); font-size:32px; font-weight:600; line-height:1; }}
  .hero-metric-value.placeholder {{ font-size:15px; font-weight:500; color:rgba(255,255,255,.45); font-family:var(--ff-sans); }}
  .hero-metric-value.neg-value {{ color:#F3B4A8; }}
  .hero-status {{ border-radius:var(--r-md); padding:10px 16px; font-size:13px; font-weight:600; margin-bottom:10px; }}
  .hero-status.status-pending {{ background:rgba(255,255,255,.08); color:rgba(255,255,255,.8); font-weight:500; }}
  .hero-status.status-profit {{ background:var(--c-success-bg); color:var(--c-success); }}
  .hero-status.status-loss {{ background:var(--c-danger-bg); color:var(--c-danger); }}
  .hero-basis {{ font-size:11px; color:rgba(255,255,255,.45); }}

  .quality-row {{ display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px; }}
  .quality-badge {{ display:inline-flex; align-items:center; gap:6px; padding:5px 12px; border-radius:var(--r-pill); font-size:11px; font-weight:600; cursor:default; }}
  .quality-volledig {{ background:var(--c-success-bg); color:var(--c-success); }}
  .quality-grotendeels {{ background:var(--c-warn-bg); color:var(--c-warn); cursor:pointer; }}
  .quality-onvolledig, .quality-onbruikbaar {{ background:var(--c-danger-bg); color:var(--c-danger); cursor:pointer; }}
  .quality-geen {{ background:var(--c-surface); color:var(--c-muted); }}
  .quality-pending {{ background:var(--c-surface); color:var(--c-muted); }}

  /* Data quality detail (uitklapbaar vanaf badge) */
  .quality-detail {{ display:none; background:var(--c-danger-bg); border:1px solid var(--c-danger); color:var(--c-danger); border-radius:var(--r-md); padding:14px 18px; margin-bottom:14px; font-size:13px; }}
  .quality-detail.show {{ display:block; }}
  .quality-detail ul {{ margin:8px 0 0; padding-left:18px; }}

  /* Trend / per-dag */
  .trend-block, .perday-block {{ background:#fff; border:1px solid var(--c-border); border-radius:var(--r-lg); padding:18px 22px; margin-bottom:14px; box-shadow:var(--shadow-2); display:none; }}
  .trend-block.show, .perday-block.show {{ display:block; }}
  .trend-title {{ font-weight:700; color:var(--c-navy-dark); margin-bottom:10px; font-size:13px; }}
  .trend-title-note {{ font-weight:400; color:var(--c-muted); }}
  .trend-legend {{ font-size:12px; color:var(--c-muted); margin-top:8px; }}

  /* Laag 2: financiele verklaring */
  .explain-block {{ background:#fff; border:1px solid var(--c-border); border-radius:var(--r-lg); padding:18px 22px; margin-bottom:14px; box-shadow:var(--shadow-2); }}
  .explain-title {{ font-weight:700; color:var(--c-navy-dark); margin-bottom:12px; font-size:14px; }}
  .waterfall {{ display:flex; flex-wrap:wrap; align-items:center; gap:6px; font-size:13px; }}
  .waterfall .step {{ display:flex; flex-direction:column; align-items:center; min-width:82px; }}
  .waterfall .step-label {{ font-size:10px; color:var(--c-muted); text-transform:uppercase; letter-spacing:.04em; margin-bottom:2px; }}
  .waterfall .step-value {{ font-family:var(--ff-display); font-weight:600; font-size:16px; color:var(--c-navy-dark); }}
  .waterfall .step-value.neg {{ color:var(--c-danger); }}
  .waterfall .arrow {{ color:var(--c-muted); font-size:15px; }}
  .waterfall-sub {{ font-size:12px; color:var(--c-muted); margin-top:10px; }}
  .waterfall-sub strong {{ color:var(--c-ink); }}
  .expand-toggle {{ background:none; border:none; color:var(--c-navy); font-size:12px; cursor:pointer; font-family:var(--ff-sans); padding:0; margin-top:12px; text-decoration:underline; }}
  .cost-breakdown {{ display:none; margin-top:12px; padding-top:12px; border-top:1px solid var(--c-border); }}
  .cost-breakdown.show {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; }}
  .cost-item {{ font-size:13px; }}
  .cost-item-label {{ color:var(--c-muted); font-size:11px; text-transform:uppercase; letter-spacing:.04em; }}
  .cost-item-value {{ font-weight:600; color:var(--c-ink); }}

  /* Kanaalvergelijking */
  .compare-block {{ margin-bottom:14px; background:#fff; border:1px solid var(--c-border); border-radius:var(--r-lg); padding:18px 22px; box-shadow:var(--shadow-2); }}
  .compare-title {{ font-family:var(--ff-display); font-size:17px; color:var(--c-navy-dark); margin-bottom:10px; }}
  .compare-issue-note {{ font-size:12px; color:var(--c-warn); background:var(--c-warn-bg); padding:8px 12px; border-radius:var(--r-md); margin-bottom:14px; }}
  .compare-viz-label {{ font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:var(--c-muted); margin-bottom:8px; }}
  .rev-share-bar {{ display:flex; height:26px; border-radius:8px; overflow:hidden; background:var(--c-surface); }}
  .rev-seg {{ position:relative; display:flex; align-items:center; justify-content:center; border-right:2px solid #fff; }}
  .rev-seg:last-child {{ border-right:none; }}
  .rev-seg-label {{ font-size:11px; font-weight:600; color:#fff; text-shadow:0 1px 2px rgba(0,0,0,.25); }}
  .legend-row {{ display:flex; flex-wrap:wrap; gap:14px; margin-top:12px; }}
  .legend-item {{ font-size:12px; color:var(--c-ink); display:flex; align-items:center; gap:6px; }}
  .legend-value {{ color:var(--c-muted); }}
  .legend-swatch {{ display:inline-block; width:9px; height:9px; border-radius:2px; }}
  .roas-bars {{ display:flex; flex-direction:column; gap:8px; }}
  .roas-bar-row {{ display:grid; grid-template-columns:120px 1fr 56px; align-items:center; gap:10px; cursor:pointer; }}
  .roas-bar-label {{ font-size:13px; color:var(--c-ink); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
  .roas-bar-track {{ height:14px; background:var(--c-surface); border-radius:4px; overflow:hidden; }}
  .roas-bar-fill {{ height:100%; border-radius:4px 0 0 4px; min-width:3px; }}
  .roas-bar-value {{ font-size:12px; font-variant-numeric:tabular-nums; color:var(--c-ink); text-align:right; }}
  .table-toggle {{ margin-top:18px; }}
  .table-toggle > summary {{ cursor:pointer; font-size:12px; color:var(--c-navy); text-decoration:underline; list-style:none; }}
  .table-toggle > summary::-webkit-details-marker {{ display:none; }}

  /* Laag 3: controle */
  details.control-section {{ background:#fff; border:1px solid var(--c-border); border-radius:var(--r-lg); margin-bottom:10px; box-shadow:var(--shadow-2); }}
  details.control-section > summary {{ cursor:pointer; padding:13px 20px; font-weight:600; color:var(--c-navy-dark); font-size:13px; list-style:none; display:flex; justify-content:space-between; align-items:center; outline:none; }}
  details.control-section > summary:focus-visible {{ outline:2px solid var(--c-navy-hover); outline-offset:-2px; border-radius:var(--r-md); }}
  details.control-section > summary::-webkit-details-marker {{ display:none; }}
  details.control-section > summary::after {{ content:'▸'; color:var(--c-muted); transition:transform .15s ease; }}
  details.control-section[open] > summary::after {{ transform:rotate(90deg); }}
  .control-section-body {{ padding:0 20px 18px; }}
  .control-count {{ font-weight:400; color:var(--c-muted); margin-left:4px; }}
  .control-count.warn {{ color:var(--c-warn); }}

  table {{ width:100%; border-collapse:collapse; background:#fff; border-radius:var(--r-md); overflow:hidden; }}
  th, td {{ padding:9px 10px; border-bottom:1px solid var(--c-border); font-size:13px; text-align:left; white-space:nowrap; }}
  th {{ background:var(--c-surface); font-size:11px; text-transform:uppercase; letter-spacing:.04em; color:var(--c-muted); }}
  td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .row-total td {{ font-weight:700; background:var(--c-navy-soft); }}
  .row-problem {{ background:var(--c-danger-bg); }}
  .problems {{ color:var(--c-danger); white-space:normal; max-width:220px; }}
  .table-wrap {{ overflow-x:auto; border:1px solid var(--c-border); border-radius:var(--r-md); }}
  .clickable-row {{ cursor:pointer; }}
  .control-list {{ margin-bottom:14px; font-size:13px; }}
  .control-list-label {{ font-weight:600; display:block; margin-bottom:4px; }}
  .control-ok {{ color:var(--c-success); }}
  .control-list ul {{ margin:4px 0 0; padding-left:18px; color:var(--c-danger); }}
</style>
</head>
<body>
<div class="wrap">
  <h1>ROAS &amp; winstgevendheid</h1>
  <div class="page-subtitle">Werkelijke prestaties versus dynamische break-even</div>

  <div class="toolbar-row1">
    <div class="pill-row" id="lwTopPills"></div>
    <div class="period-controls">
      <select id="lwPeriodSelect">
        <option value="vandaag">Vandaag</option>
        <option value="gisteren">Gisteren</option>
        <option value="laatste7">Laatste 7 dagen</option>
        <option value="deze_week">Deze week</option>
        <option value="vorige_week">Vorige week</option>
        <option value="laatste30" selected>Laatste 30 dagen</option>
        <option value="deze_maand">Deze maand</option>
        <option value="vorige_maand">Vorige maand</option>
        <option value="dit_jaar">Dit jaar</option>
        <option value="aangepast">Aangepaste periode</option>
      </select>
      <div class="custom-range" id="lwCustomRange">
        <input type="date" id="lwCustomStart">
        <span style="color:var(--c-muted);font-size:12px;">t/m</span>
        <input type="date" id="lwCustomEnd">
      </div>
    </div>
  </div>
  <div class="toolbar-row2">
    <div class="pill-row sub" id="lwSubPills"></div>
    <div class="view-toggle" id="lwViewToggle">
      <button data-view="totaal" class="active" onclick="lwSetView('totaal')">Overzicht</button>
      <button data-view="perdag" onclick="lwSetView('perdag')">Per dag</button>
      <button data-view="trend" onclick="lwSetView('trend')">Trend</button>
    </div>
  </div>

  <div class="hero">
    <div class="hero-scope-row">
      <div class="hero-scope" id="lwHeroScope"></div>
      <span class="btw-toggle">
        <button class="btw-btn" data-mode="excl" onclick="lwSetBtwMode('excl', this)">Excl. btw</button>
        <button class="btw-btn active" data-mode="incl" onclick="lwSetBtwMode('incl', this)">Incl. btw</button>
      </span>
    </div>
    <div class="margin-slider-row">
      <div class="margin-slider-label">Doel-winstmarge <span id="lwMarginValue">0%</span></div>
      <input type="range" id="lwMarginSlider" min="0" max="10" step="0.5" value="0" oninput="lwOnMarginInput(this.value)">
      <div class="margin-slider-result" id="lwMarginResult"></div>
    </div>
    <div class="hero-cols">
      <div class="hero-col">
        <div class="hero-metric-label">Werkelijke ROAS</div>
        <div class="hero-metric-value placeholder" id="lwRealizedRoas">—</div>
      </div>
      <div class="hero-col">
        <div class="hero-metric-label">Break-even ROAS</div>
        <div class="hero-metric-value roas-dual" id="lwBreakevenRoas" data-excl="" data-incl=""></div>
      </div>
      <div class="hero-col">
        <div class="hero-metric-label">Verschil</div>
        <div class="hero-metric-value placeholder" id="lwDiffRoas">—</div>
      </div>
    </div>
    <div class="hero-status" id="lwHeroStatus"></div>
    <div class="hero-basis" id="lwHeroBasis">Vergelijkingsbasis: omzet excl. btw, na kortingen en refunds</div>
  </div>

  <div class="quality-row">
    <span id="lwQualityBadge"></span>
    <span class="quality-badge quality-pending" id="lwAdDataBadge">Advertentiedata: niet gekoppeld</span>
  </div>
  <div class="quality-detail" id="lwQualityDetail"></div>

  <div class="trend-block" id="lwTrendBlock">
    <div class="trend-title">Break-even ROAS per dag <span class="trend-title-note">(werkelijke ROAS volgt zodra TrackBee gekoppeld is)</span></div>
    <div id="lwTrendChart"></div>
  </div>

  <div class="perday-block" id="lwPerDayBlock"></div>

  <div class="explain-block">
    <div class="explain-title">Hoe komt de break-even ROAS tot stand?</div>
    <div class="waterfall" id="lwWaterfall"></div>
    <div class="waterfall-sub" id="lwWaterfallSub"></div>
    <button class="expand-toggle" onclick="lwToggleCostBreakdown()">Volledige kostenopbouw tonen</button>
    <div class="cost-breakdown" id="lwCostBreakdown"></div>
  </div>

  <div class="compare-block" id="lwCompareBlock"></div>

  <details class="control-section">
    <summary>Ordercontrole <span id="lwOrderCount" class="control-count"></span></summary>
    <div class="control-section-body">
      <div class="table-wrap">
        <table>
          <thead><tr>
            <th>Order</th><th>Datum</th><th>Producten</th><th>SKU's</th><th>Aantal</th>
            <th>Kanaal</th><th>Kortingscode</th>
            <th>Omzet excl. btw</th><th>Inkoop</th><th>Shipping</th><th>Fulfilment</th><th>Betaal/platform</th>
            <th>Overhead</th><th>Kosten excl. ads</th><th>Marge</th><th>Break-even ROAS</th><th>Dataproblemen</th>
          </tr></thead>
          <tbody id="lwOrderTable"></tbody>
        </table>
      </div>
    </div>
  </details>

  <details class="control-section">
    <summary>Datakwaliteit <span id="lwControlCount" class="control-count"></span></summary>
    <div class="control-section-body" id="lwControlBlock"></div>
  </details>
</div>

<script>
const LW_EVENTS = {events_json};
const LW_TRACKBEE = {trackbee_json};
const LW_TODAY = "{today_iso}";
const LW_EARLIEST = "{earliest_iso}";
const LW_TOPS = ['Meta', 'Google', 'TikTok', 'Direct', 'Overig'];

// Vergelijkingsbasis staat vast op excl. btw (zo blijft break-even ROAS altijd
// exact vergelijkbaar met de werkelijke ROAS zodra TrackBee gekoppeld is - die
// twee moeten op dezelfde grondslag staan, anders ontstaat een schijnbare
// winst/verlies-conclusie die alleen door het btw-verschil komt).
let state = {{ top: 'Meta', sub: null, period: 'laatste30', view: 'totaal', btw: 'incl', marginPct: 0, customStart: null, customEnd: null }};
let lwLastG = null;

// ---------- formatting ----------
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

// ---------- date helpers (dagstrings zijn al Amsterdam-kalenderdagen) ----------
function toDate(iso) {{ var p = iso.split('-'); return new Date(Date.UTC(+p[0], +p[1] - 1, +p[2])); }}
function toIso(d) {{ return d.toISOString().slice(0, 10); }}
function addDays(iso, n) {{ var d = toDate(iso); d.setUTCDate(d.getUTCDate() + n); return toIso(d); }}
function startOfWeek(iso) {{ var d = toDate(iso); var day = (d.getUTCDay() + 6) % 7; d.setUTCDate(d.getUTCDate() - day); return toIso(d); }}
function firstOfMonth(iso) {{ var p = iso.split('-'); return p[0] + '-' + p[1] + '-01'; }}
function lastOfMonth(iso) {{ var d = toDate(firstOfMonth(iso)); d.setUTCMonth(d.getUTCMonth() + 1); d.setUTCDate(d.getUTCDate() - 1); return toIso(d); }}
function firstOfYear(iso) {{ return iso.slice(0, 4) + '-01-01'; }}

function lwPeriodRange() {{
  var t = LW_TODAY;
  switch (state.period) {{
    case 'vandaag': return [t, t];
    case 'gisteren': var y = addDays(t, -1); return [y, y];
    case 'laatste7': return [addDays(t, -6), t];
    case 'deze_week': return [startOfWeek(t), t];
    case 'vorige_week': var s = addDays(startOfWeek(t), -7); return [s, addDays(s, 6)];
    case 'laatste30': return [addDays(t, -29), t];
    case 'deze_maand': return [firstOfMonth(t), t];
    case 'vorige_maand': var pm = addDays(firstOfMonth(t), -1); return [firstOfMonth(pm), lastOfMonth(pm)];
    case 'dit_jaar': return [firstOfYear(t), t];
    case 'aangepast': return [state.customStart || LW_EARLIEST, state.customEnd || t];
    default: return [addDays(t, -29), t];
  }}
}}

// ---------- aggregatie (JS-equivalent van summarize_rows) ----------
function lwSummarize(rows) {{
  var agg = {{ n_orders: 0, n_units: 0, omzet_incl: 0, omzet_excl: 0, inkoop: 0, shipping: 0, fulfilment: 0, shopify_fee: 0, overhead: 0 }};
  var unknownOrders = 0, unknownOmzet = 0;
  var unknownProducts = new Set();
  rows.forEach(function(r) {{
    agg.n_orders++; agg.n_units += r.units;
    agg.omzet_incl += r.omzet_incl; agg.omzet_excl += r.omzet_excl;
    agg.inkoop += r.inkoop; agg.shipping += r.shipping; agg.fulfilment += r.fulfilment;
    agg.shopify_fee += r.shopify_fee; agg.overhead += r.overhead;
    if (r.has_unknown_sku) {{
      unknownOrders++; unknownOmzet += r.omzet_excl;
      r.unknown_lines.forEach(function(u) {{ unknownProducts.add(u); }});
    }}
  }});
  var kosten_excl_ads = agg.inkoop + agg.shipping + agg.fulfilment + agg.shopify_fee + agg.overhead;
  var marge = agg.omzet_excl - kosten_excl_ads;
  var marge_pct = agg.omzet_excl > 0 ? marge / agg.omzet_excl : 0;
  var breakeven_roas = marge > 0 ? agg.omzet_excl / marge : null;
  var breakeven_roas_incl = marge > 0 ? agg.omzet_incl / marge : null;
  var omzetShareAffected = agg.omzet_excl > 0 ? unknownOmzet / agg.omzet_excl : 0;
  var quality = 'volledig';
  if (agg.n_orders === 0) quality = 'geen';
  else if (unknownOrders === 0) quality = 'volledig';
  else if (omzetShareAffected < 0.10) quality = 'grotendeels';
  else if (omzetShareAffected < 0.40) quality = 'onvolledig';
  else quality = 'onbruikbaar';
  return Object.assign(agg, {{
    kosten_excl_ads: kosten_excl_ads, marge: marge, marge_pct: marge_pct,
    breakeven_roas: breakeven_roas, breakeven_roas_incl: breakeven_roas_incl,
    max_ads: marge > 0 ? marge : 0, reliable: unknownOrders === 0,
    unknown_orders: unknownOrders, unknown_omzet: unknownOmzet,
    unknown_products: Array.from(unknownProducts), omzet_share_affected: omzetShareAffected,
    quality: quality,
  }});
}}

function lwFilterRows(start, end, top, sub) {{
  return LW_EVENTS.filter(function(e) {{
    if (e.status !== 'ok') return false;
    if (e.day < start || e.day > end) return false;
    if (top !== 'Totaal' && e.channel_top !== top) return false;
    if (sub && e.channel_sub !== sub) return false;
    return true;
  }});
}}
// TrackBee-snapshot: alleen Meta en Google hebben dag-cijfers (zie
// trackbee_data.json). Totaal = som van de kanalen die wél data hebben.
// Geeft null terug zodra er geen enkele dag binnen bereik dekking heeft, of
// het kanaal niet los gemeten wordt (Direct/TikTok/Overig/subkanalen) -
// dan blijft de hero-placeholder gewoon staan i.p.v. een verzonnen cijfer.
function lwGetRealized(start, end, top) {{
  var channels = top === 'Totaal' ? ['Meta', 'Google'] : (top === 'Meta' || top === 'Google') ? [top] : null;
  if (!channels) return null;
  var s = toDate(start), e = toDate(end);
  var daysTotal = Math.round((e - s) / 86400000) + 1;
  var spend = 0, revenue = 0, covered = 0;
  for (var i = 0; i < daysTotal; i++) {{
    var d = addDays(start, i);
    var dayHasAny = false;
    channels.forEach(function(ch) {{
      var v = LW_TRACKBEE[d] && LW_TRACKBEE[d][ch];
      if (v) {{ spend += v.spend; revenue += v.revenue; dayHasAny = true; }}
    }});
    if (dayHasAny) covered++;
  }}
  if (spend <= 0 || covered === 0) return null;
  return {{ spend: spend, revenue: revenue, roas: revenue / spend, daysCovered: covered, daysTotal: daysTotal }};
}}

function lwControlCounts(start, end) {{
  var cancelled = 0, noLines = [], refunded = [];
  LW_EVENTS.forEach(function(e) {{
    if (e.day < start || e.day > end) return;
    if (e.status === 'cancelled') cancelled++;
    else if (e.status === 'no_lines') noLines.push(e.name);
    else if (e.status === 'ok' && e.has_refund) refunded.push(e.name);
  }});
  return {{ cancelled: cancelled, noLines: noLines, refunded: refunded }};
}}

// ---------- pills ----------
function lwSelectTop(top) {{ state.top = top; state.sub = null; lwRenderPills(); lwRender(); }}
function lwSelectSub(sub) {{ state.sub = sub; lwRenderPills(); lwRender(); }}

function lwRenderPills() {{
  var range = lwPeriodRange();
  var allRows = lwFilterRows(range[0], range[1], 'Totaal', null);
  var byTop = {{}};
  allRows.forEach(function(r) {{ (byTop[r.channel_top] = byTop[r.channel_top] || []).push(r); }});

  var topHtml = '<span class="pill' + (state.top === 'Totaal' ? ' active' : '') + '" onclick="lwSelectTop(\\'Totaal\\')">Totaal</span>';
  LW_TOPS.forEach(function(top) {{
    var has = byTop[top] && byTop[top].length > 0;
    var label = has ? top : top + ' — geen data';
    topHtml += '<span class="pill' + (state.top === top ? ' active' : '') + (has ? '' : ' pill-empty') + '" onclick="' + (has ? "lwSelectTop('" + top + "')" : '') + '">' + label + '</span>';
  }});
  document.getElementById('lwTopPills').innerHTML = topHtml;

  var subHtml = '';
  if (state.top !== 'Totaal') {{
    var topRows = byTop[state.top] || [];
    var subs = {{}};
    topRows.forEach(function(r) {{ (subs[r.channel_sub] = subs[r.channel_sub] || []).push(r); }});
    var subKeys = Object.keys(subs);
    if (subKeys.length > 1 || (subKeys.length === 1 && subKeys[0] !== state.top)) {{
      subHtml += '<span class="pill' + (!state.sub ? ' active' : '') + '" onclick="lwSelectSub(null)">Alle ' + state.top + '</span>';
      subKeys.forEach(function(sub) {{
        subHtml += '<span class="pill' + (state.sub === sub ? ' active' : '') + '" onclick="lwSelectSub(\\'' + sub + '\\')">' + sub + '</span>';
      }});
    }}
  }}
  document.getElementById('lwSubPills').innerHTML = subHtml;
}}

// ---------- period/view controls ----------
document.getElementById('lwPeriodSelect').addEventListener('change', function(e) {{
  state.period = e.target.value;
  document.getElementById('lwCustomRange').classList.toggle('show', state.period === 'aangepast');
  if (state.period === 'aangepast' && !state.customStart) {{
    var r = [addDays(LW_TODAY, -29), LW_TODAY];
    state.customStart = r[0]; state.customEnd = r[1];
    document.getElementById('lwCustomStart').value = r[0];
    document.getElementById('lwCustomEnd').value = r[1];
  }}
  lwRenderPills();
  lwRender();
}});
document.getElementById('lwCustomStart').addEventListener('change', function(e) {{ state.customStart = e.target.value; lwRenderPills(); lwRender(); }});
document.getElementById('lwCustomEnd').addEventListener('change', function(e) {{ state.customEnd = e.target.value; lwRenderPills(); lwRender(); }});

function lwSetView(view) {{
  state.view = view;
  document.querySelectorAll('#lwViewToggle button').forEach(function(b) {{ b.classList.toggle('active', b.getAttribute('data-view') === view); }});
  lwRender();
}}
function lwSetBtwMode(mode, btn) {{
  state.btw = mode;
  document.querySelectorAll('.btw-btn').forEach(function(b) {{ b.classList.remove('active'); }});
  document.querySelectorAll('.btw-btn[data-mode="' + mode + '"]').forEach(function(b) {{ b.classList.add('active'); }});
  lwRender();
}}

// Doel-winstmarge-slider: bij een gekozen nettowinstmarge (% van omzet excl. btw,
// na alle kosten EN advertenties) berekent dit welke ROAS daarvoor nodig is.
// Bij 0% marge komt dit exact overeen met de break-even ROAS hierboven.
// Rekenkern (marge m als fractie 0-1, op excl.-btw-basis, C = kosten excl. ads):
//   adspend = omzet_excl * (1 - m) - C  →  ROAS = omzet_excl / adspend
// Hoe hoger de doelmarge, hoe minder ruimte er overblijft voor advertenties,
// dus hoe hoger de vereiste ROAS.
function lwRequiredRoasForMargin(g, marginFrac) {{
  var adspend = g.omzet_excl * (1 - marginFrac) - g.kosten_excl_ads;
  if (adspend <= 0) return null;
  var roasExcl = g.omzet_excl / adspend;
  var ratio = g.omzet_excl > 0 ? g.omzet_incl / g.omzet_excl : 1;
  return {{ excl: roasExcl, incl: roasExcl * ratio, adspend: adspend }};
}}

function lwRenderMarginTarget() {{
  var g = lwLastG;
  var slider = document.getElementById('lwMarginSlider');
  if (!g || g.n_orders === 0 || g.marge <= 0) {{
    slider.disabled = true;
    document.getElementById('lwMarginResult').textContent = 'Geen positieve marge in deze selectie om een winstdoel op te stellen.';
    document.getElementById('lwMarginValue').textContent = '-';
    return;
  }}
  slider.disabled = false;
  var maxMarginPct = Math.max(1, Math.floor(g.marge_pct * 1000) / 10 - 0.5);
  slider.max = maxMarginPct;
  if (+slider.value > maxMarginPct) slider.value = maxMarginPct;
  if (state.marginPct > maxMarginPct) state.marginPct = maxMarginPct;
  slider.value = state.marginPct;

  var mFrac = state.marginPct / 100;
  var res = lwRequiredRoasForMargin(g, mFrac);
  var roasVal = res ? (state.btw === 'incl' ? res.incl : res.excl) : null;
  document.getElementById('lwMarginValue').textContent = state.marginPct.toFixed(1).replace(/\\.0$/, '') + '%';
  document.getElementById('lwMarginResult').innerHTML = res
    ? 'Bij <strong>' + jsPct(mFrac) + '</strong> winstmarge moet de ROAS minimaal <strong>' + jsRoas(roasVal) + '</strong> zijn (max. advertentiebudget dan ' + jsEur(res.adspend) + ').'
    : 'Bij deze marge is geen positief advertentiebudget meer over — verlaag de doelmarge.';
}}

function lwOnMarginInput(val) {{
  state.marginPct = +val;
  lwRenderMarginTarget();
}}
function lwToggleQualityDetail() {{ document.getElementById('lwQualityDetail').classList.toggle('show'); }}
function lwToggleCostBreakdown() {{ document.getElementById('lwCostBreakdown').classList.toggle('show'); }}

function lwSelectTrendDay(day) {{
  state.period = 'aangepast';
  state.customStart = day;
  state.customEnd = day;
  state.view = 'totaal';
  document.getElementById('lwPeriodSelect').value = 'aangepast';
  document.getElementById('lwCustomRange').classList.add('show');
  document.getElementById('lwCustomStart').value = day;
  document.getElementById('lwCustomEnd').value = day;
  document.querySelectorAll('#lwViewToggle button').forEach(function(b) {{ b.classList.toggle('active', b.getAttribute('data-view') === 'totaal'); }});
  lwRenderPills();
  lwRender();
}}

// ---------- rendering ----------
var LW_QUALITY_LABEL = {{ volledig: 'Volledig', grotendeels: 'Grotendeels volledig', onvolledig: 'Onvolledig', onbruikbaar: 'Onbruikbaar', geen: 'Geen data' }};

function lwShortDate(iso) {{ return toDate(iso).toLocaleDateString('nl-NL', {{ day: 'numeric', month: 'short' }}); }}

function lwScopeLabel() {{
  var range = lwPeriodRange();
  var scope = state.top === 'Totaal' ? 'Totaal' : state.top + (state.sub ? ' · ' + state.sub : ' · alle');
  var dateStr = range[0] === range[1] ? lwShortDate(range[0]) : lwShortDate(range[0]) + '–' + lwShortDate(range[1]);
  return scope + ' · ' + dateStr;
}}

function lwRenderWaterfall(g) {{
  var omzetVal = state.btw === 'incl' ? g.omzet_incl : g.omzet_excl;
  var omzetLabel = state.btw === 'incl' ? 'Omzet incl. btw' : 'Omzet excl. btw';
  var steps = [
    [omzetLabel, omzetVal, false],
    ['Inkoop', -g.inkoop, true],
    ['Inbound shipping', -g.shipping, true],
    ['Fulfilment', -g.fulfilment, true],
    ['Betaal- en platformkosten', -g.shopify_fee, true],
    ['Overhead', -g.overhead, true],
    ['Beschikbaar v. ads', g.marge, false],
  ];
  var html = '';
  steps.forEach(function(s, i) {{
    if (i > 0) html += '<span class="arrow">→</span>';
    html += '<div class="step"><div class="step-label">' + s[0] + '</div><div class="step-value' + (s[2] && s[1] < 0 ? ' neg' : '') + '">' + (s[2] ? '−' : '') + jsEur(Math.abs(s[1])) + '</div></div>';
  }});
  document.getElementById('lwWaterfall').innerHTML = html;

  var margePct = g.omzet_excl > 0 ? g.marge / g.omzet_excl : 0;
  var cpa = g.n_orders > 0 ? g.marge / g.n_orders : null;
  document.getElementById('lwWaterfallSub').innerHTML =
    '<strong>' + jsEur(g.marge) + '</strong> (' + jsPct(margePct) + ' van omzet excl. btw) is het maximale advertentiebudget om quitte te spelen' +
    (cpa !== null ? ' — break-even CPA <strong>' + jsEur(cpa) + '</strong> per order' : '') + '.' +
    '<br>Omzet is al na kortingen en (deels) refunds. Kosten (inkoop t/m overhead) zijn bedragen zonder btw-component en blijven dus gelijk in beide weergaves — alleen de omzet bovenaan wisselt mee met de toggle.';

  // Alleen aanvullen wat de waterfall hierboven nog niet toont (geen dubbele
  // regels voor inkoop/shipping/fulfilment/betaalkosten/overhead).
  document.getElementById('lwCostBreakdown').innerHTML = [
    ['Kosten excl. advertenties (subtotaal)', jsEur(g.kosten_excl_ads)],
    ['Omzet incl. btw', jsEur(g.omzet_incl)],
    ['Geldige orders', g.n_orders],
    ['Verkochte producten', (Math.round(g.n_units * 100) / 100)],
    ['Break-even CPA', cpa !== null ? jsEur(cpa) : '-'],
  ].map(function(kv) {{ return '<div class="cost-item"><div class="cost-item-label">' + kv[0] + '</div><div class="cost-item-value">' + kv[1] + '</div></div>'; }}).join('');
}}

// LumeWorks-eigen kanaalpalet (navy-familie, niet het generieke dataviz-default) -
// gevalideerd met validate_palette.js: lightness/chroma/CVD/contrast allemaal PASS
// tegen de --c-paper achtergrond (#FAFAFA).
var LW_SERIES_COLORS = ['#3B42C4', '#B8841F', '#0E8FA0', '#B3447A', '#4F8A2E'];

function lwRenderCompare(range) {{
  var el = document.getElementById('lwCompareBlock');
  if (state.sub) {{ el.innerHTML = ''; return; }}
  var title, rows, onClick;
  if (state.top === 'Totaal') {{
    title = 'Kanaalvergelijking';
    var allRows = lwFilterRows(range[0], range[1], 'Totaal', null);
    var byTop = {{}};
    allRows.forEach(function(r) {{ (byTop[r.channel_top] = byTop[r.channel_top] || []).push(r); }});
    rows = Object.keys(byTop).map(function(k) {{ return [k, lwSummarize(byTop[k])]; }});
    onClick = function(name) {{ return "lwSelectTop('" + name + "')"; }};
  }} else {{
    var topRows = lwFilterRows(range[0], range[1], state.top, null);
    var bySub = {{}};
    topRows.forEach(function(r) {{ (bySub[r.channel_sub] = bySub[r.channel_sub] || []).push(r); }});
    var subKeys = Object.keys(bySub);
    if (subKeys.length < 2) {{ el.innerHTML = ''; return; }}
    title = state.top + ': sub-kanalen';
    rows = subKeys.map(function(k) {{ return [k, lwSummarize(bySub[k])]; }});
    onClick = function(name) {{ return "lwSelectSub('" + name + "')"; }};
  }}
  rows.sort(function(a, b) {{ return b[1].omzet_excl - a[1].omzet_excl; }});
  rows.forEach(function(kv, i) {{ kv[2] = LW_SERIES_COLORS[i % LW_SERIES_COLORS.length]; }});

  var omzetKey = state.btw === 'incl' ? 'omzet_incl' : 'omzet_excl';
  var roasKey = state.btw === 'incl' ? 'breakeven_roas_incl' : 'breakeven_roas';
  var totalOmzet = rows.reduce(function(s, kv) {{ return s + kv[1][omzetKey]; }}, 0);
  var maxRoas = Math.max.apply(null, rows.map(function(kv) {{ return kv[1][roasKey] || 0; }}).concat([0.01])) * 1.15;
  var qualitiesDiffer = new Set(rows.map(function(kv) {{ return kv[1].quality; }})).size > 1;
  var anyIssue = rows.some(function(kv) {{ return kv[1].quality !== 'volledig' && kv[1].quality !== 'geen'; }});

  // Omzetaandeel: 1 gestapelde balk, categorische kleur = kanaal-identiteit
  var segs = rows.map(function(kv) {{
    var name = kv[0], g = kv[1], color = kv[2];
    var share = totalOmzet > 0 ? g[omzetKey] / totalOmzet : 0;
    var pctLabel = jsPct(share);
    var wide = share > 0.16;
    return '<div class="rev-seg" style="flex:' + Math.max(share, 0.002) + ';background:' + color + ';" title="' + name + ': ' + jsEur(g[omzetKey]) + ' (' + pctLabel + ')">' +
      (wide ? '<span class="rev-seg-label">' + pctLabel + '</span>' : '') + '</div>';
  }}).join('');
  var legend = rows.map(function(kv) {{
    return '<div class="legend-item"><span class="legend-swatch" style="background:' + kv[2] + ';"></span>' + kv[0] + ' <span class="legend-value">' + jsEur(kv[1][omzetKey]) + '</span></div>';
  }}).join('');

  // Break-even ROAS: horizontale balk per kanaal, zelfde kleur = identiteit-koppeling
  var roasBars = rows.map(function(kv) {{
    var name = kv[0], g = kv[1], color = kv[2];
    var val = g[roasKey];
    var widthPct = val ? Math.min(100, (val / maxRoas) * 100) : 0;
    return '<div class="roas-bar-row" onclick="' + onClick(name) + '">' +
      '<div class="roas-bar-label">' + name + '</div>' +
      '<div class="roas-bar-track"><div class="roas-bar-fill" style="width:' + widthPct + '%;background:' + color + ';"></div></div>' +
      '<div class="roas-bar-value">' + jsRoas(val) + '</div></div>';
  }}).join('');

  var issueNote = (!qualitiesDiffer && anyIssue) ? '<div class="compare-issue-note">Let op: databetrouwbaarheid van alle rijen hier is ' + LW_QUALITY_LABEL[rows[0][1].quality].toLowerCase() + '.</div>' : '';
  var qualityCol = qualitiesDiffer;

  var html = '<div class="compare-title">' + title + '</div>' + issueNote +
    '<div class="compare-viz">' +
      '<div class="compare-viz-label">Omzetaandeel</div>' +
      '<div class="rev-share-bar">' + segs + '</div>' +
      '<div class="legend-row">' + legend + '</div>' +
      '<div class="compare-viz-label" style="margin-top:18px;">Break-even ROAS</div>' +
      '<div class="roas-bars">' + roasBars + '</div>' +
    '</div>' +
    '<details class="table-toggle"><summary>Tabel weergeven</summary>' +
    '<div class="table-wrap"><table><thead><tr><th>Kanaal</th><th>Orders</th><th>Omzet</th><th>Break-even ROAS</th>' + (qualityCol ? '<th>Databetrouwbaarheid</th>' : '') + '</tr></thead><tbody>' +
    rows.map(function(kv) {{
      var name = kv[0], g = kv[1];
      return '<tr class="clickable-row" onclick="' + onClick(name) + '">' +
        '<td><span class="legend-swatch" style="background:' + kv[2] + ';"></span>' + name + '</td><td class="num">' + g.n_orders + '</td>' +
        '<td class="num">' + jsEur(g[omzetKey]) + '</td>' +
        '<td class="num">' + jsRoas(g[roasKey]) + '</td>' +
        (qualityCol ? '<td class="num">' + LW_QUALITY_LABEL[g.quality] + '</td>' : '') + '</tr>';
    }}).join('') +
    '</tbody></table></div></details>';
  el.innerHTML = html;
}}

function lwRenderTrend(range, top, sub) {{
  var block = document.getElementById('lwTrendBlock');
  var s = toDate(range[0]), e = toDate(range[1]);
  var nDays = Math.round((e - s) / 86400000) + 1;
  if (state.view !== 'trend' || nDays < 2) {{ block.classList.remove('show'); return; }}
  block.classList.add('show');

  var days = [];
  for (var i = 0; i < nDays; i++) days.push(addDays(range[0], i));
  var points = days.map(function(d) {{
    var rows = lwFilterRows(d, d, top, sub);
    var g = lwSummarize(rows);
    return {{ day: d, roas: g.breakeven_roas, n: g.n_orders }};
  }});
  var valid = points.filter(function(p) {{ return p.roas !== null; }});
  if (valid.length === 0) {{ document.getElementById('lwTrendChart').innerHTML = '<div style="color:var(--c-muted);font-size:13px;">Geen positieve marge in deze periode om te tonen.</div>'; return; }}

  var w = 900, h = 220, padL = 44, padR = 12, padT = 12, padB = 28;
  var minR = Math.min.apply(null, valid.map(function(p) {{ return p.roas; }}));
  var maxR = Math.max.apply(null, valid.map(function(p) {{ return p.roas; }}));
  if (minR === maxR) {{ minR -= 0.2; maxR += 0.2; }}
  var pad = (maxR - minR) * 0.15;
  minR -= pad; maxR += pad;
  var x = function(i) {{ return padL + (w - padL - padR) * (i / Math.max(1, points.length - 1)); }};
  var y = function(v) {{ return padT + (h - padT - padB) * (1 - (v - minR) / (maxR - minR)); }};

  var path = '';
  points.forEach(function(p, i) {{
    if (p.roas === null) return;
    path += (path === '' ? 'M' : 'L') + x(i).toFixed(1) + ',' + y(p.roas).toFixed(1) + ' ';
  }});
  var dots = points.map(function(p, i) {{
    if (p.roas === null) return '';
    var cx = x(i).toFixed(1), cy = y(p.roas).toFixed(1);
    return '<g class="trend-point" style="cursor:pointer;" onclick="lwSelectTrendDay(\\'' + p.day + '\\')">' +
      '<circle cx="' + cx + '" cy="' + cy + '" r="10" fill="transparent"/>' +
      '<circle cx="' + cx + '" cy="' + cy + '" r="4" fill="#121985" stroke="#FAFAFA" stroke-width="2"/>' +
      '<title>' + p.day + ': ' + jsRoas(p.roas) + ' - klik voor detail van deze dag</title></g>';
  }}).join('');
  var labelEvery = Math.ceil(points.length / 8);
  var labels = points.map(function(p, i) {{
    if (i % labelEvery !== 0 && i !== points.length - 1) return '';
    return '<text x="' + x(i).toFixed(1) + '" y="' + (h - 8) + '" font-size="10" fill="#6B7280" text-anchor="middle">' + p.day.slice(5) + '</text>';
  }}).join('');
  var yTicks = [minR, (minR + maxR) / 2, maxR].map(function(v) {{
    return '<text x="' + (padL - 8) + '" y="' + (y(v) + 3).toFixed(1) + '" font-size="10" fill="#6B7280" text-anchor="end">' + v.toFixed(2).replace('.', ',') + 'x</text>' +
      '<line x1="' + padL + '" x2="' + (w - padR) + '" y1="' + y(v).toFixed(1) + '" y2="' + y(v).toFixed(1) + '" stroke="#E5E7EB" stroke-width="1"/>';
  }}).join('');
  var lastValid = null;
  for (var li = points.length - 1; li >= 0; li--) {{ if (points[li].roas !== null) {{ lastValid = li; break; }} }}
  var endLabel = lastValid === null ? '' :
    '<text x="' + (x(lastValid) + 8).toFixed(1) + '" y="' + (y(points[lastValid].roas) - 8).toFixed(1) + '" font-size="12" font-weight="600" fill="#0D1433">' + jsRoas(points[lastValid].roas) + '</text>';

  document.getElementById('lwTrendChart').innerHTML =
    '<svg viewBox="0 0 ' + w + ' ' + h + '" style="width:100%;height:auto;">' + yTicks + '<path d="' + path + '" fill="none" stroke="#121985" stroke-width="2"/>' + dots + labels + endLabel + '</svg>' +
    '<div class="trend-legend">— Break-even ROAS per dag. Dagen zonder positieve marge zijn opengelaten.</div>';
}}

function lwRenderControl(control, range) {{
  function list(label, items) {{
    if (!items || items.length === 0) return '<div class="control-list"><span class="control-list-label">' + label + '</span><span class="control-ok">geen</span></div>';
    return '<div class="control-list"><span class="control-list-label">' + label + '</span><ul>' + items.map(function(i) {{ return '<li>' + i + '</li>'; }}).join('') + '</ul></div>';
  }}
  var html = list("Onbekende SKU's / ontbrekende kostprijzen", control.g.unknown_products);
  html += list('Orders zonder orderregels', control.noLines);
  html += list('Geannuleerde orders', control.cancelled ? ['aantal: ' + control.cancelled] : []);
  html += list('Orders met (deel)refund', control.refunded);
  document.getElementById('lwControlBlock').innerHTML = html;
}}

function lwRenderPerDay(range, top, sub) {{
  var block = document.getElementById('lwPerDayBlock');
  var s = toDate(range[0]), e = toDate(range[1]);
  var nDays = Math.round((e - s) / 86400000) + 1;
  if (state.view !== 'perdag') {{ block.classList.remove('show'); return; }}
  block.classList.add('show');

  var days = [];
  for (var i = 0; i < nDays; i++) days.push(addDays(range[0], i));
  var rowsHtml = days.slice().reverse().map(function(d) {{
    var dayRows = lwFilterRows(d, d, top, sub);
    var g = lwSummarize(dayRows);
    return '<tr class="clickable-row" onclick="lwSelectTrendDay(\\'' + d + '\\')">' +
      '<td>' + lwShortDate(d) + '</td><td class="num">' + g.n_orders + '</td>' +
      '<td class="num">' + jsEur(g.omzet_excl) + '</td><td class="num">' + jsEur(g.marge) + '</td>' +
      '<td class="num">' + jsRoas(g.breakeven_roas) + '</td></tr>';
  }}).join('');
  block.innerHTML = '<div class="trend-title">Break-even ROAS per dag — overzicht</div>' +
    '<div class="table-wrap"><table><thead><tr><th>Dag</th><th>Orders</th><th>Omzet excl. btw</th><th>Beschikbaar v. ads</th><th>Break-even ROAS</th></tr></thead><tbody>' + rowsHtml + '</tbody></table></div>' +
    '<div class="trend-legend">Klik een dag voor het detail van die dag. Dit is per-dag prestatie, niet een gemiddelde ROAS (die zou dagen met weinig omzet te zwaar laten meewegen).</div>';
}}

function lwRender() {{
  var range = lwPeriodRange();
  var rows = lwFilterRows(range[0], range[1], state.top, state.sub);
  var g = lwSummarize(rows);
  lwLastG = g;
  lwRenderMarginTarget();

  var heroRoas = state.btw === 'incl' ? g.breakeven_roas_incl : g.breakeven_roas;
  var realized = lwGetRealized(range[0], range[1], state.top);
  document.getElementById('lwHeroScope').textContent = lwScopeLabel();
  document.getElementById('lwBreakevenRoas').textContent = g.n_orders > 0 ? jsRoas(heroRoas) : 'n.v.t.';
  document.getElementById('lwHeroBasis').textContent = 'Vergelijkingsbasis: omzet ' + (state.btw === 'incl' ? 'incl.' : 'excl.') + ' btw, na kortingen en refunds' + (realized ? ' · werkelijke ROAS is TrackBee\\'s eigen ad-platformomzet (mogelijk andere grondslag)' : '');

  var realizedEl = document.getElementById('lwRealizedRoas');
  var diffEl = document.getElementById('lwDiffRoas');
  var statusEl = document.getElementById('lwHeroStatus');

  if (g.n_orders === 0) {{
    realizedEl.className = 'hero-metric-value placeholder'; realizedEl.textContent = '—';
    diffEl.className = 'hero-metric-value placeholder'; diffEl.textContent = '—';
    statusEl.className = 'hero-status status-pending';
    statusEl.textContent = 'Geen orders in deze selectie.';
  }} else if (!realized) {{
    realizedEl.className = 'hero-metric-value placeholder'; realizedEl.textContent = '—';
    diffEl.className = 'hero-metric-value placeholder'; diffEl.textContent = '—';
    statusEl.className = 'hero-status status-pending';
    statusEl.textContent = 'Minimaal benodigde ROAS: ' + jsRoas(heroRoas) + '. Geen TrackBee-data voor dit kanaal/deze periode; winstgevendheid kan daarom nog niet worden beoordeeld.';
  }} else {{
    var diff = realized.roas - heroRoas;
    realizedEl.className = 'hero-metric-value'; realizedEl.textContent = jsRoas(realized.roas);
    diffEl.className = 'hero-metric-value' + (diff >= 0 ? '' : ' neg-value'); diffEl.textContent = (diff >= 0 ? '+' : '−') + jsRoas(Math.abs(diff));
    var estProfit = g.marge - realized.spend;
    var coverageNote = realized.daysCovered < realized.daysTotal ? ' (TrackBee dekt ' + realized.daysCovered + ' van de ' + realized.daysTotal + ' dagen in deze selectie)' : '';
    if (diff > 0.05) {{
      statusEl.className = 'hero-status status-profit';
      statusEl.textContent = 'Winstgevend — werkelijke ROAS (' + jsRoas(realized.roas) + ') ligt boven de benodigde ' + jsRoas(heroRoas) + '. Geschat resultaat: ' + jsEur(estProfit) + coverageNote + '.';
    }} else if (diff < -0.05) {{
      statusEl.className = 'hero-status status-loss';
      statusEl.textContent = 'Verliesgevend — werkelijke ROAS (' + jsRoas(realized.roas) + ') ligt onder de benodigde ' + jsRoas(heroRoas) + '. Geschat resultaat: ' + jsEur(estProfit) + coverageNote + '.';
    }} else {{
      statusEl.className = 'hero-status status-pending';
      statusEl.textContent = 'Rond break-even — werkelijke ROAS (' + jsRoas(realized.roas) + ') ligt dicht bij de benodigde ' + jsRoas(heroRoas) + coverageNote + '.';
    }}
  }}

  var adBadge = document.getElementById('lwAdDataBadge');
  if (adBadge) {{
    adBadge.textContent = realized ? 'Advertentiedata: TrackBee (' + realized.daysCovered + ' dag' + (realized.daysCovered > 1 ? 'en' : '') + ')' : 'Advertentiedata: niet gekoppeld voor deze selectie';
  }}

  var qEl = document.getElementById('lwQualityBadge');
  qEl.innerHTML = '<span class="quality-badge quality-' + g.quality + '" onclick="lwToggleQualityDetail()">Kostprijsdata: ' + LW_QUALITY_LABEL[g.quality] + (g.quality !== 'volledig' && g.quality !== 'geen' ? ' ▸' : '') + '</span>';

  var qd = document.getElementById('lwQualityDetail');
  if (g.quality === 'volledig' || g.quality === 'geen' || g.n_orders === 0) {{
    qd.classList.remove('show'); qd.innerHTML = '';
  }} else {{
    var dir = 'De berekende break-even ROAS ligt hierdoor waarschijnlijk te laag — de werkelijk benodigde ROAS is hoger dan getoond, omdat de kosten van deze producten nog niet zijn meegerekend.';
    var fmtN = function(x) {{ return (Math.round(x * 10) / 10).toString().replace('.', ','); }};
    qd.innerHTML = '<strong>' + fmtN(g.unknown_orders) + ' van de ' + fmtN(g.n_orders) + ' orders</strong> (' + jsEur(g.unknown_omzet) + ' van ' + jsEur(g.omzet_excl) + ' omzet, ' + jsPct(g.omzet_share_affected) + ') bevatten een product zonder kostprijsdata.<br>' + dir +
      '<ul>' + g.unknown_products.map(function(p) {{ return '<li>' + p + '</li>'; }}).join('') + '</ul>' +
      '<div style="margin-top:8px;font-weight:600;">Actie: vul de kostprijs van deze producten aan in het kostprijsbestand.</div>';
  }}

  lwRenderWaterfall(g);
  lwRenderCompare(range);
  lwRenderTrend(range, state.top, state.sub);
  lwRenderPerDay(range, state.top, state.sub);

  document.getElementById('lwOrderCount').textContent = '— ' + rows.length + ' orders';
  var rowsHtml = rows.slice().sort(function(a, b) {{ return a.day < b.day ? 1 : -1; }}).map(function(r) {{
    var channelLabel = r.channel_top + (r.channel_sub && r.channel_sub !== r.channel_top ? ' · ' + r.channel_sub : '');
    return '<tr class="' + (r.has_problem ? 'row-problem' : '') + '">' +
      '<td>' + r.name + '</td><td>' + r.day + ' ' + r.time + '</td><td>' + r.products + '</td><td>' + r.skus + '</td><td>' + r.qtys + '</td>' +
      '<td>' + channelLabel + '</td><td>' + (r.has_discount ? '<strong>' + r.discount_codes + '</strong>' : '-') + '</td>' +
      '<td class="num">' + (state.btw === 'incl' ? jsEur(r.omzet_incl) : jsEur(r.omzet_excl)) + '</td>' +
      '<td class="num">' + jsEur(r.inkoop) + '</td><td class="num">' + jsEur(r.shipping) + '</td>' +
      '<td class="num">' + jsEur(r.fulfilment) + '</td><td class="num">' + jsEur(r.shopify_fee) + '</td>' +
      '<td class="num">' + jsEur(r.overhead) + '</td><td class="num">' + jsEur(r.kosten_totaal) + '</td>' +
      '<td class="num">' + jsEur(r.marge) + '</td><td class="num">' + (state.btw === 'incl' ? jsRoas(r.roas_incl) : jsRoas(r.roas)) + '</td>' +
      '<td class="problems">' + r.problems + '</td></tr>';
  }}).join('');
  var totalRow = '<tr class="row-total"><td colspan="7">Totaal</td>' +
    '<td class="num">' + (state.btw === 'incl' ? jsEur(g.omzet_incl) : jsEur(g.omzet_excl)) + '</td>' +
    '<td class="num">' + jsEur(g.inkoop) + '</td><td class="num">' + jsEur(g.shipping) + '</td>' +
    '<td class="num">' + jsEur(g.fulfilment) + '</td><td class="num">' + jsEur(g.shopify_fee) + '</td>' +
    '<td class="num">' + jsEur(g.overhead) + '</td><td class="num">' + jsEur(g.kosten_excl_ads) + '</td>' +
    '<td class="num">' + jsEur(g.marge) + '</td><td class="num">' + (state.btw === 'incl' ? jsRoas(g.breakeven_roas_incl) : jsRoas(g.breakeven_roas)) + '</td><td></td></tr>';
  document.getElementById('lwOrderTable').innerHTML = rowsHtml + totalRow;

  var cc = lwControlCounts(range[0], range[1]);
  lwRenderControl({{ g: g, noLines: cc.noLines, cancelled: cc.cancelled, refunded: cc.refunded }}, range);
  var issueCount = g.unknown_products.length + cc.noLines.length;
  var ccEl = document.getElementById('lwControlCount');
  ccEl.textContent = issueCount > 0 ? '— ' + issueCount + ' aandachtspunt' + (issueCount > 1 ? 'en' : '') : '— geen problemen';
  ccEl.classList.toggle('warn', issueCount > 0);
}}

lwRenderPills();
lwRender();
</script>
</body>
</html>
"""


def main():
    days_back = int(sys.argv[1]) if len(sys.argv) > 1 else 365
    end_day = datetime.now(AMS).date()
    start_day = end_day - timedelta(days=days_back - 1)

    env = load_env()
    token = get_access_token(env)
    orders = fetch_orders_for_range(env, token, start_day, end_day)
    cost_prices = load_cost_prices()

    raw_events = build_events(orders, cost_prices)
    events = [serialize_event(e) for e in raw_events]

    trackbee_data = load_trackbee_data()

    out_dir = os.path.join(os.path.dirname(__file__))
    out_path = os.path.join(out_dir, "breakeven_dashboard.html")
    html = render_dashboard(events, end_day.isoformat(), start_day.isoformat(), trackbee_data)
    with open(out_path, "w") as f:
        f.write(html)

    n_ok = sum(1 for e in events if e["status"] == "ok")
    print(json.dumps(dict(out_path=out_path, n_orders_raw=len(orders), n_ok=n_ok, range=[start_day.isoformat(), end_day.isoformat()]), indent=2, default=str))


if __name__ == "__main__":
    main()
