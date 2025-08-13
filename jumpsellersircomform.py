# jumpsellersircomform.py
import os
import uuid
import logging
import tempfile
import mimetypes

from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from werkzeug.utils import secure_filename

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

# ---------------- Configuración ----------------
FOLDER_ID = os.environ.get('GOOGLE_DRIVE_FOLDER_ID', '1dcCSfcEbGvzLld_-jg6WTmjiEKBU7bRt')
SCOPES = ['https://www.googleapis.com/auth/drive.file']
ALLOWED_EXTENSIONS = {'pdf', 'jpeg', 'jpg', 'png', 'doc', 'docx'}

# Rutas configurables por entorno (montadas como volúmenes)
GOOGLE_TOKEN_FILE = os.environ.get('GOOGLE_TOKEN_FILE', 'token.json')
GOOGLE_CREDENTIALS_FILE = os.environ.get('GOOGLE_CREDENTIALS_FILE', 'credentials.json')

# Directorio temporal (por defecto /tmp en contenedores Linux)
UPLOAD_TMP_DIR = os.environ.get('UPLOAD_TMP_DIR', tempfile.gettempdir())

# Logging básico
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')
log = logging.getLogger("sircom-uploader")

app = Flask(__name__)
# Límite de subida 2GB
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 * 1024

# CORS (dominios permitidos)
ALLOWED_ORIGINS = [
    'https://sircom.cl',
    'https://www.sircom.cl',
    'https://sircom.jumpseller.com',
    'https://www.sircom.jumpseller.com',
]
CORS(app, supports_credentials=True, origins=ALLOWED_ORIGINS)

# --------------- Middleware CORS extra ---------------
@app.after_request
def apply_cors(response):
    origin = request.headers.get('Origin')
    if origin in ALLOWED_ORIGINS:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With, Accept'
    return response

# --------------- Utilidades ---------------
def allowed_file(filename: str) -> bool:
    return ('.' in filename) and (filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS)

def get_drive_service():
    """
    Crea el servicio de Google Drive sin intentar abrir navegador dentro del contenedor.
    Requiere que token.json exista y tenga refresh_token válido.
    """
    # Validaciones de archivos de credenciales
    if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
        raise FileNotFoundError(f"Falta credentials.json en {GOOGLE_CREDENTIALS_FILE}")

    if not os.path.exists(GOOGLE_TOKEN_FILE):
        raise FileNotFoundError(
            f"Falta token.json en {GOOGLE_TOKEN_FILE}. "
            f"Genéralo FUERA del contenedor con access_type=offline y móntalo."
        )

    # Carga el token
    creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_FILE, SCOPES)

    # Renueva si es necesario (requiere refresh_token)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            log.info("Token expirado: intentando refresh...")
            creds.refresh(Request())
            with open(GOOGLE_TOKEN_FILE, 'w') as token_fp:
                token_fp.write(creds.to_json())
            log.info("Token refrescado y guardado.")
        else:
            # No intentamos InstalledAppFlow en contenedor
            raise RuntimeError(
                "token.json inválido o sin refresh_token. "
                "Regenera FUERA del contenedor usando InstalledAppFlow con access_type=offline."
            )

    # Construye cliente de Drive
    return build('drive', 'v3', credentials=creds)

# --------------- Rutas ---------------
@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'}), 200

@app.route('/upload', methods=['POST', 'OPTIONS'])
def upload_file_to_drive():
    # Preflight
    if request.method == 'OPTIONS':
        return make_response('', 204)

    # Obtiene archivo (acepta claves alternativas por si el front usa otros nombres)
    file = (
        request.files.get('file') or
        request.files.get('archivo') or
        request.files.get('files[]')
    )

    if not file:
        return jsonify({'error': 'No se envió ningún archivo'}), 400

    if not file.filename:
        return jsonify({'error': 'Nombre de archivo vacío'}), 400

    filename = secure_filename(file.filename)
    if not allowed_file(filename):
        return jsonify({'error': 'Extensión de archivo no permitida'}), 400

    # Dónde guardar temporalmente
    os.makedirs(UPLOAD_TMP_DIR, exist_ok=True)
    temp_path = os.path.join(UPLOAD_TMP_DIR, f"{uuid.uuid4()}_{filename}")

    try:
        # Guarda temporal
        file.save(temp_path)

        # Mimetype (mejor para Drive)
        mimetype = mimetypes.guess_type(filename)[0] or 'application/octet-stream'

        # Servicio de Drive
        service = get_drive_service()

        # Metadata + subida
        file_metadata = {'name': filename, 'parents': [FOLDER_ID]}
        media = MediaFileUpload(temp_path, mimetype=mimetype, resumable=True)

        uploaded_file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()

        return jsonify({
            'message': 'Archivo subido exitosamente',
            'file_id': uploaded_file.get('id'),
            'drive_url': uploaded_file.get('webViewLink')
        }), 200

    except HttpError as error:
        log.exception("Error de Google Drive durante la subida")
        return jsonify({'error': f'Error de Google Drive: {str(error)}'}), 502

    except FileNotFoundError as e:
        # Falta credentials.json o token.json
        log.error(str(e))
        return jsonify({'error': f'{type(e).__name__}: {str(e)}'}), 500

    except RuntimeError as e:
        # Token sin refresh_token o inválido para refrescar
        log.error(str(e))
        return jsonify({'error': f'{type(e).__name__}: {str(e)}'}), 500

    except Exception as e:
        # Cualquier otro fallo
        log.exception("Error interno en /upload")
        return jsonify({'error': f'Fallo interno: {type(e).__name__}: {str(e)}'}), 500

    finally:
        # Limpieza del archivo temporal
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            log.warning("No se pudo eliminar el archivo temporal: %s", temp_path)

# --------------- Main (solo dev local) ---------------
if __name__ == '__main__':
    # En producción se lanza con Gunicorn (ver Dockerfile)
    app.run(host='0.0.0.0', port=5000, debug=False)
