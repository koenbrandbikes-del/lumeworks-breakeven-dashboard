# LumeWorks break-even ROAS dashboard

Genereert `breakeven_dashboard.html`: een interactief beslissingsdashboard
dat per kanaal/periode de dynamische break-even ROAS uit Shopify-orderdata
berekent, en (indien beschikbaar) de werkelijke ROAS uit TrackBee ernaast zet.

## Gebruik

```
python3 breakeven_day.py [dagen_terug]
```

Verwacht configuratie in `~/.config/lumeworks-shopify/`:

- `.env` — `SHOPIFY_SHOP`, `SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET`
- `cost_prices.json` — kostprijzen per SKU (zie dit bestand in de repo als voorbeeld)
- `trackbee_data.json` — optionele handmatige TrackBee-snapshot per dag/kanaal (zie script voor formaat); ontbreekt dit bestand, dan draait het dashboard door zonder werkelijke ROAS

Output: `breakeven_dashboard.html` in dezelfde map.
