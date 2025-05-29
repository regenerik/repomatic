
from flask import Blueprint, request, jsonify, current_app, send_file
from reportlab.pdfgen import canvas
from logging_config import logger
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
import io, os, base64, textwrap
from mailjet_rest import Client
from dotenv import load_dotenv
from models import FormularioGestor
from datetime import datetime
from database import db
import pandas as pd
from io import BytesIO


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

    # ————— Procesar fecha —————
    try:
        fecha_usr = datetime.strptime(data.get('fecha',''), '%Y-%m-%d').date()
    except ValueError:
        fecha_usr = None

    # ————— Recomendaciones —————
    raw_recs = data.get('recomendaciones', {}) or {}
    texto_recs = ""
    for curso_rec, items in raw_recs.items():
        texto_recs += f"{curso_rec}:\n"
        for it in items:
            texto_recs += f"• {it}\n"
        texto_recs += "\n"
    nombres_recs = ', '.join(raw_recs.keys())

    # ————— Crear instancia con cols nuevas —————
    nuevo = FormularioGestor(
        apies                      = data.get('apies'),
        curso                      = data.get('curso'),
        fecha_usuario              = fecha_usr,
        gestor                     = data.get('gestor'),
        duracion_horas             = int(data.get('duracionHoras') or 0),
        objetivo                   = data.get('objetivo'),
        contenido_desarrollado     = data.get('contenidoDesarrollado'),
        ausentes                   = int(data.get('ausentes') or 0),
        presentes                  = int(data.get('presentes') or 0),
        resultados_logros          = data.get('resultadosLogros'),
        compromiso                 = data.get('compromiso'),
        participacion_actividades  = data.get('participacionActividades'),
        concentracion              = data.get('concentracion'),
        cansancio                  = data.get('cansancio'),
        interes_temas              = data.get('interesTemas'),
        recomendaciones            = nombres_recs,
        otros_aspectos             = data.get('otrosAspectos'),
        # NUEVOS CAMPOS:
        jornada                    = data.get('jornada'),
        dotacion_real_estacion     = int(data.get('dotacion_real_estacion') or 0),
        dotacion_en_campus         = int(data.get('dotacion_en_campus') or 0),
        firma_file                 = base64.b64decode(data.get('firmaFile')) if data.get('firmaFile') else None,
        nombre_firma               = data.get('nombreFirma'),
        email_gestor               = data.get('emailGestor'),
        creado_en                  = datetime.utcnow()
    )
    db.session.add(nuevo)
    db.session.commit()
    # —————————————————————————————————

    # Paths de imágenes
    base_dir  = os.path.dirname(__file__)
    bg_path   = os.path.join(base_dir, 'background.png')
    logo_path = os.path.join(base_dir, 'logo.png')

    # Generar PDF
    buffer = io.BytesIO()
    width, height = letter
    p = canvas.Canvas(buffer, pagesize=letter)

    # Fondo y logo
    if os.path.exists(bg_path):
        p.drawImage(bg_path, 0, 0, width=width, height=height)
    if os.path.exists(logo_path):
        p.drawImage(logo_path, width-130, height-70, width=80, height=40, mask='auto')

    # Título
    p.setFont("Helvetica-Bold", 18)
    p.drawCentredString(width/2, height-80, "Informe de Curso Realizado")
    y = height - 120
    p.setFont("Helvetica", 12)

    # Líneas principales
    for linea in [
        f"APIES: {nuevo.apies}",
        f"Curso: {nuevo.curso}",
        f"Fecha (usuario): {nuevo.fecha_usuario or ''}",
        f"Gestor: {nuevo.gestor}",
        f"Duración (horas): {nuevo.duracion_horas}",
        f"Ausentes: {nuevo.ausentes}, Presentes: {nuevo.presentes}",
        f"Jornada: {nuevo.jornada}",
        f"Dotación real estación: {nuevo.dotacion_real_estacion}",
        f"Dotación de Campus: {nuevo.dotacion_en_campus}",
    ]:
        p.drawString(50, y, linea)
        y -= 20
        if y < 100:
            p.showPage()
            if os.path.exists(bg_path):
                p.drawImage(bg_path, 0, 0, width=width, height=height)
            y = height - 50

    y -= 20
    def wrap_section(title, text):
        nonlocal y, p
        p.setFont("Helvetica-Bold", 12)
        p.drawString(50, y, title)
        y -= 18
        p.setFont("Helvetica", 12)
        for párrafo in (text or "").split('\n'):
            for line in textwrap.wrap(párrafo, 80):
                p.drawString(60, y, line)
                y -= 15
                if y < 100:
                    p.showPage()
                    if os.path.exists(bg_path):
                        p.drawImage(bg_path, 0, 0, width=width, height=height)
                    y = height - 50
        y -= 20

    wrap_section("Objetivo del Curso:",          nuevo.objetivo)
    wrap_section("Contenido Desarrollado:",      nuevo.contenido_desarrollado)
    wrap_section("Resultados y Logros:",         nuevo.resultados_logros)

    # Observaciones
    obs = {
        'Compromiso':    nuevo.compromiso,
        'Participación': nuevo.participacion_actividades,
        'Concentración': nuevo.concentracion,
        'Cansancio':     nuevo.cansancio,
        'Interés':       nuevo.interes_temas
    }
    wrap_section("Observaciones:", "\n".join(f"{k}: {v}" for k, v in obs.items()))
    wrap_section("Otros aspectos a destacar:", nuevo.otros_aspectos)
    wrap_section("Recomendaciones:", texto_recs)

    # Firma
    y -= 20
    if nuevo.firma_file:
        try:
            img = ImageReader(io.BytesIO(nuevo.firma_file))
            p.setFont("Helvetica-Bold", 12)
            p.drawString(50, y, "Firma:")
            y -= 18
            p.drawImage(img, 60, y-40+10, width=120, height=40, mask='auto')
            y -= 60
        except:
            pass
    elif nuevo.nombre_firma:
        p.setFont("Helvetica-Bold", 12)
        p.drawString(50, y, "Firma:")
        y -= 18
        p.setFont("Helvetica-Oblique", 12)
        p.drawString(60, y, nuevo.nombre_firma)
        y -= 60

    p.showPage()
    p.save()
    buffer.seek(0)
    pdf_bytes = buffer.getvalue()

    # Adjuntos
    encoded_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
    attachments = [{
        'ContentType':   'application/pdf',
        'Filename':      'informe_curso.pdf',
        'Base64Content': encoded_pdf
    }]

    # Asunto y cuerpo dinámicos
    subject = (
        f"Informe curso de Gestor: {nuevo.gestor} — "
        f"APIES: {nuevo.apies}, Curso: {nuevo.curso}"
    )
    text = (
        f"Informe del curso realizado por {nuevo.gestor}.\n\n"
        f"APIES: {nuevo.apies}\n"
        f"Curso: {nuevo.curso}\n\n"
        "Adjunto encontrarás el informe completo."
    )

    # Enviar email
    mailjet = Client(auth=(os.getenv('MJ_APIKEY_PUBLIC'),
                           os.getenv('MJ_APIKEY_PRIVATE')),
                     version='v3.1')
    mail_data = {
        'Messages': [{
            'From':    {'Email': os.getenv('MJ_SENDER_EMAIL'), 'Name': 'YPF Form Gestores'},
            'To':      [{'Email': nuevo.email_gestor}],
            'Subject': subject,
            'TextPart': text,
            'Attachments': attachments
        }]
    }
    fixed_mail_data = {
       'Messages': [{
            'From':    {'Email': os.getenv('MJ_SENDER_EMAIL'), 'Name': 'YPF Form Gestores'},
            'To':      [{'Email': 'nahuel.paz@ypf.com'}], # CAMBIAR A nahuel.paz@ypf.com despues de las pruebas
            'Subject': subject,
            'TextPart': text,
            'Attachments': attachments
       }]
    }
    try:
        res1 = mailjet.send.create(data=mail_data)
        logger.info('Mailjet al gestor %s → %s', nuevo.email_gestor, res1.status_code)
        res2 = mailjet.send.create(data=fixed_mail_data)
        logger.info('Mailjet fixed → %s', res2.status_code)
        return jsonify({'success': True}), 200
    except Exception as e:
        logger.error('Error enviando Mailjet: %s', e)
        return jsonify({'success': False, 'error': str(e)}), 500

