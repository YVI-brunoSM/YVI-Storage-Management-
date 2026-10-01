def test_privacy_is_public_without_session(app):
    client = app.test_client()
    response = client.get('/politica-de-privacidade')
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    for disclosure in ('Política de privacidade', 'gmail.send', 'openid e email', '90 dias', 'yvibrunosilva@gmail.com', 'Uso Limitado'):
        assert disclosure in text
    assert 'Set-Cookie' not in response.headers
    assert client.get('/api/notifications').status_code == 401


def test_notifications_missing_table_is_actionable(client, db):
    db.execute('ALTER TABLE email_settings RENAME TO email_settings_test_hidden')
    try:
        response = client.get('/api/notifications')
        assert response.status_code == 503
        assert response.json['error']['code'] == 'SCHEMA_NOT_READY'
        assert 'python migrate.py' in response.json['error']['message']
        assert response.json['error']['request_id']
    finally:
        db.execute('ALTER TABLE email_settings_test_hidden RENAME TO email_settings')
    assert client.get('/api/notifications').status_code == 200


def test_notifications_missing_column_is_actionable(client, db):
    db.execute('ALTER TABLE email_settings RENAME COLUMN worker_seen_at TO worker_seen_test_hidden')
    try:
        response = client.get('/api/notifications')
        assert response.status_code == 503
        assert response.json['error']['code'] == 'SCHEMA_NOT_READY'
    finally:
        db.execute('ALTER TABLE email_settings RENAME COLUMN worker_seen_test_hidden TO worker_seen_at')


def test_notifications_missing_singleton_does_not_crash_or_enable_sends(client, db):
    db.execute('DELETE FROM email_settings')
    response = client.get('/api/notifications')
    assert response.status_code == 503
    assert response.json['error']['code'] == 'EMAIL_SETTINGS_MISSING'
    assert db.execute('SELECT count(*) AS total FROM email_messages').fetchone()['total'] == 0
