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
        ''')
        # Migrate existing databases
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
    name = (request.json or {}).get('name', '').strip()
    if not name:
        return jsonify({'error': 'name required'}), 400
    with get_db() as db:
        cur = db.execute('INSERT INTO models (brand_id, name) VALUES (?, ?)', (brand_id, name))
        row = db.execute('SELECT * FROM models WHERE id = ?', (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201

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
        db.execute('''
            UPDATE devices
            SET type=?, label=?, brand=?, model=?, serial=?, notes=?, avg_mono=?, avg_colour=?,
                mono_rate=?, colour_rate=?, rental_amount=?, rental_period=?, x_pct=?, y_pct=?
            WHERE id=?
        ''', (
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
    if not row:
        abort(404)
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