@form_gestores_bp.route('/form_gestores/download_excel', methods=['GET'])
def download_formularios_excel():
    # 1) Traer todos los registros
    registros = FormularioGestor.query.all()
    # 2) Serializar
    data = [r.serialize() for r in registros]
    # 3) Meter en DataFrame
    df = pd.DataFrame(data)

    # 4) Volcar a un buffer Excel
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Formularios')

    output.seek(0)

    # 5) Nombre dinámico con fecha actual
    hoy = datetime.now()
    nombre = f"Formularios_Gestores_hasta_{hoy.day:02d}_{hoy.month:02d}_{hoy.year}.xlsx"

    # 6) Devolver como attachment
    return send_file(
        output,
        as_attachment=True,
        download_name=nombre,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@form_gestores_bp.route('/get_forms', methods=['GET'])
def get_forms():
    forms = (FormularioGestor
             .query
             .order_by(FormularioGestor.creado_en.desc())
             .all())
    return jsonify([f.serialize() for f in forms]), 200

@form_gestores_bp.route('/get_form_pdf/<int:form_id>', methods=['GET'])
def get_form_pdf(form_id):
    # Busca el formulario o 404
    form = FormularioGestor.query.get_or_404(form_id)

    # Reconstruir recomendaciones con contenidos, igual que la ruta POST
    recomendaciones_mapping = {
        'WOW Tienda': [
            'Ciclo de servicios Tienda',
            'Programa cultura Experiencia del cliente v2.0',
            'Elaboración de café'
        ],
        'WOW Playa': [
            'Ciclo de servicio: combustibles líquidos (líquido y GNC)',
            'Programa cultura Experiencia del cliente v2.0',
            'Nuestros productos combustibles / lubricantes'
        ],
        'PEC 1.0': [
            'Programa cultura Experiencia del cliente v2.0',
            'e-Class La voz que escuchamos'
        ],
        'PEC 2.0': [
            'Programa cultura Experiencia del cliente v2.0',
            'e-Class La voz que escuchamos'
        ]
    }
    raw_recs_keys = form.recomendaciones.split(', ') if form.recomendaciones else []
    texto_recs = ""
    for curso_rec in raw_recs_keys:
        texto_recs += f"{curso_rec}:\n"
        for it in recomendaciones_mapping.get(curso_rec, []):
            texto_recs += f"• {it}\n"
        texto_recs += "\n"

    # Buffer en memoria
    buffer = io.BytesIO()
    width, height = letter
    p = canvas.Canvas(buffer, pagesize=letter)

    # Fondo y logo
    base_dir  = os.path.dirname(__file__)
    bg_path   = os.path.join(base_dir, 'background.png')
    logo_path = os.path.join(base_dir, 'logo.png')
    if os.path.exists(bg_path):
        p.drawImage(bg_path, 0, 0, width=width, height=height)
    if os.path.exists(logo_path):
        p.drawImage(logo_path, width-130, height-70, width=80, height=40, mask='auto')

    # Título
    p.setFont("Helvetica-Bold", 18)
    p.drawCentredString(width/2, height-80, "Informe de Curso Realizado")
    y = height - 120
    p.setFont("Helvetica", 12)

    # Líneas principales extendidas
    for linea in [
        f"APIES: {form.apies}",
        f"Curso: {form.curso}",
        f"Fecha (usuario): {form.fecha_usuario.isoformat() if form.fecha_usuario else ''}",
        f"Gestor: {form.gestor}",
        f"Duración (horas): {form.duracion_horas}",
        f"Ausentes: {form.ausentes}, Presentes: {form.presentes}",
        f"Jornada: {form.jornada}",
        f"Dotación real estación: {form.dotacion_real_estacion}",
        f"Dotación en Campus: {form.dotacion_en_campus}"
    ]:
        p.drawString(50, y, linea)
        y -= 20
        if y < 100:
            p.showPage()
            if os.path.exists(bg_path):
                p.drawImage(bg_path, 0, 0, width=width, height=height)
            y = height - 50

    y -= 20

    # Función para texto largo
    def wrap_section(title, text):
        nonlocal y, p
        p.setFont("Helvetica-Bold", 12)
        p.drawString(50, y, title)
        y -= 18
        p.setFont("Helvetica", 12)
        for párrafo in (text or "").split('\n'):
            for line in textwrap.wrap(párrafo, 80):
                p.drawString(60, y, line)
                y -= 15
                if y < 100:
                    p.showPage()
                    if os.path.exists(bg_path):
                        p.drawImage(bg_path, 0, 0, width=width, height=height)
                    y = height - 50
        y -= 20

    # Secciones estándar
    wrap_section("Objetivo del Curso:",         form.objetivo)
    wrap_section("Contenido Desarrollado:",     form.contenido_desarrollado)
    wrap_section("Resultados y Logros:",        form.resultados_logros)

    # Observaciones
    obs = {
        "Compromiso":    form.compromiso,
        "Participación": form.participacion_actividades,
        "Concentración": form.concentracion,
        "Cansancio":     form.cansancio,
        "Interés":       form.interes_temas
    }
    wrap_section("Observaciones:", "\n".join(f"{k}: {v}" for k, v in obs.items()))

    # Otros aspectos a destacar
    wrap_section("Otros aspectos a destacar:", form.otros_aspectos)

    # Recomendaciones con contenidos
    wrap_section("Recomendaciones:", texto_recs)

    # Firma (imagen o texto)
    y -= 20
    if form.firma_file:
        try:
            img = ImageReader(io.BytesIO(form.firma_file))
            p.setFont("Helvetica-Bold", 12)
            p.drawString(50, y, "Firma:")
            y -= 18
            p.drawImage(img, 60, y-40+10, width=120, height=40, mask='auto')
            y -= 60
        except Exception:
            pass
    elif form.nombre_firma:
        p.setFont("Helvetica-Bold", 12)
        p.drawString(50, y, "Firma:")
        y -= 18
        p.setFont("Helvetica-Oblique", 12)
        p.drawString(60, y, form.nombre_firma)
        y -= 60

    # Finaliza y envía
    p.showPage()
    p.save()
    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"informe_{form_id}.pdf",
        mimetype='application/pdf'
    )


