import io
import csv
import pytest


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
    # device should have title-cased, space-collapsed values
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
    assert float(d['mono_rate'])     == pytest.approx(0.08)
    assert float(d['colour_rate'])   == pytest.approx(0.45)
    assert float(d['rental_amount']) == pytest.approx(1500.0)
    assert d['rental_period'] == '36'
    assert d['x_pct']         == 0.0
    assert d['y_pct']         == 0.0
