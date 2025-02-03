from flask import Blueprint, send_file, make_response, request, jsonify, render_template, current_app, Response # Blueprint para modularizar y relacionar con app
from flask_bcrypt import Bcrypt                                  # Bcrypt para encriptación
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity   # Jwt para tokens
from models import AllCommentsWithEvaluation,FilteredExperienceComments   # importar tabla "User" de models
from database import db                                          # importa la db desde database.py
from datetime import timedelta, datetime                         # importa tiempo especifico para rendimiento de token válido
from utils.find_comments_utils import red_flag_master_util
from logging_config import logger
import os                                                        # Para datos .env
from dotenv import load_dotenv                                   # Para datos .env
load_dotenv()
import pandas as pd
from io import BytesIO
import json



find_comments_bp = Blueprint('find_comments_bp', __name__)     # instanciar admin_bp desde clase Blueprint para crear las rutas.
bcrypt = Bcrypt()
jwt = JWTManager()


    
# RUTA TEST:

@find_comments_bp.route('/test_find_comments_bp', methods=['GET'])
def test():
    return jsonify({'message': 'test bien sucedido','status':"Si lees esto, funcionan rutas FIND COMMENTS BP"}),200


# MECANISMO:

@find_comments_bp.route('/find_comments', methods=['POST'])
def find_comments():
    from extensions import executor
    try:
        logger.info("Entramos a la ruta master de clasificación (find_comments).")

        # ----------------- 1) Validar que nos llegó un archivo XLSX -----------------
        if 'file' not in request.files:
            logger.info("No encontré ningún archivo en el request.")
            return jsonify({"error": "No se encontró ningún archivo en la solicitud"}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No se seleccionó ningún archivo"}), 400
        
        if not file.filename.lower().endswith('.xlsx'):
            logger.info("El archivo proporcionado no es .xlsx.")
            return jsonify({"error": "El archivo no es válido. Solo se permiten archivos .xlsx"}), 400

        # ----------------- 2) Recuperar el JSON que viene como parte del form-data -----------------
        # Ejemplo: en Postman, ponés form-data, con las siguientes claves:
        #   - key="file", type="file", y le adjuntás tu xlsx
        #   - key="body_data", type="text", y pegás tu JSON ({"prompt":"...","sentimientos_aceptados":[...],...})
        #
        # Luego acá hacemos:
        json_str = request.form.get('body_data')  # o el nombre que uses en Postman, p. ej. "json"
        if json_str:
            try:
                body_data = json.loads(json_str)
            except Exception as e:
                logger.warning(f"No se pudo parsear el JSON enviado en body_data: {str(e)}")
                body_data = {}
        else:
            body_data = {}

        # ----------------- 3) Extraer parámetros del JSON (si existen) -----------------
        prompt = body_data.get("prompt", None)
        # Validar que sea un string no vacío
        if not isinstance(prompt, str) or not prompt.strip():
            prompt = None

        sentimientos_aceptados = body_data.get("sentimientos_aceptados", None)
        if not isinstance(sentimientos_aceptados, list) or len(sentimientos_aceptados) == 0:
            sentimientos_aceptados = None
        else:
            valid_sents = {"positivo", "negativo", "invalido"}
            if not set(sentimientos_aceptados).issubset(valid_sents):
                logger.warning("sentimientos_aceptados contenían valores inválidos. Se ignora el filtro.")
                sentimientos_aceptados = None

        topicos_aceptados = body_data.get("topicos_aceptados", None)
        if not isinstance(topicos_aceptados, list) or len(topicos_aceptados) == 0:
            topicos_aceptados = None

        cantidad_minima_caracteres = body_data.get("cantidad_minima_caracteres", None)
        if not isinstance(cantidad_minima_caracteres, int) or cantidad_minima_caracteres <= 0:
            cantidad_minima_caracteres = None

        logger.info(
            f"JSON extraído de body_data: prompt={prompt}, "
            f"sentimientos_aceptados={sentimientos_aceptados}, "
            f"topicos_aceptados={topicos_aceptados}, "
            f"cantidad_minima_caracteres={cantidad_minima_caracteres}"
        )

        # ----------------- 4) Leer el contenido binario del .xlsx -----------------
        file_content = file.read()

        # ----------------- 5) Disparamos proceso en segundo plano -----------------
        executor.submit(
            run_get_evaluations_of_all,
            file_content,
            prompt,
            sentimientos_aceptados,
            topicos_aceptados,
            cantidad_minima_caracteres
        )

        return jsonify({"message": "Se inició la clasificación y corrección de campos en segundo plano"}), 200

    except Exception as e:
        logger.error(f"Error en la ruta find_comments: {str(e)}")
        return jsonify({"error": f"Se produjo un error: {str(e)}"}), 500


def run_get_evaluations_of_all(
    file_content,
    prompt=None,
    sentimientos_aceptados=None,
    topicos_aceptados=None,
    cantidad_minima_caracteres=None
):
    """
    Toma el file_content y parámetros, y en el app_context llama al util principal
    que hace toda la secuencia (filtro inicial + clasificación + relleno campos vacíos).
    """
    with current_app.app_context():
        red_flag_master_util(
            file_content,
            prompt,
            sentimientos_aceptados,
            topicos_aceptados,
            cantidad_minima_caracteres
        )


@find_comments_bp.route('/download_comments_filtered', methods=['GET'])
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
            headers={"Content-disposition": "attachment; filename=find_comments_resolved.csv"}
        )
    
    except Exception as e:
        return jsonify({"error": f"Se produjo un error al procesar el archivo: {str(e)}"}), 500