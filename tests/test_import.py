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
