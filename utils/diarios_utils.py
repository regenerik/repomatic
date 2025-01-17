from openai import OpenAI
import requests
from bs4 import BeautifulSoup
import re
import pandas as pd
from io import BytesIO
from database import db
from models import Reporte, TodosLosReportes, Survey, AllApiesResumes, DailyCommentsWithEvaluation, FilteredExperienceComments
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

# MODELO FINAL PARA CAPTURA DE EVALUACIÓN DE POSITIVIDAD DE COMENTARIOS

# Captura inicial de sentimientos de la tabla totales:
def get_evaluations_of_a_day(file_content):
    logger.info("4 - Util get_evaluations_of_all inicializado")
    
    # Leer el archivo Excel desde el contenido en memoria (file_content)
    logger.info("5 - Leyendo excel y agregando ID...")
    df = pd.read_excel(BytesIO(file_content))

    # Agregar columna de ID con un número secuencial para cada comentario
    df['ID'] = range(1, len(df) + 1)

    # Asegurar que la columna de SENTIMIENTO existe
    df['SENTIMIENTO'] = ""
    
    # Obtener las APIES únicas
    apies_unicas = df['APIES'].unique()

    logger.info(f"Total de APIES únicas: {len(apies_unicas)}")

    for apies_input in apies_unicas:
        logger.info(f"Procesando APIES {apies_input}...")

        # Filtrar comentarios por APIES y crear un diccionario {ID: Comentario}
        comentarios_filtrados = df[df['APIES'] == apies_input][['ID', 'COMENTARIO']]
        comentarios_dict = dict(zip(comentarios_filtrados['ID'], comentarios_filtrados['COMENTARIO']))

        # Crear el prompt para OpenAI
        prompt = "Para cada comentario a continuación, responde SOLO con el formato 'ID-{id}: positivo', 'ID-{id}: negativo' o 'ID-{id}: invalido'. Si el comentario no es claro o no tiene un sentimiento definido, responde 'invalido'. No utilices otras palabras como 'neutro'.Comentarios con solo un 'ok', 'joya','bien','agil' o derivados de ese estilo representando aceptación, son conciderados 'positivos'.Si se habla de rapidez o eficiencia positivamente, tambien será conciderado 'positivo'.Un '10' o un '100' suelto, o acompañado por la palabra 'nota', se concidera positivo.La palabra 'no' suelta se concidera invalida. Si se expresa la falta de algun producto se concidera 'negativo'. Aquí están los comentarios:\n"
        for comentario_id, comentario in comentarios_dict.items():
            prompt += f"ID-{comentario_id}: {comentario}\n"

        # Hacer el pedido a OpenAI
        try:
            logger.info(f"Enviando solicitud a OpenAI para APIES {apies_input}...")
            completion = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Eres un analista que clasifica comentarios por sentimiento."},
                    {"role": "user", "content": prompt}
                ]
            )

            respuesta = completion.choices[0].message.content
            logger.info(f"Respuesta obtenida para APIES {apies_input}")

            # Guardar la respuesta en el log (COMENTADO)
            # log_file.write(f"APIES {apies_input}:\n{respuesta}\n\n")

            # Parsear la respuesta usando expresiones regulares para extraer el ID y el sentimiento
            matches = re.findall(r'ID-(\d+):\s*(positivo|negativo|invalido)', respuesta)

            # Actualizar la columna 'SENTIMIENTO' usando los IDs
            for match in matches:
                comentario_id, sentimiento = match
                df.loc[df['ID'] == int(comentario_id), 'SENTIMIENTO'] = sentimiento

        except Exception as e:
            logger.error(f"Error al procesar el APIES {apies_input}: {e}")

    # Agregar la clasificación de tópicos con el prompt explícito
    logger.info(f"Agregar tópicos en ejecución")
    df = add_topic_classification_to_comments_static(df)
    logger.info(f"Agregar tópicos finalizado")

    df.loc[df['SENTIMIENTO'] == 'invalido', 'TOPICO'] = 'EXPERIENCIA_GENERICA'

    # Guardar el DataFrame actualizado en formato binario (como CSV)
    logger.info("Guardando DataFrame actualizado con sentimiento...")
    output = BytesIO()
    df.to_csv(output, index=False, encoding='utf-8', sep=',', quotechar='"', quoting=1)
    output.seek(0)
    archivo_binario = output.read()

    logger.info("Proceso completado. Guardando en base de datos...")

    # Guardar el archivo en la tabla AllCommentsWithEvaluation
    archivo_anterior = DailyCommentsWithEvaluation.query.first()
    if archivo_anterior:
        db.session.delete(archivo_anterior)
        db.session.commit()

    # Crear un nuevo registro y guardar el archivo binario
    archivo_resumido = DailyCommentsWithEvaluation(archivo_binario=archivo_binario)
    db.session.add(archivo_resumido)
    db.session.commit()

    logger.info("Archivo guardado exitosamente en la tabla DailyCommentsWithEvaluation.")
    return

