# Fleet Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-shot CSV fleet import to the admin page — download template, upload CSV, validate atomically, commit or return flagged errors.

**Architecture:** New `POST /api/admin/import-devices` endpoint in `app.py` runs a two-phase validate-then-commit inside a single SQLite transaction. Phase 1 collects all errors (missing client, duplicate serial, parse issues) and returns early if any found. Phase 2 resolves or creates the location hierarchy and inserts devices. The admin page (`static/admin.html`) gets a Fleet Import section with a client-side template download, file picker, and result panel.

**Tech Stack:** Python 3 + Flask, SQLite (via `sqlite3`), `csv` stdlib, Vanilla JS (no build step), pytest + Flask test client

---

## File Map

| File | Change |
|---|---|
| `app.py` | Add `normalize_name()`, `title_name()`, `POST /api/admin/import-devices` |
| `static/admin.html` | Add Fleet Import section (HTML + JS) |
| `tests/conftest.py` | **Create** — pytest fixtures, temp DB setup |
| `tests/test_import.py` | **Create** — all backend import tests |

---

### Task 1: Test Infrastructure

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_import.py` (skeleton only)

- [ ] **Step 1: Create `tests/conftest.py`**

```python
import os
import sys
import tempfile
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import app as flask_app


@pytest.fixture()
def app(tmp_path):
    db_file = tmp_path / 'test.db'
    flask_app.DB_PATH = db_file
    flask_app.UPLOAD_DIR = tmp_path / 'uploads'
    flask_app.UPLOAD_DIR.mkdir()
    flask_app.init_db()
    flask_app.app.config['TESTING'] = True
    yield flask_app.app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def seeded_client(client):
    """Client fixture with one client already in the DB."""
    client.post('/api/clients', json={'name': 'Acme Corp'})
    return client
```

- [ ] **Step 2: Create `tests/test_import.py` skeleton**

```python
import io
import csv


def make_csv(*rows):
    """Build a CSV bytes object from a list of dicts."""
    if not rows:
        return b''
    headers = list(rows[0].keys())
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=headers)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode()


VALID_ROW = {
    'client': 'Acme Corp',
    'city': 'Johannesburg',
    'building': 'Head Office',
    'floor_level': '0',
    'floor_label': 'Ground',
    'device_type': 'mfp',
    'label': 'Reception MFP',
    'brand': 'Ricoh',
    'model': 'IM C2000',
    'serial': 'ABC12345',
    'notes': '',
    'avg_mono': '5000',
    'avg_colour': '500',
    'mono_rate': '0.08',
    'colour_rate': '0.45',
    'rental_amount': '1500',
    'rental_period': '36',
}
```

- [ ] **Step 3: Verify imports resolve**

```bash
cd /home/kelner/amori3/printer-planner
python -m pytest tests/ --collect-only
```

Expected: `no tests ran`, no import errors.

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py tests/test_import.py
git commit -m "test: add import test infrastructure"
```

---

### Task 2: Backend — Validation (Phase 1)

**Files:**
- Modify: `app.py` — add helpers + endpoint with Phase 1 only (Phase 2 stubbed)
- Modify: `tests/test_import.py` — add validation tests

- [ ] **Step 1: Write failing validation tests**

Append to `tests/test_import.py`:

