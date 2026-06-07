# Changelog

All notable changes to PrintMap are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

## [0.2.2] - 2026-06-07
### Added
- Replacement scenario tabs appear in TCO Calculator automatically for any replacement floors created in the Planner
- Clicking a replacement tab in TCO loads the devices from that floor (auto-generated from the floor plan on first open); edits auto-save per floor
- Replacement scenario tabs in Planner can be renamed by double-clicking the tab label; name is persisted and reflects in both Planner and TCO
- Backend: `PATCH /api/floors/<id>/rename`, `GET /api/clients/<cid>/replacement-floors`, `GET/PUT /api/floors/<fid>/tco` endpoints

### Fixed
- TCO page now also loads replacement floor tabs when navigated to with a `?client=` URL parameter
- Removed dead "Future State" tab from TCO — replaced entirely by live replacement scenario tabs from the Planner

## [0.2.1] - 2026-06-07
### Added
- Replacement Scenario feature in Planner: click "+ Replacement" to clone the current floor (floor plan + all devices) as a new scenario tab; create as many as needed; delete any replacement with ×
- Scenario bar appears below the planner header whenever one or more replacements exist, showing Original and Replacement tabs for quick switching
- Export PNG, Export List, and Print moved from the header into the sidebar
- Upload / Replace floor plan moved from the header into the sidebar
- Themes section added to Admin: six colour themes (Dark, Light, Midnight, Slate, Ember, Sage) selectable via visual palette cards; choice is persisted in localStorage
- Changelog section on About tab is now scrollable

### Fixed
- About tab content was clipped when changelog was long (overflow: hidden replaced with overflow-y: auto)

## [0.2.0] - 2026-06-07
### Added
- Landing page redesigned as a client hub home screen: stats strip (clients, buildings, devices), client card grid with search, and a "+ New Client" add card
- Client detail view on the home screen: four tool cards (Lifecycle, Planner, TCO Calculator, Reports) for direct navigation, plus a Buildings & Floors section for managing the full city → building → floor hierarchy
- Floor picker modal when opening the Planner from the home screen (auto-navigates if only one floor exists)
- Floor plan upload and floor management (add, delete) directly from the home screen client view
- `/api/dashboard` endpoint providing fleet-wide totals and per-client summaries for the stats strip and client cards
- Navigation bar standardised across all inner pages: Lifecycle → Planner → TCO → Reports | Admin, with current page highlighted; nav links carry the active client parameter
- "← Dashboard" back buttons renamed to "← Home" across all pages

## [0.1.1] - 2026-06-07
### Fixed
- Deleting a device from the TCO current scenario now prompts to also remove it from the floor plan, keeping the map and TCO in sync
- Removed the Add Device button from TCO — devices must originate in the planner (where they have a physical location) and be captured into TCO from there

## [0.1.0] - 2026-06-07
### Added
- Service Agents (GO Branches and B2B contractors) with full contact details (admin, tech manager, service controller)
- Vendor pins on the dashboard Leaflet map: green for GO branches, orange for B2B; client building pins changed to blue
- Clicking a vendor pin shows a popup with all three contacts and phone numbers
- Device edit modal: Service Agent dropdown with live Haversine distance from vendor to building
- Service Agent field mirrored in the dashboard device browser modal (same data regardless of where you open a device)
- Building map pins now show clickable floor links that open the planner directly
- About tab in Admin showing version number, release stage, and SemVer convention
- VERSION file and /api/version endpoint
- CSS zoom replaces PDF re-render zoom in the planner (fixes inversion/corruption bug); works for both image and PDF floor plans
- Hand/pan tool in planner with spacebar shortcut for temporary pan
- Arrow key panning and +/-/0 keyboard zoom shortcuts in planner
- Device edit modal capped at 90vh with internal scroll
- Theme toggle moved from planner header to Admin page
- Page titles rebranded to PrintMap across all pages