# AHORA VAMOS CON LOS UTILS PARA LOS TOPICOS.


def generate_static_prompt():
    """
    Genera un prompt explícito con todos los tópicos y sub-tópicos escritos directamente.
    """
    prompt = """
Evalúa el siguiente comentario para determinar a cuál de los siguientes 10 tópicos pertenece.(no inventes tópicos nuevos, si crees que el comentario no encaja en nigun tópico, clasifícalo como EXPERIENCIA_GENERICA):

1. Si el comentario menciona temas como TRATO_ACTITUD, ATENCION_GENERAL, SERVICIOS_DE_CORTESIA, CONOCIMIENTO_DEL_VENDEDOR, y solo cuando sea evidente que se esté hablando de la atención al cliente, probablemente se trate del tópico ATENCION_AL_CLIENTE.

2. Si el comentario menciona temas como CALIDAD_NAFTA_INFINIA, CALIDAD_CAFE, CALIDAD_HAMBURGUESAS, probablemente se trate del tópico CALIDAD_DE_PRODUCTOS.

3. Si el comentario menciona temas como APLICACIONES_DIGITALES, USO_DE_TARJETAS_DIGITALES, probablemente se trate del tópico DIGITAL.

4. Si el comentario menciona temas como EXPERIENCIA_POSITIVA, EXPERIENCIA_GENERAL, COSAS_IRRELEVANTES, o es especificamente la palabra "ok" , o contiene las palabras "bien", "muy bien", "mb" sin contexto, y variantes parecidas, o además las evaluaciones con puntajes sin contexto como por ejemplo "10","de 10","10 puntos" o similares,  probablemente todos esos ejemplos se traten del tópico EXPERIENCIA_GENERICA.

5. Si el comentario menciona temas como IMAGEN_DE_INSTALACIONES, SERVICIOS_GENERALES, probablemente se trate del tópico IMAGEN_INSTALACIONES_Y_SERVICIOS_GENERALES.

6. Si el comentario menciona temas como RECLAMOS_SERIOS, PROBLEMAS_CRITICOS, probablemente se trate del tópico PROBLEMATICAS_CRITICAS.

7. Si el comentario menciona temas como LIMPIEZA_BAÑOS, HIGIENE_SANITARIOS, probablemente se trate del tópico SANITARIOS.

8. Si el comentario menciona temas como FALTA_DE_STOCK, DISPONIBILIDAD_PRODUCTOS, probablemente se trate del tópico STOCK_DE_PRODUCTOS.

9. Si el comentario menciona temas como DEMORAS_EN_EL_SERVICIO, RAPIDEZ_ATENCION, probablemente se trate del tópico TIEMPO_DE_ESPERA.

10. Si el comentario menciona temas como PRECIOS_ALTOS, USO_DE_TARJETAS_BANCARIAS, probablemente se trate del tópico VARIABLES_ECONOMICAS_Y_BANCOS.

Responde con el siguiente formato:
TOPICO: nombre del tópico

No uses corchetes, comillas ni ningún otro símbolo. Escribe SOLO el nombre del tópico después de "TOPICO:". Por ejemplo:
TOPICO: EXPERIENCIA_GENERICA
"""
    return prompt


def add_topic_classification_to_comments_static(df):
    """
    Clasifica los comentarios en el DataFrame por tópico usando un prompt explícito.
    """
    # Obtener el prompt fijo
    prompt_base = generate_static_prompt()
    logger.info("Generando clasificación de tópicos para los comentarios...")

    # Crear columna de TÓPICO en el DataFrame
    df['TOPICO'] = ""
    contador_comentarios_revisados = 0
    # Iterar por cada comentario y clasificar
    for idx, row in df.iterrows():
        contador_comentarios_revisados += 1
        logger.info(f"Revisando comentario número: {contador_comentarios_revisados}")
        comentario = row['COMENTARIO']

        # Generar el prompt específico para este comentario
        prompt = f"{prompt_base}\nComentario: {comentario}\n"
        
        try:
            # Enviar solicitud a OpenAI
            completion = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Eres un analista que clasifica comentarios en tópicos."},
                    {"role": "user", "content": prompt}
                ]
            )
            # Guardar la respuesta
            respuesta = completion.choices[0].message.content.strip()
            
            # Capturar solo el nombre del tópico
            match = re.search(r"TOPICO:\s*(.*)", respuesta)
            df.at[idx, 'TOPICO'] = match.group(1) if match else "Error"

        except Exception as e:
            logger.error(f"Error clasificando comentario ID {row['ID']}: {e}")
            df.at[idx, 'TOPICO'] = "Error"

    logger.info("Clasificación de tópicos completada.")
    return df