@form_gestores_bp.route('/delete_especific_form', methods=['POST'])
def delete_especific_form():
    try:
        data = request.get_json()
        form_id = data.get("id")

        if not form_id:
            return jsonify({"error": "Falta el ID del formulario"}), 400

        formulario = FormularioGestor.query.get(form_id)

        if not formulario:
            return jsonify({"error": "Formulario no encontrado"}), 404

        db.session.delete(formulario)
        db.session.commit()

        return jsonify({"message": f"Formulario {form_id} eliminado correctamente"}), 200

    except Exception as e:
        print(f"Error eliminando formulario: {str(e)}")
        return jsonify({"error": "Error interno del servidor"}), 500
    

@form_gestores_bp.route('/form_gestores_batch', methods=['POST'])
def form_gestores_batch():
    try:
        data_array = request.get_json()

        if not isinstance(data_array, list):
            return jsonify({"error": "Se esperaba un array de objetos"}), 400

        for data in data_array:
            # Procesar fecha
            try:
                fecha_usr = datetime.strptime(data.get('fecha_usuario', ''), '%Y-%m-%d').date()
            except ValueError:
                fecha_usr = None

            # Recomendaciones (formato nuevo o vacío)
            raw_recs = data.get('recomendaciones', {}) or {}
            texto_recs = ""
            for curso_rec, items in raw_recs.items() if isinstance(raw_recs, dict) else []:
                texto_recs += f"{curso_rec}:\n"
                for it in items:
                    texto_recs += f"• {it}\n"
                texto_recs += "\n"
            nombres_recs = ', '.join(raw_recs.keys()) if isinstance(raw_recs, dict) else ""

            nuevo = FormularioGestor(
                apies                     = data.get('apies'),
                curso                     = data.get('curso'),
                fecha_usuario             = fecha_usr,
                gestor                    = data.get('gestor'),
                duracion_horas            = int(data.get('duracion_horas') or 0),
                objetivo                  = data.get('objetivo'),
                contenido_desarrollado    = data.get('contenido_desarrollado'),
                ausentes                  = int(data.get('ausentes') or 0),
                presentes                 = int(data.get('presentes') or 0),
                resultados_logros         = data.get('resultados_logros'),
                compromiso                = data.get('compromiso'),
                participacion_actividades = data.get('participacion_actividades'),
                concentracion             = data.get('concentracion'),
                cansancio                 = data.get('cansancio'),
                interes_temas             = data.get('interes_temas'),
                recomendaciones           = nombres_recs,
                otros_aspectos            = data.get('otros_aspectos'),
                jornada                   = data.get('jornada'),
                dotacion_real_estacion    = int(data.get('dotacion_real_estacion') or 0),
                dotacion_en_campus        = int(data.get('dotacion_en_campus') or 0),
                firma_file                = base64.b64decode(data.get('firma_file')) if data.get('firma_file') else None,
                nombre_firma              = data.get('nombre_firma'),
                email_gestor              = data.get('email_gestor'),
                creado_en                 = datetime.utcnow()
            )

            db.session.add(nuevo)

        db.session.commit()
        return jsonify({"message": f"{len(data_array)} formularios guardados correctamente"}), 201

    except Exception as e:
        print(f"Error al guardar formularios: {str(e)}")
        return jsonify({"error": "Error interno del servidor"}), 500
