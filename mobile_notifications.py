"""Optional FCM delivery; payloads contain no grades, names, questions or session tokens."""
import os
from contextlib import closing
import requests
from platform_api import db


def notify_result(user_id: int):
    project = os.getenv('FCM_PROJECT_ID')
    if not project:
        return
    import google.auth
    from google.auth.transport.requests import Request
    try:
        credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/firebase.messaging'])
        credentials.refresh(Request())
        with closing(db()) as conn:
            devices = conn.execute('SELECT id,token FROM mobile_devices WHERE user_id=? AND enabled=1 LIMIT 20', (user_id,)).fetchall()
        for device in devices:
            response = requests.post(
                f'https://fcm.googleapis.com/v1/projects/{project}/messages:send',
                headers={'Authorization': f'Bearer {credentials.token}'},
                json={'message': {'token': device['token'], 'notification': {'title': 'MeritIQra', 'body': 'Your MeritIQra result is now available.'}, 'data': {'action': 'results'}, 'android': {'ttl': '3600s', 'collapse_key': 'result-ready'}}}, timeout=10,
            )
            if response.status_code == 404:
                with closing(db()) as conn:
                    conn.execute('DELETE FROM mobile_devices WHERE id=? AND user_id=?', (device['id'], user_id)); conn.commit()
    except Exception:
        # Notification availability must never change a submitted assessment.
        # No tokens or response bodies are written to application logs.
        return