# -------------------------- DAILY COMENTS EVALUATION NPS DEDICADO ------------------------------


# Captura inicial de sentimientos de la tabla totales:
def get_evaluations_of_a_day_nps(file_content):
    logger.info("4 - Util get_evaluations_of_all inicializado")
    
    # Leer el archivo Excel desde el contenido en memoria (file_content)
    logger.info("5 - Leyendo excel y agregando ID...")
    df = pd.read_excel(BytesIO(file_content))

    # Agregar columna de ID con un número secuencial para cada comentario
    df['ID'] = range(1, len(df) + 1)

    # Asegurar que la columna de SENTIMIENTO existe
    df['SENTIMIENTO'] = ""
    
    # Obtener las APIES únicas
    apies_unicas = df['APIES'].unique()

    logger.info(f"Total de APIES únicas: {len(apies_unicas)}")

    for apies_input in apies_unicas:
        logger.info(f"Procesando APIES {apies_input}...")

        # Filtrar comentarios por APIES y crear un diccionario {ID: Comentario}
        comentarios_filtrados = df[df['APIES'] == apies_input][['ID', 'COMENTARIO']]
        comentarios_dict = dict(zip(comentarios_filtrados['ID'], comentarios_filtrados['COMENTARIO']))

        # Crear el prompt para OpenAI
        prompt = "Para cada comentario a continuación, responde SOLO con el formato 'ID-{id}: positivo', 'ID-{id}: negativo' o 'ID-{id}: invalido'. Si el comentario no es claro o no tiene un sentimiento definido, responde 'invalido'. No utilices otras palabras como 'neutro'.Comentarios con solo un 'ok', 'joya','bien','agil' o derivados de ese estilo representando aceptación, son conciderados 'positivos'.Si se habla de rapidez o eficiencia positivamente, tambien será conciderado 'positivo'.Un '10' o un '100' suelto, o acompañado por la palabra 'nota', se concidera positivo.La palabra 'no' suelta se concidera invalida. Si se expresa la falta de algun producto se concidera 'negativo'. Aquí están los comentarios:\n"
        for comentario_id, comentario in comentarios_dict.items():
            prompt += f"ID-{comentario_id}: {comentario}\n"

        # Hacer el pedido a OpenAI
        try:
            logger.info(f"Enviando solicitud a OpenAI para APIES {apies_input}...")
            completion = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Eres un analista que clasifica comentarios por sentimiento."},
                    {"role": "user", "content": prompt}
                ]
            )

            respuesta = completion.choices[0].message.content
            logger.info(f"Respuesta obtenida para APIES {apies_input}")

            # Guardar la respuesta en el log (COMENTADO)
            # log_file.write(f"APIES {apies_input}:\n{respuesta}\n\n")

            # Parsear la respuesta usando expresiones regulares para extraer el ID y el sentimiento
            matches = re.findall(r'ID-(\d+):\s*(positivo|negativo|invalido)', respuesta)

            # Actualizar la columna 'SENTIMIENTO' usando los IDs
            for match in matches:
                comentario_id, sentimiento = match
                df.loc[df['ID'] == int(comentario_id), 'SENTIMIENTO'] = sentimiento

        except Exception as e:
            logger.error(f"Error al procesar el APIES {apies_input}: {e}")

    # Agregar la clasificación de tópicos con el prompt explícito
    logger.info(f"Agregar tópicos en ejecución")
    df = add_topic_classification_to_comments_static_nps(df)
    logger.info(f"Agregar tópicos finalizado")

    df.loc[df['SENTIMIENTO'] == 'invalido', 'TOPICO'] = 'EXPERIENCIA_GENERICA'

    # Guardar el DataFrame actualizado en formato binario (como CSV)
    logger.info("Guardando DataFrame actualizado con sentimiento...")
    output = BytesIO()
    df.to_csv(output, index=False, encoding='utf-8', sep=',', quotechar='"', quoting=1)
    output.seek(0)
    archivo_binario = output.read()

    logger.info("Proceso completado. Guardando en base de datos...")

    # Guardar el archivo en la tabla AllCommentsWithEvaluation
    archivo_anterior = DailyCommentsWithEvaluation.query.first()
    if archivo_anterior:
        db.session.delete(archivo_anterior)
        db.session.commit()

    # Crear un nuevo registro y guardar el archivo binario
    archivo_resumido = DailyCommentsWithEvaluation(archivo_binario=archivo_binario)
    db.session.add(archivo_resumido)
    db.session.commit()

    logger.info("Archivo guardado exitosamente en la tabla DailyCommentsWithEvaluation.")
    return