```python
def post_csv(client, rows, filename='fleet.csv'):
    data = {'file': (io.BytesIO(make_csv(*rows)), filename)}
    return client.post('/api/admin/import-devices',
                       data=data, content_type='multipart/form-data')


# ── Validation tests ──────────────────────────────────────────────────────────

def test_missing_file_returns_error(seeded_client):
    r = seeded_client.post('/api/admin/import-devices',
                           data={}, content_type='multipart/form-data')
    assert r.status_code == 400
    body = r.get_json()
    assert body['status'] == 'error'
    assert body['errors'][0]['type'] == 'parse_error'


def test_missing_required_column_returns_error(seeded_client):
    bad_row = {k: v for k, v in VALID_ROW.items() if k != 'serial'}
    r = post_csv(seeded_client, [bad_row])
    assert r.status_code == 400
    body = r.get_json()
    assert body['status'] == 'error'
    assert any('serial' in e['detail'] for e in body['errors'])


def test_client_not_found_returns_error(seeded_client):
    row = {**VALID_ROW, 'client': 'Nonexistent Corp'}
    r = post_csv(seeded_client, [row])
    assert r.status_code == 422
    body = r.get_json()
    assert body['status'] == 'error'
    assert body['errors'][0]['type'] == 'client_not_found'
    assert 'Nonexistent Corp' in body['errors'][0]['detail']


def test_client_match_is_case_insensitive(seeded_client):
    row = {**VALID_ROW, 'client': 'acme corp'}  # lowercase
    r = post_csv(seeded_client, [row])
    assert r.status_code == 200
    assert r.get_json()['status'] == 'success'


def test_duplicate_serial_in_db_returns_error(seeded_client):
    # First import succeeds
    r1 = post_csv(seeded_client, [VALID_ROW])
    assert r1.get_json()['status'] == 'success'
    # Second import with same serial fails
    row2 = {**VALID_ROW, 'label': 'Another MFP'}
    r2 = post_csv(seeded_client, [row2])
    assert r2.status_code == 422
    body = r2.get_json()
    assert body['status'] == 'error'
    assert body['errors'][0]['type'] == 'duplicate_serial'
    assert 'ABC12345' in body['errors'][0]['detail']


def test_duplicate_serial_within_csv_returns_error(seeded_client):
    row2 = {**VALID_ROW, 'label': 'Copy'}
    r = post_csv(seeded_client, [VALID_ROW, row2])
    assert r.status_code == 422
    body = r.get_json()
    assert body['status'] == 'error'
    assert body['errors'][0]['type'] == 'duplicate_serial'


def test_invalid_floor_level_returns_parse_error(seeded_client):
    row = {**VALID_ROW, 'floor_level': 'top', 'serial': 'XYZ999'}
    r = post_csv(seeded_client, [row])
    assert r.status_code == 422
    body = r.get_json()
    assert body['errors'][0]['type'] == 'parse_error'
    assert 'floor_level' in body['errors'][0]['detail']


def test_multiple_errors_all_collected(seeded_client):
    row1 = {**VALID_ROW, 'client': 'NoExist1', 'serial': 'S001'}
    row2 = {**VALID_ROW, 'client': 'NoExist2', 'serial': 'S002'}
    r = post_csv(seeded_client, [row1, row2])
    body = r.get_json()
    assert len(body['errors']) == 2
```

- [ ] **Step 2: Run tests — confirm they all fail**

```bash
cd /home/kelner/amori3/printer-planner
python -m pytest tests/test_import.py -v 2>&1 | head -40
```

