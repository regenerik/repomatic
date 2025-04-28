
from flask import Blueprint, request, jsonify, current_app
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import io, os, base64, textwrap
from mailjet_rest import Client
from dotenv import load_dotenv

load_dotenv()

form_gestores_bp = Blueprint('form_gestores_bp', __name__)

# Clave API para proteger la ruta
API_KEY = os.getenv('API_KEY')

def check_api_key(api_key):
    return api_key == API_KEY

@form_gestores_bp.before_request
def authorize():
    if request.method == 'OPTIONS':
        return
    if request.path == '/test_form_gestores_bp':
        return
    api_key = request.headers.get('Authorization')
    if not api_key or not check_api_key(api_key):
        return jsonify({'message': 'Unauthorized'}), 401

@form_gestores_bp.route('/test_form_gestores_bp', methods=['GET'])
def test():
    return jsonify({'message': 'Test OK'}), 200

@form_gestores_bp.route('/form_gestores', methods=['POST'])
def form_gestores():
    data = request.get_json()
    # Configurar paths de imágenes
    base_dir = os.path.dirname(__file__)
    bg_path = os.path.join(base_dir, 'background.png')  # Fondo completo
    logo_path = os.path.join(base_dir, 'logo.png')      # Logo esquinero

    # Generar PDF
    buffer = io.BytesIO()
    width, height = letter
    p = canvas.Canvas(buffer, pagesize=letter)

    # Dibujar fondo
    if os.path.exists(bg_path):
        p.drawImage(bg_path, 0, 0, width=width, height=height)

    # Dibujar logo arriba derecha
    if os.path.exists(logo_path):
        logo_w, logo_h = 80, 40
        p.drawImage(logo_path, width - logo_w - 50, height - logo_h - 30, width=logo_w, height=logo_h, mask='auto')

    # Título centrado
    p.setFont("Helvetica-Bold", 18)
    p.drawCentredString(width/2, height - 80, "Informe de Curso Realizado")
    y = height - 120
    p.setFont("Helvetica", 12)

    # Datos principales
    for linea in [
        f"APIES: {data.get('apies')}",
        f"Curso: {data.get('curso')}",
        f"Fecha: {data.get('fecha')}",
        f"Gestor: {data.get('gestor')}",
        f"Duración (horas): {data.get('duracionHoras')}",
        f"Ausentes: {data.get('ausentes')}, Presentes: {data.get('presentes')}"
    ]:
        p.drawString(50, y, linea)
        y -= 20
        if y < 100:
            p.showPage()
            if os.path.exists(bg_path):
                p.drawImage(bg_path, 0, 0, width=width, height=height)
            y = height - 50

    # Salto antes de secciones
    y -= 20

    def wrap_section(title, text):
        nonlocal y, p, width, height
        p.setFont("Helvetica-Bold", 12)
        p.drawString(50, y, title)
        y -= 18
        p.setFont("Helvetica", 12)
        for párrafo in text.split('\n'):
            for line in textwrap.wrap(párrafo, 80):
                p.drawString(60, y, line)
                y -= 15
                if y < 100:
                    p.showPage()
                    if os.path.exists(bg_path):
                        p.drawImage(bg_path, 0, 0, width=width, height=height)
                    y = height - 50
        y -= 20

    wrap_section("Objetivo del Curso:", data.get('objetivo', ''))
    wrap_section("Contenido Desarrollado:", data.get('contenidoDesarrollado', ''))
    wrap_section("Resultados y Logros:", data.get('resultadosLogros', ''))

    # Observaciones
    obs_lines = [f"{k}: {v}" for k, v in {
        'Compromiso': data.get('compromiso'),
        'Participación': data.get('participacionActividades'),
        'Concentración': data.get('concentracion'),
        'Cansancio': data.get('cansancio'),
        'Interés': data.get('interesTemas')
    }.items()]
    wrap_section("Observaciones:", "\n".join(obs_lines))

    # Recomendaciones generales
    p.setFont("Helvetica-Bold", 12)
    p.drawString(50, y, "Recomendación para continuar con los siguientes cursos:")
    y -= 18
    p.setFont("Helvetica", 12)
    for curso, items in data.get('recomendaciones', {}).items():
        p.setFont("Helvetica-Bold", 12)
        p.drawString(60, y, curso)
        y -= 16
        p.setFont("Helvetica", 12)
        for item in items:
            p.drawString(70, y, f"- {item}")
            y -= 15
            if y < 100:
                p.showPage()
                if os.path.exists(bg_path): p.drawImage(bg_path, 0, 0, width=width, height=height)
                y = height - 50
        y -= 10

    # Firma con espacio extra
    y -= 20
    if data.get('nombreFirma'):
        p.setFont("Helvetica-Bold", 12)
        p.drawString(50, y, "Firma:")
        y -= 18
        p.setFont("Helvetica-Oblique", 12)
        p.drawString(60, y, data.get('nombreFirma'))
        y -= 60

    p.showPage()
    p.save()
    buffer.seek(0)
    pdf_bytes = buffer.getvalue()

    # Enviar email vía Mailjet
    mj_api_key = os.getenv('MJ_APIKEY_PUBLIC')
    mj_secret_key = os.getenv('MJ_APIKEY_PRIVATE')
    sender_email = os.getenv('MJ_SENDER_EMAIL')
    recipient = data.get('emailGestor')

    encoded_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
    attachments = [{
        'ContentType': 'application/pdf',
        'Filename': 'informe_curso.pdf',
        'Base64Content': encoded_pdf
    }]
    mailjet = Client(auth=(mj_api_key, mj_secret_key), version='v3.1')
    mail_data = {'Messages': [{
        'From': {'Email': sender_email, 'Name': 'YPF Form Gestores'},
        'To': [{'Email': recipient}],
        'Subject': 'Informe de Curso Realizado',
        'TextPart': 'Adjunto encontrarás el Informe de Curso realizado.',
        'Attachments': attachments
    }]}
    try:
        result = mailjet.send.create(data=mail_data)
        if result.status_code in (200, 201):
            return jsonify({'success': True}), 200
        return jsonify({'success': False, 'error': result.text}), result.status_code
    except Exception as e:
        print('Error enviando email vía Mailjet:', e)
        return jsonify({'success': False, 'error': str(e)}), 500