# AHORA VAMOS CON LOS UTILS PARA LOS TOPICOS.


def generate_static_prompt_nps():
    """
    Genera un prompt explícito con todos los tópicos y sub-tópicos escritos directamente.
    """
    prompt = """
Evalúa el siguiente comentario para determinar a cuál de los siguientes 10 tópicos pertenece.(no inventes tópicos nuevos, si crees que el comentario no encaja en nigun tópico, clasifícalo como EXPERIENCIA_GENERICA):

1. Si el comentario menciona temas como TRATO_ACTITUD, ATENCION_GENERAL, SERVICIOS_DE_CORTESIA, CONOCIMIENTO_DEL_VENDEDOR, y solo cuando sea evidente que se esté hablando de la atención al cliente, probablemente se trate del tópico ATENCION_AL_CLIENTE.

2. Si el comentario menciona temas como CALIDAD_NAFTA_INFINIA, CALIDAD_CAFE, CALIDAD_HAMBURGUESAS, probablemente se trate del tópico CALIDAD_DE_PRODUCTOS.

3. Si el comentario menciona temas como APLICACIONES_DIGITALES, USO_DE_TARJETAS_DIGITALES, probablemente se trate del tópico DIGITAL.

4. Si el comentario menciona temas como EXPERIENCIA_POSITIVA, EXPERIENCIA_GENERAL, COSAS_IRRELEVANTES, o es especificamente la palabra "ok" , o contiene las palabras "bien", "muy bien", "mb" sin contexto, y variantes parecidas, o además las evaluaciones con puntajes sin contexto como por ejemplo "10","de 10","10 puntos" o similares,  probablemente todos esos ejemplos se traten del tópico EXPERIENCIA_GENERICA.

5. Si el comentario menciona temas como IMAGEN_DE_INSTALACIONES, SERVICIOS_GENERALES, probablemente se trate del tópico IMAGEN_INSTALACIONES_Y_SERVICIOS_GENERALES.

6. Si el comentario menciona temas como RECLAMOS_SERIOS, PROBLEMAS_CRITICOS, probablemente se trate del tópico PROBLEMATICAS_CRITICAS.

7. Si el comentario menciona temas como LIMPIEZA_BAÑOS, HIGIENE_SANITARIOS, probablemente se trate del tópico SANITARIOS.

8. Si el comentario menciona temas como FALTA_DE_STOCK, DISPONIBILIDAD_PRODUCTOS, probablemente se trate del tópico STOCK_DE_PRODUCTOS.

9. Si el comentario menciona temas como DEMORAS_EN_EL_SERVICIO, RAPIDEZ_ATENCION, probablemente se trate del tópico TIEMPO_DE_ESPERA.

10. Si el comentario menciona temas como PRECIOS_ALTOS, USO_DE_TARJETAS_BANCARIAS, probablemente se trate del tópico VARIABLES_ECONOMICAS_Y_BANCOS.

Responde con el siguiente formato:
TOPICO: nombre del tópico

No uses corchetes, comillas ni ningún otro símbolo. Escribe SOLO el nombre del tópico después de "TOPICO:". Por ejemplo:
TOPICO: EXPERIENCIA_GENERICA
"""
    return prompt


def add_topic_classification_to_comments_static_nps(df):
    """
    Clasifica los comentarios en el DataFrame por tópico usando un prompt explícito.
    """
    # Obtener el prompt fijo
    prompt_base = generate_static_prompt_nps()
    logger.info("Generando clasificación de tópicos para los comentarios...")

    # Crear columna de TÓPICO en el DataFrame
    df['TOPICO'] = ""
    contador_comentarios_revisados = 0
    # Iterar por cada comentario y clasificar
    for idx, row in df.iterrows():
        contador_comentarios_revisados += 1
        logger.info(f"Revisando comentario número: {contador_comentarios_revisados}")
        comentario = row['COMENTARIO']

        # Generar el prompt específico para este comentario
        prompt = f"{prompt_base}\nComentario: {comentario}\n"
        
        try:
            # Enviar solicitud a OpenAI
            completion = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Eres un analista que clasifica comentarios en tópicos."},
                    {"role": "user", "content": prompt}
                ]
            )
            # Guardar la respuesta
            respuesta = completion.choices[0].message.content.strip()
            
            # Capturar solo el nombre del tópico
            match = re.search(r"TOPICO:\s*(.*)", respuesta)
            df.at[idx, 'TOPICO'] = match.group(1) if match else "Error"

        except Exception as e:
            logger.error(f"Error clasificando comentario ID {row['ID']}: {e}")
            df.at[idx, 'TOPICO'] = "Error"

    logger.info("Clasificación de tópicos completada.")
    return df


