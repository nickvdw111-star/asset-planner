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
