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
