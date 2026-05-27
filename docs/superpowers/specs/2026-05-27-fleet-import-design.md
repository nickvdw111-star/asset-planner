# Fleet Import — Design Spec
_Date: 2026-05-27_

## Overview

A one-shot CSV import feature for bulk-loading device fleets into PrintMap. Users download a template, populate it with their fleet data, and upload it via the admin page. The import resolves or creates the full location hierarchy under an existing client and inserts all devices atomically.

---

## Scope

- **In scope:** CSV upload, template download, location hierarchy auto-creation, brand/model normalisation, conflict detection, error report, admin UI.
- **Out of scope:** Partial imports (all-or-nothing), device deduplication by fields other than serial, floorplan coordinate assignment (devices land at 0,0 and are placed manually).

---

## CSV Template

Downloadable from the admin page. Contains a header row and one example row. Generated client-side as a Blob — no backend endpoint needed.

### Columns

| Column | Type | Required | Notes |
|---|---|---|---|
| `client` | text | yes | Must match an existing client name (case-insensitive) |
| `city` | text | yes | Created if it doesn't exist under the client |
| `building` | text | yes | Created if it doesn't exist under the city |
| `floor_level` | integer | yes | 0 = Ground, positive = above ground, negative = basement |
| `floor_label` | text | yes | e.g. "Ground", "Level 1", "Basement" |
| `device_type` | text | yes | `printer`, `mfp`, `scanner`, or `print_server` |
| `label` | text | yes | Display name for the device |
| `brand` | text | no | Normalised on import; added to catalogue if new |
| `model` | text | no | Normalised on import; added to catalogue if new |
| `serial` | text | yes | Used for conflict detection — must be unique across all devices |
| `notes` | text | no | Free text |
| `avg_mono` | integer | no | Average mono pages/month |
| `avg_colour` | integer | no | Average colour pages/month |
| `mono_rate` | decimal | no | Mono cost rate (R/page) |
| `colour_rate` | decimal | no | Colour cost rate (R/page) |
| `rental_amount` | decimal | no | Monthly rental (R/month) |
| `rental_period` | text | no | `No rental`, `12`, `24`, `36`, `72`, or `Evergreen` |

---

## Backend

### Endpoint

```
POST /api/admin/import-devices
Content-Type: multipart/form-data
Field: file (CSV)
```

### Processing — two phases, single transaction

**Phase 1: Validate (no writes)**

For every row in the CSV:
1. Look up client by name (case-insensitive `LOWER(name)`). If not found → collect error.
2. Check serial number against all existing device records. If a match is found → collect error including the existing device's location path.

If any errors were collected → return error response. Nothing is written.

**Phase 2: Commit (only if Phase 1 is clean)**

For every row:
1. Resolve or create City under the matched client (case-insensitive lookup, insert if missing).
2. Resolve or create Building under that city.
3. Resolve or create Floor under that building, matched by `floor_level`. If a floor with that level already exists, use it as-is (label is not updated). If no floor with that level exists, create one using `floor_label` from the CSV.
4. Normalise brand and model:
   - Strip leading/trailing whitespace, collapse internal whitespace, lowercase for lookup.
   - Look up brand in `brands` table. If not found, insert using title-cased version.
   - Look up model under that brand. If not found, insert using title-cased version.
5. Insert device record with `x_pct=0, y_pct=0`. Coordinates are set manually in the floor planner.

All inserts run inside a single SQLite transaction. Any unexpected error triggers a full rollback.

### Response shapes

**Error:**
```json
{
  "status": "error",
  "imported": 0,
  "errors": [
    {
      "row": 3,
      "type": "client_not_found",
      "detail": "Client 'Acme Corp' not found"
    },
    {
      "row": 7,
      "type": "duplicate_serial",
      "detail": "Serial 'ABC123' already exists on Ground Floor, Tower A, Cape Town"
    }
  ]
}
```

**Success:**
```json
{
  "status": "success",
  "imported": 42,
  "created": {
    "cities": 1,
    "buildings": 2,
    "floors": 4
  }
}
```

### Normalisation logic

```python
def normalize_name(s):
    return ' '.join(s.strip().split()).lower()

def title_name(s):
    return ' '.join(s.strip().split()).title()
```

Lookup uses `normalize_name()`; inserts use `title_name()`.

---

## Admin UI (admin.html)

A new **Fleet Import** section added below the existing admin content.

### Elements

**Download Template button**
- Label: "Download Template"
- Behaviour: generates a CSV Blob in the browser and triggers a download as `printmap-fleet-template.csv`
- No server round-trip

**Upload area**
- File input: `.csv` files only
- "Import Devices" button: disabled until a file is selected
- On click: POST file to `/api/admin/import-devices`, show loading state

**Result panel** (rendered after each import attempt)

_Success:_
> ✓ 42 devices imported. 1 city, 2 buildings, and 4 floors were created.

Rendered as a green banner.

_Error:_
> ✗ Import stopped — 2 issues found. Fix them in your CSV and re-upload.

Followed by a table with columns: **Row / Issue / Detail**

Rendered as a red banner + table.

---

## Error types

| Type | Cause |
|---|---|
| `client_not_found` | Client name in CSV doesn't match any existing client |
| `duplicate_serial` | Serial number already exists on a device in the database |
| `parse_error` | Row is malformed (missing required columns, invalid `floor_level` integer, etc.) |

---

## Notes

- A single CSV file may reference multiple clients. Each row is resolved independently — all referenced clients must exist.

## What is not handled

- Updating existing devices from CSV (flag and stop — re-import is not an update operation)
- Floorplan image upload or GPS coordinate assignment via CSV (devices land at 0,0; placed manually in the floor planner)
