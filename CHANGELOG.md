# Changelog

All notable changes to PrintMap are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

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
