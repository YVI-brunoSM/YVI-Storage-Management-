import base64
import io
from PIL import Image
from conftest import authenticated, headers


def photo():
    out = io.BytesIO()
    Image.new('RGB', (400, 200), 'navy').save(out, format='PNG')
    return base64.b64encode(out.getvalue()).decode()


def test_avatar_owner_validation_and_persistence(app, db):
    operator = authenticated(app, 2)
    admin = authenticated(app, 1)
    assert operator.put('/api/me/avatar', json={'image': photo()}).status_code == 403
    assert operator.put('/api/me/avatar', json={'image': 'not-an-image'}, headers=headers()).status_code == 422
    assert operator.put('/api/me/avatar', json={'image': photo()}, headers=headers()).status_code == 200
    me = operator.get('/api/me').json['user']
    assert me['has_avatar'] and me['avatar_revision'] == 1 and 'avatar' not in me
    response = operator.get('/api/users/2/avatar')
    assert response.status_code == 200 and response.mimetype == 'image/jpeg'
    image = Image.open(io.BytesIO(response.data))
    assert image.size == (256, 256) and not image.getexif()
    assert db.execute('SELECT octet_length(avatar) AS n FROM users WHERE id=2').fetchone()['n'] > 0
    assert admin.get('/api/users/2/avatar').status_code == 200
    assert operator.get('/api/users/1/avatar').status_code == 403
    assert app.test_client().get('/api/users/2/avatar').status_code == 401
    assert operator.delete('/api/me/avatar', headers=headers()).status_code == 200
    assert operator.get('/api/users/2/avatar').status_code == 404
    assert not operator.get('/api/me').json['user']['has_avatar']


def test_photo_limits_and_unsafe_content(client):
    for value in [base64.b64encode(b'<svg onload="alert(1)"/>').decode(), 'a'*2_800_001]:
        assert client.put('/api/me/avatar', json={'image': value}, headers=headers()).status_code == 422
    assert client.put('/api/me/avatar', json={'image': 'a'*2_900_000}, headers=headers()).status_code == 413


def test_category_icons_are_persisted_and_allowlisted(client):
    for icon in ['folder','dumbbell','zap','file-text','droplet','sparkles','box','wrench','gear','cable','shield','truck']:
        response = client.post('/api/categories', json={'name':'Categoria '+icon,'icon':icon}, headers=headers())
        assert response.status_code in (200,201)
    assert {row['icon'] for row in client.get('/api/categories').json} >= {'box','wrench','gear','cable','shield','truck'}
    assert client.post('/api/categories', json={'name':'Inválida','icon':'<script>'}, headers=headers()).status_code == 422