Expected: all tests `FAILED` with `404` or `AttributeError` (endpoint doesn't exist yet).

- [ ] **Step 3: Add helpers and Phase 1 endpoint to `app.py`**

Add the following imports at the top of `app.py` (after existing imports):

```python
import csv
import io
```

Add the following two helpers immediately before the `# ── Helpers ──` section (around line 843):

```python
def normalize_name(s):
    return ' '.join(s.strip().split()).lower()

def title_name(s):
    return ' '.join(s.strip().split()).title()
```

Add the following route after the `# ── Tree ──` section and before `# ── Helpers ──`:

```python
# ── Fleet Import ──────────────────────────────────────────────────────────────

IMPORT_REQUIRED_COLS = {'client', 'city', 'building', 'floor_level', 'floor_label',
                        'device_type', 'label', 'serial'}

@app.route('/api/admin/import-devices', methods=['POST'])
def import_devices():
    file = request.files.get('file')
    if not file:
        return jsonify({'status': 'error', 'imported': 0,
                        'errors': [{'row': 0, 'type': 'parse_error',
                                    'detail': 'No file provided'}]}), 400

    try:
        content = file.read().decode('utf-8-sig')
        reader  = csv.DictReader(io.StringIO(content))
        rows    = list(reader)
        fieldnames = set(reader.fieldnames or [])
    except Exception as exc:
        return jsonify({'status': 'error', 'imported': 0,
                        'errors': [{'row': 0, 'type': 'parse_error',
                                    'detail': f'Could not read CSV: {exc}'}]}), 400

    missing_cols = IMPORT_REQUIRED_COLS - fieldnames
    if missing_cols:
        return jsonify({'status': 'error', 'imported': 0,
                        'errors': [{'row': 0, 'type': 'parse_error',
                                    'detail': f'Missing required columns: {", ".join(sorted(missing_cols))}'}]}), 400

    errors = []
    seen_serials = {}  # serial -> first row number (1-based, header = row 1)

    with get_db() as db:
        for i, row in enumerate(rows, start=2):
            # floor_level must be integer
            try:
                int(row.get('floor_level', ''))
            except (ValueError, TypeError):
                errors.append({'row': i, 'type': 'parse_error',
                               'detail': f"floor_level must be an integer, got: '{row.get('floor_level', '')}'"}); continue

            # serial required
            serial = row.get('serial', '').strip()
            if not serial:
                errors.append({'row': i, 'type': 'parse_error',
                               'detail': 'serial is required'}); continue

            # duplicate serial within CSV
            if serial in seen_serials:
                errors.append({'row': i, 'type': 'duplicate_serial',
                               'detail': f"Serial '{serial}' already appears on row {seen_serials[serial]} of this CSV"}); continue
            seen_serials[serial] = i

            # client must exist
            client_name = row.get('client', '').strip()
            client_row  = db.execute(
                'SELECT id FROM clients WHERE LOWER(name) = ?',
                (normalize_name(client_name),)
            ).fetchone()
            if not client_row:
                errors.append({'row': i, 'type': 'client_not_found',
                               'detail': f"Client '{client_name}' not found"}); continue

            # duplicate serial in DB
            existing = db.execute('''
                SELECT d.serial, f.label AS floor_label,
                       b.name AS building_name, ci.name AS city_name
                FROM devices d
                JOIN floors    f  ON f.id  = d.floor_id
                JOIN buildings b  ON b.id  = f.building_id
                JOIN cities    ci ON ci.id = b.city_id
                WHERE d.serial = ?
            ''', (serial,)).fetchone()
            if existing:
                errors.append({'row': i, 'type': 'duplicate_serial',
                               'detail': (f"Serial '{serial}' already exists on "
                                          f"{existing['floor_label']}, "
                                          f"{existing['building_name']}, "
                                          f"{existing['city_name']}")}); continue

    if errors:
        return jsonify({'status': 'error', 'imported': 0, 'errors': errors}), 422

    # Phase 2 — commit (Task 3)
    return jsonify({'status': 'success', 'imported': 0, 'created': {'cities': 0, 'buildings': 0, 'floors': 0}})
```

- [ ] **Step 4: Run validation tests — confirm they pass**

```bash
cd /home/kelner/amori3/printer-planner
python -m pytest tests/test_import.py -v -k "not success and not commit"
```

Expected: all tests listed in Step 1 pass. The `test_client_match_is_case_insensitive` test may return `status: success` with `imported: 0` — that is acceptable for now.

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_import.py
git commit -m "feat: add fleet import endpoint — Phase 1 validation"
```

---

### Task 3: Backend — Commit (Phase 2)

**Files:**
- Modify: `app.py` — replace Phase 2 stub with full commit logic
- Modify: `tests/test_import.py` — add commit tests

- [ ] **Step 1: Write failing commit tests**

Append to `tests/test_import.py`:

```python
# ── Commit tests ──────────────────────────────────────────────────────────────

def test_successful_import_returns_correct_counts(seeded_client):
    r = post_csv(seeded_client, [VALID_ROW])
    assert r.status_code == 200
    body = r.get_json()
    assert body['status'] == 'success'
    assert body['imported'] == 1
    assert body['created']['cities'] == 1
    assert body['created']['buildings'] == 1
    assert body['created']['floors'] == 1


def test_device_appears_in_tree_after_import(seeded_client):
    post_csv(seeded_client, [VALID_ROW])
    tree = seeded_client.get('/api/tree').get_json()
    acme = next(c for c in tree if c['name'] == 'Acme Corp')
    assert acme['device_count'] == 1


def test_existing_city_is_reused_not_duplicated(seeded_client):
    row2 = {**VALID_ROW, 'serial': 'XYZ999', 'label': 'Second MFP',
            'building': 'Branch Office', 'floor_level': '1', 'floor_label': '+1'}
    r = post_csv(seeded_client, [VALID_ROW, row2])
    body = r.get_json()
    assert body['status'] == 'success'
    assert body['imported'] == 2
    assert body['created']['cities'] == 1      # same Johannesburg reused
    assert body['created']['buildings'] == 2
    assert body['created']['floors'] == 2


def test_existing_floor_is_reused(seeded_client):
    # Import twice to same floor
    post_csv(seeded_client, [VALID_ROW])
    row2 = {**VALID_ROW, 'serial': 'DEF999', 'label': 'Second MFP'}
    r = post_csv(seeded_client, [row2])
    body = r.get_json()
    assert body['status'] == 'success'
    assert body['created']['floors'] == 0  # floor reused, not created


def test_brand_model_normalisation(seeded_client):
    row = {**VALID_ROW, 'serial': 'NORM001', 'brand': 'ricoh', 'model': 'im  c2000'}
    r = post_csv(seeded_client, [row])
    assert r.get_json()['status'] == 'success'
    # device should have title-cased values
    tree = seeded_client.get('/api/tree').get_json()
    acme = next(c for c in tree if c['name'] == 'Acme Corp')
    city = acme['cities'][0]
    building = city['buildings'][0]
    floor = building['floors'][0]
    devices = seeded_client.get(f"/api/floors/{floor['id']}/devices").get_json()
    d = next(dev for dev in devices if dev['serial'] == 'NORM001')
    assert d['brand'] == 'Ricoh'
    assert d['model'] == 'Im C2000'  # title_name() collapses spaces then title-cases


def test_new_brand_added_to_catalogue(seeded_client):
    row = {**VALID_ROW, 'serial': 'NEW001', 'brand': 'Brandnew Co', 'model': 'X100'}
    post_csv(seeded_client, [row])
    brands = seeded_client.get('/api/brands').get_json()
    assert any(b['name'] == 'Brandnew Co' for b in brands)


def test_all_device_fields_stored(seeded_client):
    r = post_csv(seeded_client, [VALID_ROW])
    assert r.get_json()['status'] == 'success'
    tree = seeded_client.get('/api/tree').get_json()
    acme = next(c for c in tree if c['name'] == 'Acme Corp')
    floor_id = acme['cities'][0]['buildings'][0]['floors'][0]['id']
    devices = seeded_client.get(f'/api/floors/{floor_id}/devices').get_json()
    assert len(devices) == 1
    d = devices[0]
    assert d['serial']        == 'ABC12345'
    assert d['type']          == 'mfp'
    assert d['label']         == 'Reception MFP'
    assert d['avg_mono']      == 5000
    assert d['avg_colour']    == 500
    assert float(d['mono_rate'])   == pytest.approx(0.08)
    assert float(d['colour_rate']) == pytest.approx(0.45)
    assert float(d['rental_amount']) == pytest.approx(1500.0)
    assert d['rental_period'] == '36'
    assert d['x_pct']         == 0.0
    assert d['y_pct']         == 0.0
```

Add `import pytest` to the top of `tests/test_import.py`.

- [ ] **Step 2: Run commit tests — confirm they all fail**

```bash
cd /home/kelner/amori3/printer-planner
python -m pytest tests/test_import.py -v -k "commit or count or tree or reused or normal or brand or field"
```

Expected: all new tests fail (`imported: 0` returned by stub).

- [ ] **Step 3: Replace Phase 2 stub in `app.py`**

Find the line `# Phase 2 — commit (Task 3)` in the `import_devices` function and replace the stub return with:

```python
    # Phase 2 — commit
    counts = {'cities': 0, 'buildings': 0, 'floors': 0}
    imported = 0

    def _safe_float(v):
        try:
            return float(v) if v and str(v).strip() else None
        except (ValueError, TypeError):
            return None

    def _safe_int(v):
        try:
            return int(v) if v and str(v).strip() else 0
        except (ValueError, TypeError):
            return 0

    with get_db() as db:
        for i, row in enumerate(rows, start=2):
            client_name = row['client'].strip()
            client_row  = db.execute(
                'SELECT id FROM clients WHERE LOWER(name) = ?',
                (normalize_name(client_name),)
            ).fetchone()
            client_id = client_row['id']

            # Resolve or create city
            city_name = row['city'].strip()
            city_row  = db.execute(
                'SELECT id FROM cities WHERE client_id = ? AND LOWER(name) = ?',
                (client_id, normalize_name(city_name))
            ).fetchone()
            if city_row:
                city_id = city_row['id']
            else:
                cur = db.execute(
                    'INSERT INTO cities (client_id, name) VALUES (?, ?)',
                    (client_id, title_name(city_name))
                )
                city_id = cur.lastrowid
                counts['cities'] += 1

            # Resolve or create building
            building_name = row['building'].strip()
            building_row  = db.execute(
                'SELECT id FROM buildings WHERE city_id = ? AND LOWER(name) = ?',
                (city_id, normalize_name(building_name))
            ).fetchone()
            if building_row:
                building_id = building_row['id']
            else:
                cur = db.execute(
                    'INSERT INTO buildings (city_id, name) VALUES (?, ?)',
                    (city_id, title_name(building_name))
                )
                building_id = cur.lastrowid
                counts['buildings'] += 1

            # Resolve or create floor (matched by level, not label)
            floor_level_int  = int(row['floor_level'])
            floor_label_text = row.get('floor_label', '').strip() or floor_label(floor_level_int)
            floor_row = db.execute(
                'SELECT id FROM floors WHERE building_id = ? AND level = ?',
                (building_id, floor_level_int)
            ).fetchone()
            if floor_row:
                floor_id = floor_row['id']
            else:
                cur = db.execute(
                    'INSERT INTO floors (building_id, level, label) VALUES (?, ?, ?)',
                    (building_id, floor_level_int, floor_label_text)
                )
                floor_id = cur.lastrowid
                counts['floors'] += 1

            # Normalise and resolve/create brand
            brand_raw = row.get('brand', '').strip()
            brand_str = title_name(brand_raw) if brand_raw else ''
            if brand_raw:
                b_row = db.execute(
                    'SELECT id FROM brands WHERE LOWER(name) = ?',
                    (normalize_name(brand_raw),)
                ).fetchone()
                if not b_row:
                    db.execute('INSERT OR IGNORE INTO brands (name) VALUES (?)', (brand_str,))

            # Normalise and resolve/create model
            model_raw = row.get('model', '').strip()
            model_str = title_name(model_raw) if model_raw else ''
            if model_raw and brand_raw:
                b_row2 = db.execute(
                    'SELECT id FROM brands WHERE LOWER(name) = ?',
                    (normalize_name(brand_raw),)
                ).fetchone()
                if b_row2:
                    m_row = db.execute(
                        'SELECT id FROM models WHERE brand_id = ? AND LOWER(name) = ?',
                        (b_row2['id'], normalize_name(model_raw))
                    ).fetchone()
                    if not m_row:
                        db.execute(
                            'INSERT INTO models (brand_id, name) VALUES (?, ?)',
                            (b_row2['id'], model_str)
                        )

            # Insert device
            rental_period = row.get('rental_period', '').strip() or None
            db.execute('''
                INSERT INTO devices
                    (id, floor_id, type, label, brand, model, serial, notes,
                     avg_mono, avg_colour, mono_rate, colour_rate,
                     rental_amount, rental_period, x_pct, y_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
            ''', (
                str(uuid.uuid4()),
                floor_id,
                row.get('device_type', 'printer').strip().lower(),
                row.get('label', '').strip() or 'Device',
                brand_str,
                model_str,
                row.get('serial', '').strip(),
                row.get('notes', '').strip(),
                _safe_int(row.get('avg_mono')),
                _safe_int(row.get('avg_colour')),
                _safe_float(row.get('mono_rate')),
                _safe_float(row.get('colour_rate')),
                _safe_float(row.get('rental_amount')),
                rental_period,
            ))
            imported += 1

    return jsonify({'status': 'success', 'imported': imported, 'created': counts})
```

- [ ] **Step 4: Run all import tests**

```bash
cd /home/kelner/amori3/printer-planner
python -m pytest tests/test_import.py -v
```

Expected: all tests pass. If `test_brand_model_normalisation` fails on the model name assertion, check your `title_name()` — `'im  c2000'.title()` gives `'Im  C2000'` (spaces preserved after `title()`), which is the expected value.

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_import.py
git commit -m "feat: add fleet import endpoint — Phase 2 commit"
```

---

### Task 4: Admin UI — Fleet Import Section

**Files:**
- Modify: `static/admin.html` — add Fleet Import section

- [ ] **Step 1: Add CSS for import card**

In `static/admin.html`, find the closing `</style>` tag (around line 116) and insert before it:

```css
    .import-card {
      background: var(--surface); border: 1px solid var(--border2); border-radius: 10px;
      padding: 22px; max-width: 540px; margin-bottom: 24px;
    }
    .import-card p { font-size: 13px; color: var(--muted); line-height: 1.7; margin: 0 0 14px; }
    .import-upload-row { display: flex; align-items: center; gap: 10px; margin-top: 14px; }
    .import-upload-row input[type="file"] { flex: 1; font-size: 13px; color: var(--text); }

    #import-result { margin-top: 16px; border-radius: 8px; padding: 14px 16px; font-size: 13px; }
    #import-result.success { background: rgba(34,197,94,0.1); border: 1px solid rgba(34,197,94,0.3); color: #86efac; }
    #import-result.error   { background: rgba(239,68,68,0.1);  border: 1px solid rgba(239,68,68,0.3);  color: #fca5a5; }
    #import-result .err-table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 12px; }
    #import-result .err-table th { text-align: left; padding: 4px 8px; color: var(--muted); font-weight: 600; border-bottom: 1px solid rgba(255,255,255,0.08); }
    #import-result .err-table td { padding: 5px 8px; border-bottom: 1px solid rgba(255,255,255,0.05); vertical-align: top; }
    #import-result .err-table tr:last-child td { border-bottom: none; }
```

- [ ] **Step 2: Add Fleet Import HTML section**

In `static/admin.html`, find the closing `</div>` of `#add-brand-section` (around line 204, the one that closes the `<div id="add-brand-section">` block). Insert the following **after** that `</div>`:

```html
    <!-- Fleet Import -->
    <div id="fleet-import-section">
      <h2>Fleet Import</h2>
      <div class="import-card">
        <p>
          Upload a CSV to bulk-import devices across all locations.<br>
          Clients must already exist. Cities, buildings, and floors are created automatically.<br>
          Any serial number conflict or unknown client stops the entire import.
        </p>
        <button class="btn btn-neutral" onclick="downloadTemplate()">⬇ Download Template</button>
        <div class="import-upload-row">
          <input type="file" id="import-file" accept=".csv">
          <button class="btn btn-primary" id="import-btn" disabled onclick="runImport()">Import Devices</button>
        </div>
        <div id="import-result" style="display:none"></div>
      </div>
    </div>
```

- [ ] **Step 3: Add Fleet Import JavaScript**

In `static/admin.html`, find the closing `</script>` tag (the last one, just before `</body>`). Insert the following **before** `</script>`:

```javascript
// ── Fleet Import ──────────────────────────────────────────────────────────────

document.getElementById('import-file').addEventListener('change', function () {
  document.getElementById('import-btn').disabled = !this.files.length;
  document.getElementById('import-result').style.display = 'none';
});

function downloadTemplate() {
  const headers = [
    'client','city','building','floor_level','floor_label',
    'device_type','label','brand','model','serial','notes',
    'avg_mono','avg_colour','mono_rate','colour_rate','rental_amount','rental_period'
  ];
  const example = [
    'Acme Corp','Johannesburg','Head Office','0','Ground',
    'mfp','Reception MFP','Ricoh','IM C2000','ABC12345','Main entrance',
    '5000','500','0.08','0.45','1500','36'
  ];
  const csv = [headers.join(','), example.join(',')].join('\r\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href = url; a.download = 'printmap-fleet-template.csv';
  document.body.appendChild(a); a.click();
  document.body.removeChild(a); URL.revokeObjectURL(url);
}

async function runImport() {
  const file = document.getElementById('import-file').files[0];
  if (!file) return;

  const btn    = document.getElementById('import-btn');
  const result = document.getElementById('import-result');
  btn.disabled = true;
  btn.textContent = 'Importing…';
  result.style.display = 'none';
  result.className = '';

  const form = new FormData();
  form.append('file', file);

  try {
    const res  = await fetch('/api/admin/import-devices', { method: 'POST', body: form });
    const body = await res.json();
    result.style.display = 'block';

    if (body.status === 'success') {
      const c = body.created;
      const parts = [];
      if (c.cities)    parts.push(`${c.cities} cit${c.cities === 1 ? 'y' : 'ies'}`);
      if (c.buildings) parts.push(`${c.buildings} building${c.buildings === 1 ? '' : 's'}`);
      if (c.floors)    parts.push(`${c.floors} floor${c.floors === 1 ? '' : 's'}`);
      const created = parts.length ? ` ${parts.join(', ')} created.` : '';
      result.className = 'success';
      result.textContent = `✓ ${body.imported} device${body.imported === 1 ? '' : 's'} imported.${created}`;
    } else {
      result.className = 'error';
      const banner = document.createElement('div');
      banner.textContent = `✗ Import stopped — ${body.errors.length} issue${body.errors.length === 1 ? '' : 's'} found. Fix your CSV and re-upload.`;
      const table = document.createElement('table');
      table.className = 'err-table';
      table.innerHTML = '<thead><tr><th>Row</th><th>Issue</th><th>Detail</th></tr></thead>';
      const tbody = document.createElement('tbody');
      body.errors.forEach(e => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${e.row || '—'}</td><td>${e.type}</td><td>${e.detail}</td>`;
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      result.innerHTML = '';
      result.appendChild(banner);
      result.appendChild(table);
    }
  } catch (err) {
    result.style.display = 'block';
    result.className = 'error';
    result.textContent = `✗ Network error: ${err.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Import Devices';
  }
}
```

- [ ] **Step 4: Manual smoke test**

Start the app and verify the UI:

```bash
cd /home/kelner/amori3/printer-planner
python3 app.py &
```

Open `http://localhost:5050/admin` in a browser (or via SSH port forward). Verify:
1. "Fleet Import" section is visible below the "Add Brand" section.
2. "Download Template" downloads `printmap-fleet-template.csv` with correct headers and one example row.
3. "Import Devices" button is disabled until a file is selected.
4. Upload the template as-is (with "Acme Corp" as client) — expect an error about client not found.
5. Create "Acme Corp" client via the dashboard, re-upload — expect success banner with counts.
6. Re-upload the same file — expect a duplicate serial error.

Kill the dev server after testing: `kill %1`

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
cd /home/kelner/amori3/printer-planner
python -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add static/admin.html
git commit -m "feat: add fleet import UI to admin page"
```
