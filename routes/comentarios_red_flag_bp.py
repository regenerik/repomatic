from flask import Blueprint, send_file, make_response, request, jsonify, render_template, current_app, Response # Blueprint para modularizar y relacionar con app
from flask_bcrypt import Bcrypt                                  # Bcrypt para encriptación
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity   # Jwt para tokens
from models import AllCommentsWithEvaluation,FilteredExperienceComments   # importar tabla "User" de models
from database import db                                          # importa la db desde database.py
from datetime import timedelta, datetime                         # importa tiempo especifico para rendimiento de token válido
from utils.red_flag_utils import process_missing_fields, red_flag_finder
from logging_config import logger
import os                                                        # Para datos .env
from dotenv import load_dotenv                                   # Para datos .env
load_dotenv()
import pandas as pd
from io import BytesIO



comentarios_red_flag_bp = Blueprint('comentarios_red_flag_bp', __name__)     # instanciar admin_bp desde clase Blueprint para crear las rutas.
bcrypt = Bcrypt()
jwt = JWTManager()


    
# RUTA TEST:

@comentarios_red_flag_bp.route('/test_comentarios_red_flag_bp', methods=['GET'])
def test():
    return jsonify({'message': 'test bien sucedido','status':"Si lees esto, funcionan rutas COMENTARIOS RED FLAG BP"}),200


#  ( PASO 1 ) - EVALUACION DE TODOS LOS COMENTARIOS BUSCANDO RED FLAGS

@comentarios_red_flag_bp.route('/red_flag_comments_evaluation', methods=['POST'])
def get_evaluation_of_all_red_flags():
    from extensions import executor
    try:
        logger.info("1 - Entró en la ruta red_flag_comments_evaluation")
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
            executor.submit(run_get_evaluations_of_all, file_content)

            return jsonify({"message": "El proceso de recuperacion del reporte ha comenzado"}), 200

        else:
            logger.info("Error - El archivo que se proporcionó no es válido. Fijate que sea un .xlsx")
            return jsonify({"error": "El archivo no es válido. Solo se permiten archivos .xlsx"}), 400
    
    except Exception as e:
        return jsonify({"error": f"Se produjo un error: {str(e)}"}), 500


def run_get_evaluations_of_all(file_content):
    with current_app.app_context():
        red_flag_finder(file_content)


#  ( PASO 2 ) DESCARGAR PRIMERA EVALUACION DE RED FLAGS / DESCARGA UNA VERSIÓN SIN CORRECCIONES de "AllCommentsWithEvaluation"
@comentarios_red_flag_bp.route('/download_red_flag_evaluation', methods=['GET'])
def download_comments_evaluation():
    try:
        # Buscar el único archivo en la base de datos
        archivo = AllCommentsWithEvaluation.query.first()  # Como siempre habrá un único registro, usamos .first()

        if not archivo:
            return jsonify({"error": "No se encontró ningún archivo"}), 404

        # Leer el archivo binario desde la base de datos
        archivo_binario = archivo.archivo_binario

        # # Convertir el binario a CSV directamente
        # csv_data = archivo_binario.decode('utf-8') 

        # Preparar la respuesta con el CSV como descarga
        return Response(
            archivo_binario,
            mimetype="text/csv",
            headers={"Content-disposition": "attachment; filename=incomplete_red_flag_evaluation.csv"}
        )
    
    except Exception as e:
        return jsonify({"error": f"Se produjo un error al procesar el archivo: {str(e)}"}), 500


#  ( PASO 3 ) CORRECCIÓN DE CAMPOS VACIOS - Corrige en loop todos los campos vacios (aprox 8 loops )Es necesario enviarle el archivo generado en el paso 1 y decargado en paso 2. 
@comentarios_red_flag_bp.route('/correccion_campos_no_evaluados', methods=['POST'])
def missing_fields_evaluation():
    from extensions import executor
    try:
        logger.info("1 - Entró en la ruta correccion_campos_vacios")
        if 'file' not in request.files:
            logger.info(f"Error al recuperar el archivo adjunto del request")
            return jsonify({"error": "No se encontró ningún archivo en la solicitud"}), 400

        file = request.files['file']

        if file.filename == '':
            return jsonify({"error": "No se seleccionó ningún archivo"}), 400

        if file and file.filename.lower().endswith('.csv'):
            # Leer el archivo CSV directamente desde la memoria (sin decodificar)
            logger.info("2 - Archivo recuperado. Leyendo archivo CSV...")
            file_content = file.read()  # Mantener el archivo como bytes
            
            logger.info("3 - Llamando util process_missing_fields para procesar los campos faltantes en hilo paralelo...")
            executor.submit(run_process_missing_fields, file_content)

            return jsonify({"message": "El proceso de corrección del reporte ha comenzado"}), 200

        else:
            logger.info("Error - El archivo proporcionado no es válido. Fijate que sea un .csv")
            return jsonify({"error": "El archivo no es válido. Solo se permiten archivos .csv"}), 400
    
    except Exception as e:
        logger.error(f"Error en la ruta correccion_campos_vacios: {str(e)}")
        return jsonify({"error": f"Se produjo un error: {str(e)}"}), 500

def run_process_missing_fields(file_content):
    with current_app.app_context():
        process_missing_fields(file_content)

#  ( PASO 4 ) DESCARGAR EVALUACION DE TOPICO DE COMENTARIOS TOTALES ( CON CORRECCIONES DE: CAMPOS VACIOS)
@comentarios_red_flag_bp.route('/descargar_red_flags', methods=['GET'])
def descargar_positividad_corregida():
    try:
        # Buscar el único archivo en la base de datos
        archivo = FilteredExperienceComments.query.first()  # Como siempre habrá un único registro, usamos .first()

        if not archivo:
            return jsonify({"error": "No se encontró ningún archivo"}), 404

        # Leer el archivo binario desde la base de datos
        archivo_binario = archivo.archivo_binario

        # Preparar la respuesta con el CSV como descarga
        return Response(
            archivo_binario,
            mimetype="text/csv",
            headers={"Content-disposition": "attachment; filename=all_comments_red_flag.csv"}
        )
    
    except Exception as e:
        return jsonify({"error": f"Se produjo un error al procesar el archivo: {str(e)}"}), 500