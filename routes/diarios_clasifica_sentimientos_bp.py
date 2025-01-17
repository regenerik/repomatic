from flask import Blueprint, send_file, make_response, request, jsonify, render_template, current_app, Response # Blueprint para modularizar y relacionar con app
from flask_bcrypt import Bcrypt                                  # Bcrypt para encriptación
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity   # Jwt para tokens
from models import  DailyCommentsWithEvaluation                  # importar tabla "User" de models
from database import db                                          # importa la db desde database.py
from datetime import timedelta, datetime                         # importa tiempo especifico para rendimiento de token válido
from utils.diarios_utils import get_evaluations_of_a_day, get_evaluations_of_a_day_nps
from logging_config import logger
import os                                                        # Para datos .env
from dotenv import load_dotenv                                   # Para datos .env
load_dotenv()
import pandas as pd
from io import BytesIO



diarios_clasifica_sentimientos_bp = Blueprint('diarios_clasifica_sentimientos_bp', __name__)     # instanciar admin_bp desde clase Blueprint para crear las rutas.
bcrypt = Bcrypt()
jwt = JWTManager()

# Sistema de key base pre rutas ------------------------:

API_KEY = os.getenv('API_KEY')

def check_api_key(api_key):
    return api_key == API_KEY

@diarios_clasifica_sentimientos_bp.before_request
def authorize():
    if request.method == 'OPTIONS':
        return
    if request.path in ['/download_daily_comments_evaluation','/generate_daily_comments_evaluation','/comparar_comentarios','/evaluate_negative_comments','/test_clasifica_comentarios_individuales_bp','/','/correccion_campos_vacios','/descargar_positividad_corregida','/download_comments_evaluation','/all_comments_evaluation','/download_resume_csv','/create_resumes_of_all','/descargar_excel','/create_resumes', '/reportes_disponibles', '/create_user', '/login', '/users','/update_profile','/update_profile_image','/update_admin']:
        return
    api_key = request.headers.get('Authorization')
    if not api_key or not check_api_key(api_key):
        return jsonify({'message': 'Unauthorized'}), 401
    
# RUTA TEST:

@diarios_clasifica_sentimientos_bp.route('/test_clasifica_comentarios_individuales_bp', methods=['GET'])
def test():
    return jsonify({'message': 'test bien sucedido','status':"Si lees esto es porque las rutas de evaluacion de sentimientos diarios funcionan"}),200

#  ( PASO 1 ) - EVALUACION DE TODOS LOS COMENTARIOS 1 A 1 POR POSITIVIDAD O NEGATIVIDAD ( PASO 1 )

@diarios_clasifica_sentimientos_bp.route('/generate_daily_comments_evaluation', methods=['POST'])
def get_evaluation_of_all():
    from extensions import executor
    try:
        logger.info("1 - Entró en la ruta all_comments_evaluation")
        if 'file' not in request.files:
            logger.info(f"Error al recuperar el archivo adjunto del request")
            return jsonify({"error": "No se encontró ningún archivo en la solicitud"}), 400

        file = request.files['file']

        if file.filename == '':
            return jsonify({"error": "No se seleccionó ningún archivo"}), 400


        if file and file.filename.lower().endswith('.xlsx'):
            # Leer el archivo directamente desde la memoria
            logger.info("2 - Archivo recuperado. Leyendo archivo...")
            file_content = file.read()

            logger.info("3 - Llamando util get_evaluations_of_all para la creación de resumenes en hilo paralelo...")
            executor.submit(run_get_evaluations_of_a_day, file_content)

            return jsonify({"message": "El proceso de recuperacion de los sentimientos diarios ha comenzado"}), 200

        else:
            logger.info("Error - El archivo que se proporcionó no es válido. Fijate que sea un .xlsx")
            return jsonify({"error": "El archivo no es válido. Solo se permiten archivos .xlsx"}), 400
    
    except Exception as e:
        return jsonify({"error": f"Se produjo un error: {str(e)}"}), 500


def run_get_evaluations_of_a_day(file_content):
    with current_app.app_context():
        get_evaluations_of_a_day(file_content)


