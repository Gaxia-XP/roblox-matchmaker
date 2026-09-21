# Cooking Battle Match Control Design

This dashboard uses the Nintendo.com (2001) system from
[`VoltAgent/awesome-design-md`](https://github.com/VoltAgent/awesome-design-md/tree/main/design-md/nintendo-2001)
as its visual source of truth, adapted for a live matchmaking control panel.

## Direction

Treat the page as console hardware, not a modern SaaS dashboard. The interface is
a dense, fixed-width faceplate assembled from cool periwinkle metal panels,
carbon command bars, hard bevels, and small warm signal controls.

## Color Roles

| Role | Value | Use |
| --- | --- | --- |
| Carbon | `#21242e` | Page background, command bars, footer |
| Canvas | `#7a8aba` | Outer metal chassis |
| Pale sky | `#9fbee7` | Raised chrome edge |
| Ice | `#c0d5e6` | Metric plates |
| Lavender | `#acace7` | Match-control hero field |
| Chrome indigo | `#3d4f97` | Hard shadows, dividers, secondary text |
| Platinum | `#dedede` | Data rows and inset surfaces |
| Surface | `#ffffff` | Match records and highlighted rows |
| Signal orange | `#f68d1f` | Directional markers and counts only |
| Amber | `#ecab37` | Utility and status labels only |
| Alert red | `#e60012` | Product mark and error state only |

Do not add decorative colors. Warm colors must communicate status, utility, or
direction rather than decorate the page.

## Typography

- Display: Arial Black, uppercase, outlined with a hard indigo shadow.
- Structural labels: Arial Bold, 10–11px, uppercase, `0.5px` tracking.
- Data and body copy: Arial, 10–12px.
- Identifiers: Consolas or another system monospace, 11px.
- Do not load web fonts.

## Geometry and Depth

- Default to sharp or chamfered corners. Do not round every container.
- Build elevation with bright top/left edges and hard indigo bottom/right edges.
- Do not use blurred shadows or glass surfaces.
- Carbon bars use a restrained dot-matrix texture.
- Major gaps are 4px seams; interior spacing follows an 8px base rhythm.
- Desktop canvas is approximately 920px wide and centered.

## Dashboard Layout

1. Carbon command bar with product identity and connection status.
2. Lavender hero plate with the outlined `MATCH CONTROL` wordmark.
3. Four tightly joined telemetry plates.
4. Two-column body: recent matches at two-thirds width, live queue at one-third.
5. Carbon system footer.

Below 760px, stack the queue above recent matches. Below 460px, stack telemetry
plates and team rosters into a single column. Touch targets and readable values
take priority over strict 2001-era dimensions.

## Guardrails

- No floating rounded-card grid.
- No soft gradients, glow fields, glassmorphism, or oversized whitespace.
- No generic hero eyebrow plus marketing CTA composition.
- No invented metrics; display only values returned by the matchmaker API.
- Preserve semantic HTML, live regions, escaping of API content, and responsive
  behavior when changing the visual layer.
