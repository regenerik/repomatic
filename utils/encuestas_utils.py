from openai import OpenAI
import requests
from bs4 import BeautifulSoup
import re
import pandas as pd
from io import BytesIO
from database import db
from models import  Survey
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timedelta
from io import BytesIO
import pytz
from dotenv import load_dotenv
load_dotenv()
import os
from logging_config import logger
import gc
# Zona horaria de São Paulo/Buenos Aires
tz = pytz.timezone('America/Sao_Paulo')

# - Creando cliente openai
client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    organization="org-cSBk1UaTQMh16D7Xd9wjRUYq"
)


# --------------------------------------------el de nahu------------------------------------------------------


def obtener_y_guardar_survey():

    api_key = os.getenv('SURVEYMONKEY_API_KEY')
    access_token = os.getenv('SURVEYMONKEY_ACCESS_TOKEN')
    survey_id = os.getenv('SURVEY_ID')

    logger.info("2 - Ya en Utils - Iniciando la recuperación de la encuesta...")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    HOST = "https://api.surveymonkey.com"
    SURVEY_RESPONSES_ENDPOINT = f"/v3/surveys/{survey_id}/responses/bulk"
    SURVEY_DETAILS_ENDPOINT = f"/v3/surveys/{survey_id}/details"

    # Obtener detalles de la encuesta
    survey_details = requests.get(f"{HOST}{SURVEY_DETAILS_ENDPOINT}", headers=headers).json()

    choice_map = {}
    question_map = {}

    logger.info("3 - Request hecho perfecto,...Empieza la iteracion")

    for page in survey_details["pages"]:
        for question in page["questions"]:
            question_map[question["id"]] = question["headings"][0]["heading"]
            if "answers" in question:
                for answer in question["answers"]["choices"]:
                    choice_map[answer["id"]] = answer["text"]

    page = 1
    per_page = 10000
    all_responses = []

    logger.info("4 - Terminó la iteracion de las pages en survey_details. Comenzando con While haciendo request de cada página...")

    while True:
        response_data = requests.get(f"{HOST}{SURVEY_RESPONSES_ENDPOINT}?page={page}&per_page={per_page}", headers=headers)
        if response_data.status_code == 200:
            responses_json = response_data.json()["data"]
            if not responses_json:
                break
            all_responses.extend(responses_json)
            page += 1
        else:
            logger.info(f"Error: {response_data.status_code}")
            break

    logger.info("5 - Terminó el while de fetchs por pagina...Comienza el for response in all_responses")

    responses_dict = {}
    for response in all_responses:
        respondent_id = response["id"]
        if respondent_id not in responses_dict:
            responses_dict[respondent_id] = {}
        responses_dict[respondent_id]['custom_variables'] = response.get('custom_variables', {}).get('ID_CODE', '')
        responses_dict[respondent_id]['date_created'] = response.get('date_created', '')[:10]
        for page in response["pages"]:
            for question in page["questions"]:
                question_id = question["id"]
                for answer in question["answers"]:
                    if "choice_id" in answer:
                        responses_dict[respondent_id][question_id] = choice_map.get(answer["choice_id"], answer["choice_id"])
                    elif "text" in answer:
                        responses_dict[respondent_id][question_id] = answer["text"]
                    elif "row_id" in answer and "text" in answer:
                        responses_dict[respondent_id][question_id] = answer["text"]

    df_responses = pd.DataFrame.from_dict(responses_dict, orient='index')

    logger.info("6 - Terminó el For, y ya creó el df_responses! Ya casi estamos !Ahora  creamos funcion extract_text_from_spam y la usamos")

    def extract_text_from_span(html_text):
        return re.sub(r'<[^>]*>', '', html_text)

    if '152421787' in df_responses.columns:
        df_responses['152421787'] = df_responses['152421787'].apply(extract_text_from_span)

    df_responses.rename(columns=question_map, inplace=True)
    df_responses.columns = [extract_text_from_span(col) for col in df_responses.columns]

    logger.info("7 - Terminó de modificar df_reponses. Ahora vamos a convertir el dataFrame a binario preguardado...")    

    # Convertir el DataFrame a binario
    with BytesIO() as output:
        df_responses.to_pickle(output)  # Cambiamos a pickle
        binary_data = output.getvalue()

    logger.info("8 - Ya convertimos el dataframe a binario, ahora vamos a guardar el archivo...")

    # Elimina registros previos en la tabla que corresponde
    report_to_delete = Survey.query.first()
    if report_to_delete:
        db.session.delete(report_to_delete)
        db.session.commit()
        logger.info("9 - Survey previo eliminado >>> guardando el nuevo...")

    # Instancia el nuevo registro a la tabla que corresponde y guarda en db
    new_survey = Survey(data=binary_data)
    db.session.add(new_survey)
    db.session.commit()
    logger.info("10 - Survey nuevo guardado en la base de datos. Fin de la ejecución.")

    gc.collect()

    return





