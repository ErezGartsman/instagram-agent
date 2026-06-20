# Analytics pillar — Power BI embed

The Analytics surface (`/analytics`) frames a single Power BI report inside the
cockpit: an Executive KPI strip (real CRM data, ours) over a segmented,
Atelier-themed Power BI embed.

## 1. Connect the report
Set on the backend (Vercel env, never the JS bundle):

- `POWERBI_REPORT_ID` — the report's GUID
- `POWERBI_TENANT_ID` — the Azure tenant (ctid)

The cockpit reads these via `GET /api/cockpit/powerbi` (Supabase-JWT gated) and
embeds `app.powerbi.com/reportEmbed?...&autoAuth=true`. autoAuth uses the
viewer's own Power BI login, so sign in to Power BI in the same browser. Until
configured the surface shows a calm "Connect Power BI" state.

## 2. Apply the Graphite Atelier theme
The embed can't be themed at runtime (autoAuth iframe), so theming is applied
inside the report:

1. Open the report in **Power BI Desktop**.
2. **View → Themes → Browse for themes** → select
   `graphite-atelier-powerbi-theme.json` (this folder).
3. Publish. The report now renders in warm obsidian + champagne bronze.

Power BI's service only renders a fixed font set, so the theme uses **Segoe UI**
(the cockpit's own KPI strip carries the JetBrains Mono / Inter identity). The
obsidian canvas + bronze/sage data colors do the rest.

## 3. (Optional) Per-segment deep links
The segmented control (Pipeline · Community · Bookings) can jump to specific
report pages. Set each view's `pageName` in `../lib/analytics.ts` to the page's
section ObjectId — find them via the Power BI REST API:
`GET /reports/{reportId}/pages`. Empty `pageName` = the report's default page.
