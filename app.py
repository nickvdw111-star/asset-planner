import csv
import io
import os
import uuid
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory, abort

BASE_DIR   = Path(__file__).parent
DATA_DIR   = Path(os.environ.get('DATA_DIR', BASE_DIR))
DB_PATH    = DATA_DIR / 'printer_planner.db'
UPLOAD_DIR = DATA_DIR / 'uploads'
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXT = {'.pdf', '.png', '.jpg', '.jpeg', '.webp'}

app = Flask(__name__, static_folder='static', static_url_path='')


# ── Database ──────────────────────────────────────────────────────────────────

def get_db():
    import sqlite3
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys = ON')
    return db


def init_db():
    with get_db() as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS clients (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS cities (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
                name      TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS buildings (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                city_id INTEGER NOT NULL REFERENCES cities(id) ON DELETE CASCADE,
                name    TEXT NOT NULL,
                lat     REAL,
                lng     REAL
            );
            CREATE TABLE IF NOT EXISTS floors (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                building_id    INTEGER NOT NULL REFERENCES buildings(id) ON DELETE CASCADE,
                level          INTEGER NOT NULL DEFAULT 0,
                label          TEXT NOT NULL DEFAULT 'Ground',
                floorplan_path TEXT
            );
            CREATE TABLE IF NOT EXISTS devices (
                id         TEXT PRIMARY KEY,
                floor_id   INTEGER NOT NULL REFERENCES floors(id) ON DELETE CASCADE,
                type       TEXT NOT NULL DEFAULT 'printer',
                label      TEXT NOT NULL DEFAULT 'Device',
                brand      TEXT NOT NULL DEFAULT '',
                model      TEXT NOT NULL DEFAULT '',
                serial     TEXT NOT NULL DEFAULT '',
                notes      TEXT NOT NULL DEFAULT '',
                avg_mono   INTEGER NOT NULL DEFAULT 0,
                avg_colour INTEGER NOT NULL DEFAULT 0,
                x_pct      REAL NOT NULL DEFAULT 0,
                y_pct      REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS brands (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS models (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                brand_id INTEGER NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
                name     TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tco_scenarios (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id  INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
                scenario   TEXT NOT NULL CHECK(scenario IN ('current','future')),
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(client_id, scenario)
            );
            CREATE TABLE IF NOT EXISTS tco_scenario_rows (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                scenario_id INTEGER NOT NULL REFERENCES tco_scenarios(id) ON DELETE CASCADE,
                sort_order  INTEGER NOT NULL DEFAULT 0,
                device_id   TEXT,
                label       TEXT NOT NULL DEFAULT '',
                location    TEXT NOT NULL DEFAULT '',
                brand       TEXT NOT NULL DEFAULT '',
                model       TEXT NOT NULL DEFAULT '',
                serial      TEXT NOT NULL DEFAULT '',
                mono_vol    INTEGER NOT NULL DEFAULT 0,
                colour_vol  INTEGER NOT NULL DEFAULT 0,
                mono_rate   REAL,
                colour_rate REAL,
                rental      REAL,
                period      TEXT
            );
        ''')
        # Migrate existing databases
        mcols = [r[1] for r in db.execute('PRAGMA table_info(models)').fetchall()]
        if 'colour_type' not in mcols:
            db.execute("ALTER TABLE models ADD COLUMN colour_type TEXT DEFAULT 'mono'")
        if 'page_size' not in mcols:
            db.execute("ALTER TABLE models ADD COLUMN page_size TEXT DEFAULT 'A4'")
        if 'mono_rate' not in mcols:
            db.execute('ALTER TABLE models ADD COLUMN mono_rate REAL')
        if 'colour_rate' not in mcols:
            db.execute('ALTER TABLE models ADD COLUMN colour_rate REAL')
        if 'optimiser_allowed' not in mcols:
            db.execute('ALTER TABLE models ADD COLUMN optimiser_allowed INTEGER NOT NULL DEFAULT 0')
        if 'rental_amount' not in mcols:
            db.execute('ALTER TABLE models ADD COLUMN rental_amount REAL')
        if 'device_type' not in mcols:
            db.execute("ALTER TABLE models ADD COLUMN device_type TEXT DEFAULT 'mfp'")

        cols = [r[1] for r in db.execute('PRAGMA table_info(devices)').fetchall()]
        if 'avg_mono' not in cols:
            db.execute('ALTER TABLE devices ADD COLUMN avg_mono INTEGER NOT NULL DEFAULT 0')
        if 'avg_colour' not in cols:
            db.execute('ALTER TABLE devices ADD COLUMN avg_colour INTEGER NOT NULL DEFAULT 0')
        if 'mono_rate' not in cols:
            db.execute('ALTER TABLE devices ADD COLUMN mono_rate REAL')
        if 'colour_rate' not in cols:
            db.execute('ALTER TABLE devices ADD COLUMN colour_rate REAL')
        if 'rental_amount' not in cols:
            db.execute('ALTER TABLE devices ADD COLUMN rental_amount REAL')
        if 'rental_period' not in cols:
            db.execute("ALTER TABLE devices ADD COLUMN rental_period TEXT")
        bcols = [r[1] for r in db.execute('PRAGMA table_info(buildings)').fetchall()]
        if 'lat' not in bcols:
            db.execute('ALTER TABLE buildings ADD COLUMN lat REAL')
        if 'lng' not in bcols:
            db.execute('ALTER TABLE buildings ADD COLUMN lng REAL')
        flcols = [r[1] for r in db.execute('PRAGMA table_info(floors)').fetchall()]
        if 'level' not in flcols:
            db.execute('ALTER TABLE floors ADD COLUMN level INTEGER NOT NULL DEFAULT 0')

        # Add unique constraint on models(brand_id, name) if not already present
        # SQLite doesn't support ADD CONSTRAINT, so we check via index
        existing_indexes = [r[1] for r in db.execute("PRAGMA index_list('models')").fetchall()]
        if 'uq_models_brand_name' not in existing_indexes:
            db.execute('CREATE UNIQUE INDEX IF NOT EXISTS uq_models_brand_name ON models(brand_id, name)')

        # Seed brands and models — safe to run every startup (INSERT OR IGNORE / WHERE NOT EXISTS)
        SEED = {
            'Brother': [
                'DCP-L2550DW', 'DCP-L3550CDW',
                'HL-L2350DW', 'HL-L3270CDW', 'HL-L6400DW',
                'MFC-L2750DW', 'MFC-L3770CDW', 'MFC-L5900DW', 'MFC-L6900DW', 'MFC-L8900CDW',
            ],
            'Canon': [
                'i-SENSYS MF742Cdw', 'i-SENSYS MF746Cx',
                'imageRUNNER 2625i', 'imageRUNNER 2630i', 'imageRUNNER 2645i',
                'imageRUNNER ADVANCE C3530i', 'imageRUNNER ADVANCE C3535i',
                'imageRUNNER ADVANCE C5535i', 'imageRUNNER ADVANCE C5540i',
                'imageRUNNER ADVANCE 4525i', 'imageRUNNER ADVANCE 4535i',
                'imageRUNNER C3125i', 'imageRUNNER C3226i', 'imageRUNNER C3326i',
            ],
            'Copystar': [
                'CS-2553ci', 'CS-3212i', 'CS-3253ci', 'CS-4012i', 'CS-4053ci',
                'CS-5004i', 'CS-6003i', 'CS-6053ci',
            ],
            'Develop': [
                'ineo 225i', 'ineo 285i', 'ineo 360i', 'ineo 458i', 'ineo 558i',
                'ineo+ 224e', 'ineo+ 284e', 'ineo+ 364e', 'ineo+ 454e', 'ineo+ 554e',
                'ineo C3300i', 'ineo C3350i', 'ineo C4000i', 'ineo C4050i',
            ],
            'Duplo': [
                'DCC-6000', 'DP-C106-II',
            ],
            'Epson': [
                'EcoTank L3150', 'EcoTank L3250', 'EcoTank L5190', 'EcoTank L6190',
                'SC-T3100', 'SC-T3100N', 'SC-T5100', 'SC-T5100N', 'SC-T7100',
                'WorkForce Pro WF-4820', 'WorkForce Pro WF-C5290',
                'WorkForce Pro WF-C5790', 'WorkForce Pro WF-C20590',
            ],
            'Fujifilm': [
                'ApeosPort C3570', 'ApeosPort C4570', 'ApeosPort C5570', 'ApeosPort C6570',
                'ApeosPort 3560', 'ApeosPort 4560', 'ApeosPort 5560',
            ],
            'Gestetner': [
                'MP 2702', 'MP C2004ex', 'MP C3004ex',
            ],
            'HP': [
                'Color LaserJet Enterprise M555dn',
                'Color LaserJet Pro M454dw', 'Color LaserJet Pro MFP M479fdw',
                'DesignJet T230', 'DesignJet T630', 'DesignJet T830 MFP',
                'LaserJet Enterprise M507dn', 'LaserJet Enterprise MFP M528dn',
                'LaserJet Pro M404dn', 'LaserJet Pro MFP M428fdw',
                'OfficeJet Pro 9010', 'OfficeJet Pro 9020',
                'PageWide Pro 477dw', 'PageWide Pro 552dw',
            ],
            'Infotec': [
                'IM 2702', 'IM 3300', 'IM 4000',
                'IM C2000', 'IM C2500', 'IM C3000', 'IM C3500', 'IM C4500',
            ],
            'Konica Minolta': [
                'bizhub 227', 'bizhub 287', 'bizhub 367', 'bizhub 458', 'bizhub 558', 'bizhub 658e',
                'bizhub C224e', 'bizhub C284e', 'bizhub C364e', 'bizhub C454e', 'bizhub C554e',
                'bizhub C250i', 'bizhub C300i', 'bizhub C360i',
                'bizhub C3300i', 'bizhub C3320i', 'bizhub C4000i', 'bizhub C4050i',
                'bizhub 4000i', 'bizhub 4050i', 'bizhub 4700i', 'bizhub 4750i',
            ],
            'Kyocera': [
                'ECOSYS M2540dn', 'ECOSYS M2635dn', 'ECOSYS M2640idw',
                'ECOSYS M3145dn', 'ECOSYS M3645dn',
                'ECOSYS M6230cidn', 'ECOSYS M6630cidn',
                'ECOSYS P2235dn', 'ECOSYS P3050dn',
                'ECOSYS P6230cdn', 'ECOSYS P6235cdn',
                'TASKalfa 2553ci', 'TASKalfa 3253ci', 'TASKalfa 4053ci', 'TASKalfa 5053ci', 'TASKalfa 6053ci',
                'TASKalfa 2554ci', 'TASKalfa 3554ci', 'TASKalfa 4054ci', 'TASKalfa 5054ci', 'TASKalfa 6054ci',
                'TASKalfa 3212i', 'TASKalfa 4012i', 'TASKalfa 5002i', 'TASKalfa 6002i',
            ],
            'Lanier': [
                'IM 2702', 'IM 3300', 'IM 4000', 'IM 5000',
                'IM C2000', 'IM C2500', 'IM C3000', 'IM C3500', 'IM C4500', 'IM C6000',
            ],
            'Lexmark': [
                'CS421dn', 'CS521dn', 'CS622de', 'CS820de',
                'CX421adn', 'CX522ade', 'CX622ade', 'CX725dhe', 'CX820de',
                'MS421dn', 'MS521dn', 'MS621dn', 'MS821dn',
                'MX421ade', 'MX522adhe', 'MX622adhe', 'MX722ade', 'MX822ade',
            ],
            'Mimaki': [
                'CJV150-160', 'CJV300-160',
                'JV150-160', 'JV300-160',
                'TS100-1600', 'TS300P-1800',
                'UJF-3042MkII', 'UJF-6042MkII', 'UJF-7151plus',
                'UCJV300-160',
            ],
            'Mutoh': [
                'RJ-900X', 'RJ-1300X',
                'ValueJet 1138X', 'ValueJet 1338X', 'ValueJet 1638X', 'ValueJet 2638X',
                'XpertJet 1341SR', 'XpertJet 1641SR',
            ],
            'Nashuatec': [
                'MP 2702', 'MP 3300', 'MP 4000', 'MP 5000',
                'MP C2004ex', 'MP C3004ex', 'MP C4504ex',
            ],
            'OKI': [
                'C332dn', 'C542dn', 'C612dn', 'C712dn',
                'ES5162LP', 'ES7470 MFP', 'ES7480 MFP',
                'MC363dn', 'MC563dn', 'MC883',
                'MB472dnw', 'MB562dnw',
            ],
            'Olivetti': [
                'd-Color MF3023plus', 'd-Color P216L',
            ],
            'Panasonic': [
                'KX-MB2120', 'KX-MB2130', 'KX-MB2170', 'DP-MB310',
            ],
            'Ricoh': [
                'IM 2702', 'IM 3300', 'IM 4000', 'IM 5000', 'IM 6000',
                'IM C2000', 'IM C2500', 'IM C3000', 'IM C3500', 'IM C4500', 'IM C5500', 'IM C6000',
                'MP 2014', 'MP 301', 'MP 501SPF',
                'MP C2004ex', 'MP C2504ex', 'MP C3004ex', 'MP C3504ex',
                'MP C4504ex', 'MP C5504ex', 'MP C6004ex',
                'SP 311SFNw', 'SP 325SFNw', 'SP 377SFNw',
            ],
            'Riso': [
                'ComColor GD7330', 'ComColor GD9630', 'ComColor GL9730',
                'HC5000', 'HC5500',
            ],
            'Roland': [
                'BN-20', 'BN2-20', 'BN2-20A',
                'RF-640', 'RF-640A',
                'TrueVIS SG2-540', 'TrueVIS SG2-640',
                'TrueVIS VG-540', 'TrueVIS VG-640', 'TrueVIS VG2-540', 'TrueVIS VG2-640',
                'VersaStudio BN-20',
            ],
            'Samsung': [
                'ProXpress M3320ND', 'ProXpress M3820DW', 'ProXpress M4020ND',
                'SL-C3060FR', 'SL-C4060FX',
                'Xpress M2835DW', 'Xpress M3065FW', 'Xpress C1860FW',
                'MultiXpress K4300LX', 'MultiXpress X4220RX',
            ],
            'Savin': [
                'IM 2702', 'IM 3300', 'IM 4000',
                'IM C2000', 'IM C2500', 'IM C3000', 'IM C3500', 'IM C4500',
            ],
            'Sharp': [
                'BP-30C25', 'BP-50C26', 'BP-70C31', 'BP-70C36', 'BP-70C45', 'BP-70C55', 'BP-70C65',
                'MX-2651', 'MX-3051', 'MX-3551', 'MX-4051', 'MX-5051', 'MX-6051',
                'MX-3050N', 'MX-3550N', 'MX-4050N', 'MX-5050N', 'MX-6050N',
                'MX-M3050', 'MX-M3550', 'MX-M4050', 'MX-M5050', 'MX-M6050',
            ],
            'Sindoh': [
                'N612', 'N700 Series', 'D410', 'D412',
            ],
            'Toshiba': [
                'e-STUDIO 2515AC', 'e-STUDIO 3015AC', 'e-STUDIO 3515AC',
                'e-STUDIO 4515AC', 'e-STUDIO 5015AC',
                'e-STUDIO 2518A', 'e-STUDIO 3018A', 'e-STUDIO 3518A',
                'e-STUDIO 4518A', 'e-STUDIO 5018A',
                'e-STUDIO 338CS', 'e-STUDIO 408CS',
                'e-STUDIO 5525AC', 'e-STUDIO 6525AC', 'e-STUDIO 7525AC',
            ],
            'Triumph-Adler': [
                '2508ci', '3208ci', '4008ci', '5008ci', '6008ci',
                'P-C2480i', 'P-C3065i', 'P-C3080i',
            ],
            'UTAX': [
                '2508ci', '3208ci', '4008ci', '5008ci',
                'P-C2480i', 'P-C3065i',
            ],
            'Xerox': [
                'AltaLink B8045', 'AltaLink B8055', 'AltaLink B8065', 'AltaLink B8075', 'AltaLink B8090',
                'AltaLink C8030', 'AltaLink C8035', 'AltaLink C8045', 'AltaLink C8055', 'AltaLink C8070',
                'VersaLink B400', 'VersaLink B405',
                'VersaLink B7025', 'VersaLink B7030', 'VersaLink B7035',
                'VersaLink C400', 'VersaLink C405',
                'VersaLink C7000', 'VersaLink C7020', 'VersaLink C7025', 'VersaLink C7030',
                'WorkCentre 6515', 'WorkCentre 6515DN',
            ],
            'Zebra': [
                'GC420d', 'GK420d', 'GK420t', 'GX420d',
                'ZD421', 'ZD620', 'ZD621',
                'ZT230', 'ZT411', 'ZT421', 'ZT610', 'ZT620',
            ],
        }
        for brand_name, models in SEED.items():
            db.execute('INSERT OR IGNORE INTO brands (name) VALUES (?)', (brand_name,))
            row = db.execute('SELECT id FROM brands WHERE name = ?', (brand_name,)).fetchone()
            if not row:
                continue
            brand_id = row['id']
            for model_name in models:
                db.execute('''
                    INSERT INTO models (brand_id, name)
                    SELECT ?, ? WHERE NOT EXISTS (
                        SELECT 1 FROM models WHERE brand_id = ? AND name = ?
                    )
                ''', (brand_id, model_name, brand_id, model_name))


def floor_label(level):
    if level == 0: return 'Ground'
    if level > 0:  return f'+{level}'
    return str(level)


# ── Static pages ──────────────────────────────────────────────────────────────

@app.route('/')
def dashboard():
    return send_from_directory('static', 'index.html')

@app.route('/planner')
def planner():
    return send_from_directory('static', 'planner.html')

@app.route('/tco')
def tco_page():
    return send_from_directory('static', 'tco.html')

@app.route('/reports')
def reports_page():
    return send_from_directory('static', 'reports.html')

@app.route('/admin')
def admin():
    return send_from_directory('static', 'admin.html')


# ── Brands & Models ───────────────────────────────────────────────────────────

@app.route('/api/brands', methods=['GET'])
def list_brands():
    with get_db() as db:
        brands = db.execute('SELECT * FROM brands ORDER BY name').fetchall()
        result = []
        for b in brands:
            bd = dict(b)
            bd['models'] = [dict(m) for m in db.execute(
                'SELECT * FROM models WHERE brand_id = ? ORDER BY name', (b['id'],)
            ).fetchall()]
            result.append(bd)
    return jsonify(result)

@app.route('/api/brands', methods=['POST'])
def create_brand():
    name = (request.json or {}).get('name', '').strip()
    if not name:
        return jsonify({'error': 'name required'}), 400
    with get_db() as db:
        cur = db.execute('INSERT INTO brands (name) VALUES (?)', (name,))
        row = db.execute('SELECT * FROM brands WHERE id = ?', (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201

@app.route('/api/brands/<int:brand_id>', methods=['DELETE'])
def delete_brand(brand_id):
    with get_db() as db:
        db.execute('DELETE FROM brands WHERE id = ?', (brand_id,))
    return '', 204

@app.route('/api/brands/<int:brand_id>/models', methods=['GET'])
def list_models(brand_id):
    with get_db() as db:
        rows = db.execute(
            'SELECT * FROM models WHERE brand_id = ? ORDER BY name', (brand_id,)
        ).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/brands/<int:brand_id>/models', methods=['POST'])
def create_model(brand_id):
    d = request.json or {}
    name = d.get('name', '').strip()
    if not name:
        return jsonify({'error': 'name required'}), 400
    colour_type   = d.get('colour_type', 'mono')
    page_size     = d.get('page_size', 'A4')
    device_type   = d.get('device_type', 'mfp')
    mono_rate     = d.get('mono_rate') or None
    colour_rate   = d.get('colour_rate') or None
    rental_amount = d.get('rental_amount') or None
    with get_db() as db:
        cur = db.execute(
            'INSERT INTO models (brand_id, name, colour_type, page_size, device_type, mono_rate, colour_rate, rental_amount) VALUES (?,?,?,?,?,?,?,?)',
            (brand_id, name, colour_type, page_size, device_type, mono_rate, colour_rate, rental_amount)
        )
        row = db.execute('SELECT * FROM models WHERE id = ?', (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201

@app.route('/api/models/<int:model_id>', methods=['PUT'])
def update_model(model_id):
    d = request.json or {}
    name = d.get('name', '').strip()
    if not name:
        return jsonify({'error': 'name required'}), 400
    colour_type       = d.get('colour_type', 'mono')
    page_size         = d.get('page_size', 'A4')
    device_type       = d.get('device_type', 'mfp')
    mono_rate         = d.get('mono_rate') or None
    colour_rate       = d.get('colour_rate') or None
    rental_amount     = d.get('rental_amount') or None
    optimiser_allowed = 1 if d.get('optimiser_allowed') else 0
    with get_db() as db:
        db.execute(
            'UPDATE models SET name=?, colour_type=?, page_size=?, device_type=?, mono_rate=?, colour_rate=?, rental_amount=?, optimiser_allowed=? WHERE id=?',
            (name, colour_type, page_size, device_type, mono_rate, colour_rate, rental_amount, optimiser_allowed, model_id)
        )
        row = db.execute('SELECT * FROM models WHERE id = ?', (model_id,)).fetchone()
    return jsonify(dict(row))

@app.route('/api/models/<int:model_id>', methods=['DELETE'])
def delete_model(model_id):
    with get_db() as db:
        db.execute('DELETE FROM models WHERE id = ?', (model_id,))
    return '', 204


# ── Clients ───────────────────────────────────────────────────────────────────

@app.route('/api/clients', methods=['GET'])
def list_clients():
    with get_db() as db:
        rows = db.execute('SELECT * FROM clients ORDER BY name').fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/clients', methods=['POST'])
def create_client():
    name = (request.json or {}).get('name', '').strip()
    if not name:
        return jsonify({'error': 'name required'}), 400
    with get_db() as db:
        cur = db.execute('INSERT INTO clients (name) VALUES (?)', (name,))
        row = db.execute('SELECT * FROM clients WHERE id = ?', (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201

@app.route('/api/clients/<int:cid>', methods=['PUT'])
def update_client(cid):
    name = (request.json or {}).get('name', '').strip()
    if not name:
        return jsonify({'error': 'name required'}), 400
    with get_db() as db:
        db.execute('UPDATE clients SET name=? WHERE id=?', (name, cid))
        row = db.execute('SELECT * FROM clients WHERE id=?', (cid,)).fetchone()
    return jsonify(dict(row))

@app.route('/api/clients/<int:cid>/report', methods=['GET'])
def client_report(cid):
    with get_db() as db:
        client = db.execute('SELECT * FROM clients WHERE id=?', (cid,)).fetchone()
        if not client:
            abort(404)
        rows = db.execute('''
            SELECT d.id, d.label, d.type, d.brand, d.model, d.serial,
                   d.avg_mono, d.avg_colour, d.mono_rate, d.colour_rate,
                   d.rental_amount,
                   COALESCE(m.colour_type, 'mono') AS colour_type,
                   COALESCE(m.page_size,   'A4')   AS page_size,
                   b.name  AS building_name, b.id AS building_id,
                   f.label AS floor_label,
                   ci.name AS city_name,   ci.id AS city_id
            FROM devices d
            LEFT JOIN brands br ON br.name = d.brand
            LEFT JOIN models m  ON m.brand_id = br.id AND m.name = d.model
            JOIN floors    f  ON f.id  = d.floor_id
            JOIN buildings b  ON b.id  = f.building_id
            JOIN cities    ci ON ci.id = b.city_id
            WHERE ci.client_id = ?
            ORDER BY ci.name, b.name, f.level, d.label
        ''', (cid,)).fetchall()
        devices = [dict(r) for r in rows]

    def _tco(d):
        return ((d['avg_mono']    or 0) * (d['mono_rate']   or 0) +
                (d['avg_colour']  or 0) * (d['colour_rate'] or 0) +
                (d['rental_amount'] or 0))

    def _clicks(d):
        return ((d['avg_mono']   or 0) * (d['mono_rate']   or 0) +
                (d['avg_colour'] or 0) * (d['colour_rate'] or 0))

    # ── Summary ──
    summary = {
        'devices':       len(devices),
        'mono_vol':      sum(d['avg_mono']       or 0 for d in devices),
        'colour_vol':    sum(d['avg_colour']      or 0 for d in devices),
        'click_charges': sum(_clicks(d)               for d in devices),
        'rental':        sum(d['rental_amount']   or 0 for d in devices),
        'tco':           sum(_tco(d)                  for d in devices),
    }

    # ── By city / building ──
    from collections import OrderedDict
    cities_map = OrderedDict()
    for d in devices:
        cn, bn = d['city_name'], d['building_name']
        if cn not in cities_map:
            cities_map[cn] = dict(name=cn, devices=0, mono_vol=0, colour_vol=0,
                                  click_charges=0, rental=0, tco=0, buildings=OrderedDict())
        city = cities_map[cn]
        city['devices']       += 1
        city['mono_vol']      += d['avg_mono']      or 0
        city['colour_vol']    += d['avg_colour']    or 0
        city['click_charges'] += _clicks(d)
        city['rental']        += d['rental_amount'] or 0
        city['tco']           += _tco(d)
        if bn not in city['buildings']:
            city['buildings'][bn] = dict(name=bn, devices=0, mono_vol=0, colour_vol=0,
                                         click_charges=0, rental=0, tco=0)
        bld = city['buildings'][bn]
        bld['devices']       += 1
        bld['mono_vol']      += d['avg_mono']      or 0
        bld['colour_vol']    += d['avg_colour']    or 0
        bld['click_charges'] += _clicks(d)
        bld['rental']        += d['rental_amount'] or 0
        bld['tco']           += _tco(d)

    cities = []
    for city in cities_map.values():
        c = dict(city)
        c['buildings'] = list(city['buildings'].values())
        cities.append(c)

    # ── By category (page_size × device_type) ──
    cat_map = {}
    for d in devices:
        ps = d['page_size'] or 'A4'
        dt = d['type']      or 'printer'
        ct = d['colour_type'] or 'mono'
        key = (ps, dt)
        if key not in cat_map:
            cat_map[key] = dict(page_size=ps, device_type=dt,
                                label=f'{ps} {dt.upper()}',
                                devices=0, mono_count=0, colour_count=0,
                                mono_vol=0, colour_vol=0,
                                click_charges=0, rental=0, tco=0)
        cat = cat_map[key]
        cat['devices']       += 1
        cat['mono_count']    += (1 if ct == 'mono'   else 0)
        cat['colour_count']  += (1 if ct == 'colour' else 0)
        cat['mono_vol']      += d['avg_mono']      or 0
        cat['colour_vol']    += d['avg_colour']    or 0
        cat['click_charges'] += _clicks(d)
        cat['rental']        += d['rental_amount'] or 0
        cat['tco']           += _tco(d)

    type_order = {'printer': 0, 'mfp': 1, 'scanner': 2, 'server': 3}
    categories = sorted(cat_map.values(),
                        key=lambda c: ({'A4':0,'A3':1}.get(c['page_size'],9),
                                       type_order.get(c['device_type'],9)))

    # ── Top 10 by TCO ──
    top = sorted(
        [dict(label=d['label'] or 'Unnamed', brand=d['brand'], model=d['model'],
              building=d['building_name'], city=d['city_name'], floor=d['floor_label'],
              category=f"{d['page_size']} {(d['type'] or 'printer').upper()}",
              colour_type=d['colour_type'],
              mono_vol=d['avg_mono'] or 0, colour_vol=d['avg_colour'] or 0,
              tco=round(_tco(d), 2)) for d in devices],
        key=lambda x: x['tco'], reverse=True
    )[:10]

    return jsonify(dict(client_name=client['name'],
                        summary=summary, cities=cities,
                        categories=categories, top_devices=top))

@app.route('/api/clients/<int:cid>/devices', methods=['GET'])
def list_client_devices(cid):
    with get_db() as db:
        rows = db.execute('''
            SELECT d.*,
                   b.name  AS building_name,
                   f.label AS floor_label,
                   ci.name AS city_name
            FROM devices d
            JOIN floors    f  ON f.id  = d.floor_id
            JOIN buildings b  ON b.id  = f.building_id
            JOIN cities    ci ON ci.id = b.city_id
            WHERE ci.client_id = ?
            ORDER BY ci.name, b.name, f.level, d.label
        ''', (cid,)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/clients/<int:cid>', methods=['DELETE'])
def delete_client(cid):
    with get_db() as db:
        _cleanup_client_files(db, cid)
        db.execute('DELETE FROM clients WHERE id = ?', (cid,))
    return '', 204


# ── Cities ────────────────────────────────────────────────────────────────────

@app.route('/api/clients/<int:cid>/cities', methods=['POST'])
def create_city(cid):
    name = (request.json or {}).get('name', '').strip()
    if not name:
        return jsonify({'error': 'name required'}), 400
    with get_db() as db:
        cur = db.execute('INSERT INTO cities (client_id, name) VALUES (?, ?)', (cid, name))
        row = db.execute('SELECT * FROM cities WHERE id = ?', (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201

@app.route('/api/cities/<int:city_id>', methods=['PUT'])
def update_city(city_id):
    data = request.json or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'name required'}), 400
    with get_db() as db:
        db.execute('UPDATE cities SET name=? WHERE id=?', (name, city_id))
        row = db.execute('SELECT * FROM cities WHERE id=?', (city_id,)).fetchone()
    return jsonify(dict(row))

@app.route('/api/cities/<int:city_id>', methods=['DELETE'])
def delete_city(city_id):
    with get_db() as db:
        floors = db.execute('''
            SELECT f.floorplan_path FROM floors f
            JOIN buildings b ON b.id = f.building_id
            WHERE b.city_id = ?
        ''', (city_id,)).fetchall()
        for f in floors:
            _delete_file(f['floorplan_path'])
        db.execute('DELETE FROM cities WHERE id = ?', (city_id,))
    return '', 204


# ── Buildings ─────────────────────────────────────────────────────────────────

@app.route('/api/cities/<int:city_id>/buildings', methods=['POST'])
def create_building(city_id):
    data = request.json or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'name required'}), 400
    lat = data.get('lat')
    lng = data.get('lng')
    lat = float(lat) if lat not in (None, '') else None
    lng = float(lng) if lng not in (None, '') else None
    with get_db() as db:
        cur = db.execute('INSERT INTO buildings (city_id, name, lat, lng) VALUES (?, ?, ?, ?)', (city_id, name, lat, lng))
        row = db.execute('SELECT * FROM buildings WHERE id = ?', (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201

@app.route('/api/buildings/<int:building_id>', methods=['PUT'])
def update_building(building_id):
    data = request.json or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'name required'}), 400
    lat = data.get('lat')
    lng = data.get('lng')
    lat = float(lat) if lat not in (None, '') else None
    lng = float(lng) if lng not in (None, '') else None
    with get_db() as db:
        db.execute('UPDATE buildings SET name=?, lat=?, lng=? WHERE id=?', (name, lat, lng, building_id))
        row = db.execute('SELECT * FROM buildings WHERE id=?', (building_id,)).fetchone()
    return jsonify(dict(row))

@app.route('/api/buildings/<int:building_id>', methods=['DELETE'])
def delete_building(building_id):
    with get_db() as db:
        floors = db.execute(
            'SELECT floorplan_path FROM floors WHERE building_id = ?', (building_id,)
        ).fetchall()
        for f in floors:
            _delete_file(f['floorplan_path'])
        db.execute('DELETE FROM buildings WHERE id = ?', (building_id,))
    return '', 204


# ── Floors ────────────────────────────────────────────────────────────────────

@app.route('/api/floors/<int:floor_id>', methods=['GET'])
def get_floor(floor_id):
    with get_db() as db:
        row = db.execute('''
            SELECT f.id, f.label, f.floorplan_path,
                   b.name AS building_name,
                   ci.name AS city_name,
                   c.name  AS client_name
            FROM floors f
            JOIN buildings b  ON b.id  = f.building_id
            JOIN cities ci    ON ci.id = b.city_id
            JOIN clients c    ON c.id  = ci.client_id
            WHERE f.id = ?
        ''', (floor_id,)).fetchone()
    if not row:
        abort(404)
    return jsonify(dict(row))

@app.route('/api/buildings/<int:building_id>/floors', methods=['POST'])
def create_floor(building_id):
    data = request.json or {}
    level = int(data.get('level', 0))
    label = floor_label(level)
    with get_db() as db:
        existing = db.execute(
            'SELECT id FROM floors WHERE building_id = ? AND level = ?', (building_id, level)
        ).fetchone()
        if existing:
            return jsonify({'error': f'Level {label} already exists in this building'}), 409
        cur = db.execute(
            'INSERT INTO floors (building_id, level, label) VALUES (?, ?, ?)', (building_id, level, label)
        )
        row = db.execute('SELECT * FROM floors WHERE id = ?', (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201

@app.route('/api/floors/<int:floor_id>', methods=['DELETE'])
def delete_floor(floor_id):
    with get_db() as db:
        floor = db.execute('SELECT floorplan_path FROM floors WHERE id = ?', (floor_id,)).fetchone()
        if floor:
            _delete_file(floor['floorplan_path'])
        db.execute('DELETE FROM floors WHERE id = ?', (floor_id,))
    return '', 204


# ── Floor plan upload / serve ─────────────────────────────────────────────────

@app.route('/api/floors/<int:floor_id>/floorplan', methods=['POST'])
def upload_floorplan(floor_id):
    file = request.files.get('file')
    if not file:
        return jsonify({'error': 'no file provided'}), 400
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        return jsonify({'error': f'unsupported file type: {ext}'}), 400
    with get_db() as db:
        floor = db.execute('SELECT * FROM floors WHERE id = ?', (floor_id,)).fetchone()
        if not floor:
            abort(404)
        _delete_file(floor['floorplan_path'])
        filename = f'floor_{floor_id}{ext}'
        file.save(UPLOAD_DIR / filename)
        db.execute('UPDATE floors SET floorplan_path = ? WHERE id = ?', (filename, floor_id))
    return jsonify({'url': f'/api/floors/{floor_id}/floorplan'}), 200

@app.route('/api/floors/<int:floor_id>/floorplan', methods=['GET'])
def get_floorplan(floor_id):
    with get_db() as db:
        floor = db.execute('SELECT floorplan_path FROM floors WHERE id = ?', (floor_id,)).fetchone()
    if not floor or not floor['floorplan_path']:
        abort(404)
    return send_from_directory(UPLOAD_DIR, floor['floorplan_path'])


# ── Devices ───────────────────────────────────────────────────────────────────

@app.route('/api/floors/<int:floor_id>/devices', methods=['GET'])
def list_devices(floor_id):
    with get_db() as db:
        rows = db.execute('SELECT * FROM devices WHERE floor_id = ?', (floor_id,)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/floors/<int:floor_id>/devices', methods=['POST'])
def create_device(floor_id):
    d = request.json or {}
    device_id = str(uuid.uuid4())
    with get_db() as db:
        db.execute('''
            INSERT INTO devices (id, floor_id, type, label, brand, model, serial, notes, avg_mono, avg_colour, x_pct, y_pct)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            device_id, floor_id,
            d.get('type', 'printer'), d.get('label', 'Device'),
            d.get('brand', ''), d.get('model', ''),
            d.get('serial', ''), d.get('notes', ''),
            d.get('avg_mono', 0), d.get('avg_colour', 0),
            d.get('x_pct', 0), d.get('y_pct', 0),
        ))
        row = db.execute('SELECT * FROM devices WHERE id = ?', (device_id,)).fetchone()
    return jsonify(dict(row)), 201

@app.route('/api/devices/<device_id>', methods=['PUT'])
def update_device(device_id):
    d = request.json or {}
    with get_db() as db:
        existing = db.execute('SELECT floor_id FROM devices WHERE id=?', (device_id,)).fetchone()
        if not existing:
            abort(404)
        floor_id = d.get('floor_id') or existing['floor_id']
        db.execute('''
            UPDATE devices
            SET floor_id=?, type=?, label=?, brand=?, model=?, serial=?, notes=?, avg_mono=?, avg_colour=?,
                mono_rate=?, colour_rate=?, rental_amount=?, rental_period=?, x_pct=?, y_pct=?
            WHERE id=?
        ''', (
            floor_id,
            d.get('type'), d.get('label'),
            d.get('brand', ''), d.get('model', ''),
            d.get('serial', ''), d.get('notes', ''),
            d.get('avg_mono', 0), d.get('avg_colour', 0),
            d.get('mono_rate') or None, d.get('colour_rate') or None,
            d.get('rental_amount') or None, d.get('rental_period') or None,
            d.get('x_pct'), d.get('y_pct'),
            device_id,
        ))
        row = db.execute('SELECT * FROM devices WHERE id = ?', (device_id,)).fetchone()
    return jsonify(dict(row))

@app.route('/api/devices/<device_id>', methods=['DELETE'])
def delete_device(device_id):
    with get_db() as db:
        db.execute('DELETE FROM devices WHERE id = ?', (device_id,))
    return '', 204


# ── Tree (full hierarchy + counts) ────────────────────────────────────────────

@app.route('/api/tree')
def get_tree():
    with get_db() as db:
        clients = db.execute('SELECT * FROM clients ORDER BY name').fetchall()
        result  = []
        for c in clients:
            cd = dict(c)
            cities = db.execute(
                'SELECT * FROM cities WHERE client_id = ? ORDER BY name', (c['id'],)
            ).fetchall()
            cd['cities'] = []
            for ci in cities:
                cid = dict(ci)
                buildings = db.execute(
                    'SELECT * FROM buildings WHERE city_id = ? ORDER BY name', (ci['id'],)
                ).fetchall()
                cid['buildings'] = []
                for b in buildings:
                    bd = dict(b)
                    floors = db.execute(
                        'SELECT * FROM floors WHERE building_id = ? ORDER BY level DESC', (b['id'],)
                    ).fetchall()
                    bd['floors'] = []
                    for f in floors:
                        fd = dict(f)
                        fd['level'] = fd.get('level', 0)
                        fd['device_count'] = db.execute(
                            'SELECT COUNT(*) FROM devices WHERE floor_id = ?', (f['id'],)
                        ).fetchone()[0]
                        fd['has_floorplan'] = bool(fd['floorplan_path'])
                        bd['floors'].append(fd)
                    bd['device_count'] = sum(f['device_count'] for f in bd['floors'])
                    cid['buildings'].append(bd)
                cid['device_count'] = sum(b['device_count'] for b in cid['buildings'])
                cd['cities'].append(cid)
            cd['device_count'] = sum(ci['device_count'] for ci in cd['cities'])
            result.append(cd)
    return jsonify(result)


# ── Fleet Import ──────────────────────────────────────────────────────────────

def normalize_name(s):
    return ' '.join(s.strip().split()).lower()

def title_name(s):
    return ' '.join(s.strip().split()).title()

IMPORT_REQUIRED_COLS = {'client', 'city', 'building', 'floor_level', 'floor_label', 'label', 'serial'}
IMPORT_VALID_DEVICE_TYPES = {'printer', 'mfp', 'scanner', 'print_server'}

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

            # device_type is optional; validate only when provided
            dtype = row.get('device_type', '').strip().lower()
            if dtype and dtype not in IMPORT_VALID_DEVICE_TYPES:
                errors.append({'row': i, 'type': 'parse_error',
                               'detail': f"device_type must be one of: {', '.join(sorted(IMPORT_VALID_DEVICE_TYPES))}, got: '{row.get('device_type', '')}'"}); continue

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
                'SELECT id FROM clients WHERE LOWER(name) = LOWER(?)',
                (client_name.strip(),)
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
                'SELECT id FROM clients WHERE LOWER(name) = LOWER(?)',
                (client_name,)
            ).fetchone()
            client_id = client_row['id']

            # Resolve or create city
            city_name = row['city'].strip()
            city_row  = db.execute(
                'SELECT id FROM cities WHERE client_id = ? AND LOWER(name) = LOWER(?)',
                (client_id, city_name)
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
                'SELECT id FROM buildings WHERE city_id = ? AND LOWER(name) = LOWER(?)',
                (city_id, building_name)
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

            # Normalise and resolve/create brand and model
            brand_raw = row.get('brand', '').strip()
            model_raw = row.get('model', '').strip()
            model_str = title_name(model_raw) if model_raw else ''

            # Use canonical DB name for brand so the dropdown matches on re-open
            brand_str = title_name(brand_raw) if brand_raw else ''
            brand_id = None
            if brand_raw:
                b_row = db.execute(
                    'SELECT id, name FROM brands WHERE LOWER(name) = ?',
                    (normalize_name(brand_raw),)
                ).fetchone()
                if not b_row:
                    db.execute('INSERT OR IGNORE INTO brands (name) VALUES (?)', (brand_str,))
                    b_row = db.execute(
                        'SELECT id, name FROM brands WHERE LOWER(name) = ?',
                        (normalize_name(brand_raw),)
                    ).fetchone()
                if b_row:
                    brand_id  = b_row['id']
                    brand_str = b_row['name']  # use canonical casing from DB

            # Resolve or create model; capture its device_type for auto-fill
            model_device_type = None
            if model_raw and brand_id is not None:
                m_row = db.execute(
                    'SELECT id, device_type FROM models WHERE brand_id = ? AND LOWER(name) = ?',
                    (brand_id, normalize_name(model_raw))
                ).fetchone()
                if not m_row:
                    db.execute(
                        'INSERT OR IGNORE INTO models (brand_id, name) VALUES (?, ?)',
                        (brand_id, model_str)
                    )
                else:
                    model_device_type = m_row['device_type']

            # device_type: CSV value wins; fall back to model catalogue; default printer
            csv_dtype = row.get('device_type', '').strip().lower()
            if csv_dtype in IMPORT_VALID_DEVICE_TYPES:
                final_device_type = csv_dtype
            elif model_device_type and model_device_type in IMPORT_VALID_DEVICE_TYPES:
                final_device_type = model_device_type
            else:
                final_device_type = 'printer'

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
                final_device_type,
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


# ── TCO Scenarios ─────────────────────────────────────────────────────────────

def _get_or_create_scenario(db, client_id, scenario):
    row = db.execute(
        'SELECT id FROM tco_scenarios WHERE client_id=? AND scenario=?', (client_id, scenario)
    ).fetchone()
    if row:
        return row['id']
    cur = db.execute(
        'INSERT INTO tco_scenarios (client_id, scenario) VALUES (?,?)', (client_id, scenario)
    )
    return cur.lastrowid

def _scenario_rows(db, scenario_id):
    return [dict(r) for r in db.execute(
        'SELECT * FROM tco_scenario_rows WHERE scenario_id=? ORDER BY sort_order, id',
        (scenario_id,)
    ).fetchall()]

def _safe_f(v):
    try: return float(v) if v not in (None, '') else None
    except: return None

def _safe_i(v):
    try: return int(float(v)) if v not in (None, '') else 0
    except: return 0

@app.route('/api/clients/<int:cid>/tco/current/capture-fleet', methods=['POST'])
def capture_fleet(cid):
    with get_db() as db:
        devices = db.execute('''
            SELECT d.*,
                   b.name  AS building_name,
                   f.label AS floor_label,
                   ci.name AS city_name
            FROM devices d
            JOIN floors    f  ON f.id  = d.floor_id
            JOIN buildings b  ON b.id  = f.building_id
            JOIN cities    ci ON ci.id = b.city_id
            WHERE ci.client_id = ?
            ORDER BY ci.name, b.name, f.level, d.label
        ''', (cid,)).fetchall()
        sc_id = _get_or_create_scenario(db, cid, 'current')
        db.execute('UPDATE tco_scenarios SET updated_at=datetime("now") WHERE id=?', (sc_id,))
        db.execute('DELETE FROM tco_scenario_rows WHERE scenario_id=?', (sc_id,))
        for i, d in enumerate(devices):
            db.execute('''
                INSERT INTO tco_scenario_rows
                    (scenario_id, sort_order, device_id, label, location,
                     brand, model, serial, mono_vol, colour_vol,
                     mono_rate, colour_rate, rental, period)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''', (
                sc_id, i, d['id'],
                d['label'] or '',
                f"{d['building_name']} · {d['floor_label']}",
                d['brand'] or '', d['model'] or '', d['serial'] or '',
                d['avg_mono'] or 0, d['avg_colour'] or 0,
                d['mono_rate'], d['colour_rate'],
                d['rental_amount'], d['rental_period'],
            ))
        return jsonify(_scenario_rows(db, sc_id))

@app.route('/api/clients/<int:cid>/tco/future/copy-current', methods=['POST'])
def copy_current_to_future(cid):
    with get_db() as db:
        sc_curr = db.execute(
            'SELECT id FROM tco_scenarios WHERE client_id=? AND scenario="current"', (cid,)
        ).fetchone()
        if not sc_curr:
            return jsonify({'error': 'No current state to copy from'}), 404
        curr_rows = _scenario_rows(db, sc_curr['id'])
        sc_id = _get_or_create_scenario(db, cid, 'future')
        db.execute('UPDATE tco_scenarios SET updated_at=datetime("now") WHERE id=?', (sc_id,))
        db.execute('DELETE FROM tco_scenario_rows WHERE scenario_id=?', (sc_id,))
        for r in curr_rows:
            db.execute('''
                INSERT INTO tco_scenario_rows
                    (scenario_id, sort_order, device_id, label, location,
                     brand, model, serial, mono_vol, colour_vol,
                     mono_rate, colour_rate, rental, period)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''', (
                sc_id, r['sort_order'], r.get('device_id'),
                r['label'], r['location'], r['brand'], r['model'], r['serial'],
                r['mono_vol'], r['colour_vol'],
                r['mono_rate'], r['colour_rate'], r['rental'], r['period'],
            ))
        return jsonify(_scenario_rows(db, sc_id))

@app.route('/api/clients/<int:cid>/tco/optimise', methods=['GET'])
def optimise_fleet(cid):
    from collections import defaultdict
    with get_db() as db:
        sc = db.execute(
            'SELECT id FROM tco_scenarios WHERE client_id=? AND scenario="current"', (cid,)
        ).fetchone()
        if not sc:
            return jsonify({'error': 'Capture the fleet into Current State first.'}), 404
        curr_rows = _scenario_rows(db, sc['id'])
        if not curr_rows:
            return jsonify({'error': 'Current State is empty — add devices first.'}), 404
        allowed = [dict(m) for m in db.execute('''
            SELECT m.*, b.name AS brand_name
            FROM models m
            JOIN brands b ON b.id = m.brand_id
            WHERE m.optimiser_allowed = 1 AND m.mono_rate IS NOT NULL
        ''').fetchall()]

    if not allowed:
        return jsonify({'error': 'No devices in the optimisation pool. Tick models in Admin → Catalogue.'}), 404

    colour_pool = [m for m in allowed if m['colour_type'] == 'colour' and m['colour_rate'] is not None]
    groups = defaultdict(list)
    for r in curr_rows:
        groups[r['location'] or 'Unspecified'].append(r)

    results = []
    total_curr_clicks = 0.0
    total_opt_clicks  = 0.0

    for location, devices in groups.items():
        n           = len(devices)
        mono_vol    = sum(d['mono_vol']   or 0 for d in devices)
        colour_vol  = sum(d['colour_vol'] or 0 for d in devices)
        curr_clicks = sum((d['mono_vol']   or 0) * (d['mono_rate']   or 0) +
                         (d['colour_vol'] or 0) * (d['colour_rate'] or 0)
                         for d in devices)
        curr_rental = sum(d['rental'] or 0 for d in devices)
        needs_colour = colour_vol > 0
        pool = colour_pool if (needs_colour and colour_pool) else allowed

        best = None
        best_clicks = float('inf')
        for m in pool:
            c = mono_vol * (m['mono_rate'] or 0) + colour_vol * (m['colour_rate'] or 0)
            if c < best_clicks:
                best_clicks = c
                best = m

        results.append({
            'location':      location,
            'device_count':  n,
            'mono_vol':      mono_vol,
            'colour_vol':    colour_vol,
            'curr_clicks':   round(curr_clicks, 2),
            'curr_rental':   round(curr_rental, 2),
            'opt_clicks':    round(best_clicks, 2) if best else None,
            'click_savings': round(curr_clicks - best_clicks, 2) if best else None,
            'needs_colour':  needs_colour,
            'colour_covered': bool(best and best['colour_type'] == 'colour') if needs_colour else True,
            'recommended':   {
                'brand':       best['brand_name'],
                'model':       best['name'],
                'colour_type': best['colour_type'],
                'page_size':   best['page_size'],
                'mono_rate':   best['mono_rate'],
                'colour_rate': best['colour_rate'],
            } if best else None,
        })
        total_curr_clicks += curr_clicks
        total_opt_clicks  += (best_clicks if best else curr_clicks)

    return jsonify({
        'summary': {
            'locations':     len(results),
            'curr_clicks':   round(total_curr_clicks, 2),
            'opt_clicks':    round(total_opt_clicks, 2),
            'click_savings': round(total_curr_clicks - total_opt_clicks, 2),
            'savings_pct':   round((total_curr_clicks - total_opt_clicks) / total_curr_clicks * 100, 1)
                             if total_curr_clicks else 0,
        },
        'locations': results,
    })

@app.route('/api/clients/<int:cid>/tco/<scenario>', methods=['GET'])
def get_tco_scenario(cid, scenario):
    if scenario not in ('current', 'future'):
        abort(404)
    with get_db() as db:
        sc = db.execute(
            'SELECT id FROM tco_scenarios WHERE client_id=? AND scenario=?', (cid, scenario)
        ).fetchone()
        if not sc:
            return jsonify([])
        return jsonify(_scenario_rows(db, sc['id']))

@app.route('/api/clients/<int:cid>/tco/<scenario>', methods=['PUT'])
def save_tco_scenario(cid, scenario):
    if scenario not in ('current', 'future'):
        abort(404)
    rows_data = request.json
    if not isinstance(rows_data, list):
        return jsonify({'error': 'expected array'}), 400
    with get_db() as db:
        sc_id = _get_or_create_scenario(db, cid, scenario)
        db.execute('UPDATE tco_scenarios SET updated_at=datetime("now") WHERE id=?', (sc_id,))
        db.execute('DELETE FROM tco_scenario_rows WHERE scenario_id=?', (sc_id,))
        for i, row in enumerate(rows_data):
            db.execute('''
                INSERT INTO tco_scenario_rows
                    (scenario_id, sort_order, device_id, label, location,
                     brand, model, serial, mono_vol, colour_vol,
                     mono_rate, colour_rate, rental, period)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''', (
                sc_id, i,
                row.get('device_id') or None,
                row.get('label') or '',
                row.get('location') or '',
                row.get('brand') or '',
                row.get('model') or '',
                row.get('serial') or '',
                _safe_i(row.get('mono_vol')),
                _safe_i(row.get('colour_vol')),
                _safe_f(row.get('mono_rate')),
                _safe_f(row.get('colour_rate')),
                _safe_f(row.get('rental')),
                row.get('period') or None,
            ))
    return jsonify({'status': 'ok'})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _delete_file(path):
    if path:
        try:
            (UPLOAD_DIR / path).unlink(missing_ok=True)
        except Exception:
            pass

def _cleanup_client_files(db, client_id):
    floors = db.execute('''
        SELECT f.floorplan_path FROM floors f
        JOIN buildings b ON b.id = f.building_id
        JOIN cities ci ON ci.id = b.city_id
        WHERE ci.client_id = ?
    ''', (client_id,)).fetchall()
    for f in floors:
        _delete_file(f['floorplan_path'])


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    print('Printer Planner running at http://localhost:5050')
    app.run(host='0.0.0.0', port=5050, debug=True)
