import os
import uuid
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from werkzeug.utils import secure_filename
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

# --- CONFIGURACIÓN ---
FOLDER_ID = '1dcCSfcEbGvzLld_-jg6WTmjiEKBU7bRt'
SCOPES = ['https://www.googleapis.com/auth/drive.file']
ALLOWED_EXTENSIONS = {'pdf', 'jpeg', 'jpg', 'png', 'doc', 'docx'}

app = Flask(__name__)

# Limite de subida 2GB
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 * 1024

# CORS solo desde dominios permitidos
CORS(app, supports_credentials=True, origins=[
    'https://sircom.cl',
    'https://www.sircom.cl',
    'https://sircom.jumpseller.com',
    'https://www.sircom.jumpseller.com'
])

# --- Middleware CORS manual (por si CORS de Flask no lo aplica bien) ---
@app.after_request
def apply_cors(response):
    origin = request.headers.get('Origin')
    allowed_origins = [
        'https://sircom.cl',
        'https://www.sircom.cl',
        'https://sircom.jumpseller.com',
        'https://www.sircom.jumpseller.com'
    ]
    if origin in allowed_origins:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    return response

# --- Funciones auxiliares ---
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_drive_service():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('drive', 'v3', credentials=creds)

# --- RUTA /upload ---
@app.route('/upload', methods=['POST', 'OPTIONS'])
def upload_file_to_drive():
    if request.method == 'OPTIONS':
        # Preflight
        return make_response('', 204)

    if 'file' not in request.files:
        return jsonify({'error': 'No se envió ningún archivo'}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({'error': 'Nombre de archivo vacío'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': 'Extensión de archivo no permitida'}), 400

    filename = secure_filename(file.filename)
    temp_filename = f"{uuid.uuid4()}_{filename}"
    file.save(temp_filename)

    try:
        service = get_drive_service()
        file_metadata = {
            'name': filename,
            'parents': [FOLDER_ID]
        }
        media = MediaFileUpload(temp_filename, resumable=True)
        uploaded_file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()

        os.remove(temp_filename)

        return jsonify({
            'message': 'Archivo subido exitosamente',
            'file_id': uploaded_file.get('id'),
            'drive_url': uploaded_file.get('webViewLink')
        })

    except HttpError as error:
        if os.path.exists(temp_filename):
            os.remove(temp_filename)
        return jsonify({'error': f'Error al subir a Google Drive: {str(error)}'}), 500

# --- MAIN (modo desarrollo) ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