#  ( PASO 2 ) DESCARGAR PRIMERA EVALUACION DE POSITIVIDAD DE COMENTARIOS TOTALES / DESCARGA UNA VERSIÓN SIN CORRECCIONES de "AllCommentsWithEvaluation"
@diarios_clasifica_sentimientos_bp.route('/download_daily_comments_evaluation', methods=['GET'])
def download_comments_evaluation():
    try:
        # Buscar el único archivo en la base de datos
        archivo = DailyCommentsWithEvaluation.query.first()  # Como siempre habrá un único registro, usamos .first()

        if not archivo:
            return jsonify({"error": "No se encontró ningún archivo"}), 404

        # Leer el archivo binario desde la base de datos
        archivo_binario = archivo.archivo_binario

        # Convertir el binario (CSV) a un DataFrame
        df = pd.read_csv(BytesIO(archivo_binario), encoding='utf-8')

        # Eliminar la columna 'ID'
        if 'ID' in df.columns:
            df.drop(columns=['ID'], inplace=True)

        # Si el comentario contiene solo "no", cambiar a "inválido"
        df.loc[df['COMENTARIO'].str.strip().str.lower() == 'no', 'SENTIMIENTO'] = 'inválido'

        # Si el comentario incluye la palabra "milei", cambiar a "inválido"
        df.loc[df['COMENTARIO'].str.contains(r'\bmilei\b', case=False, na=False), 'SENTIMIENTO'] = 'inválido'


        # Convertir el DataFrame a Excel
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Comentarios')

        # Preparar el archivo Excel para ser descargado
        output.seek(0)
        return Response(
            output,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-disposition": "attachment; filename=daily_comments_evaluation.xlsx"}
        )
    
    except Exception as e:
        return jsonify({"error": f"Se produjo un error al procesar el archivo: {str(e)}"}), 500


# -------------------------- DAILY COMENTS EVALUATION NPS DEDICADO ------------------------------



#  ( PASO 1 ) - EVALUACION DE TODOS LOS COMENTARIOS 1 A 1 POR POSITIVIDAD O NEGATIVIDAD ( PASO 1 )

@diarios_clasifica_sentimientos_bp.route('/generate_daily_comments_evaluation_nps', methods=['POST'])
def get_evaluation_of_all_nps():
    from extensions import executor
    try:
        logger.info("1 - Entró en la ruta all_comments_evaluation_nps")
        if 'file' not in request.files:
            logger.info(f"Error al recuperar el archivo adjunto del request")
            return jsonify({"error": "No se encontró ningún archivo en la solicitud"}), 400

        file = request.files['file']

        if file.filename == '':
            return jsonify({"error": "No se seleccionó ningún archivo"}), 400


        if file and file.filename.lower().endswith('.xlsx'):
            # Leer el archivo directamente desde la memoria
            logger.info("2 - Archivo recuperado. Leyendo archivo...")
            file_content = file.read()

            logger.info("3 - Llamando util get_evaluations_of_all para la creación de resumenes en hilo paralelo...")
            executor.submit(run_get_evaluations_of_a_day_nps, file_content)

            return jsonify({"message": "El proceso de recuperacion de los sentimientos diarios ha comenzado"}), 200

        else:
            logger.info("Error - El archivo que se proporcionó no es válido. Fijate que sea un .xlsx")
            return jsonify({"error": "El archivo no es válido. Solo se permiten archivos .xlsx"}), 400
    
    except Exception as e:
        return jsonify({"error": f"Se produjo un error: {str(e)}"}), 500


def run_get_evaluations_of_a_day_nps(file_content):
    with current_app.app_context():
        get_evaluations_of_a_day_nps(file_content)


#  ( PASO 2 ) DESCARGAR PRIMERA EVALUACION DE POSITIVIDAD DE COMENTARIOS TOTALES / DESCARGA UNA VERSIÓN SIN CORRECCIONES de "AllCommentsWithEvaluation"
@diarios_clasifica_sentimientos_bp.route('/download_daily_comments_evaluation_nps', methods=['GET'])
def download_comments_evaluation_nps():
    try:
        # Buscar el único archivo en la base de datos
        archivo = DailyCommentsWithEvaluation.query.first()  # Como siempre habrá un único registro, usamos .first()

        if not archivo:
            return jsonify({"error": "No se encontró ningún archivo"}), 404

        # Leer el archivo binario desde la base de datos
        archivo_binario = archivo.archivo_binario

        # Convertir el binario (CSV) a un DataFrame
        df = pd.read_csv(BytesIO(archivo_binario), encoding='utf-8')

        # Eliminar la columna 'ID'
        if 'ID' in df.columns:
            df.drop(columns=['ID'], inplace=True)

        # Si el comentario contiene solo "no", cambiar a "inválido"
        df.loc[df['COMENTARIO'].str.strip().str.lower() == 'no', 'SENTIMIENTO'] = 'inválido'

        # Si el comentario incluye la palabra "milei", cambiar a "inválido"
        df.loc[df['COMENTARIO'].str.contains(r'\bmilei\b', case=False, na=False), 'SENTIMIENTO'] = 'inválido'


        # Convertir el DataFrame a Excel
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Comentarios')

        # Preparar el archivo Excel para ser descargado
        output.seek(0)
        return Response(
            output,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-disposition": "attachment; filename=daily_comments_evaluation_nps.xlsx"}
        )
    
    except Exception as e:
        return jsonify({"error": f"Se produjo un error al procesar el archivo: {str(e)}"}), 500

