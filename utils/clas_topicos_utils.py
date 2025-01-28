from openai import OpenAI
import requests
from bs4 import BeautifulSoup
import re
import pandas as pd
from io import BytesIO
from database import db
from models import Reporte, TodosLosReportes, Survey, AllApiesResumes, AllCommentsWithEvaluation, FilteredExperienceComments
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timedelta
from io import BytesIO
import pytz
from dotenv import load_dotenv
load_dotenv()
import os
from logging_config import logger
# Zona horaria de São Paulo/Buenos Aires
tz = pytz.timezone('America/Sao_Paulo')




# - Creando cliente openai
client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    organization="org-cSBk1UaTQMh16D7Xd9wjRUYq"
)

# MODELO FINAL PARA CAPTURA DE EVALUACIÓN DE POSITIVIDAD DE COMENTARIOS

# Captura inicial de sentimientos de la tabla totales:
def get_evaluations_of_all(file_content):
    logger.info("4 - Util get_evaluations_of_all inicializado")
    
    # Leer el archivo Excel desde el contenido en memoria (file_content)
    logger.info("5 - Leyendo excel y agregando ID...")
    df = pd.read_excel(BytesIO(file_content))

    # Agregar columna de ID con un número secuencial para cada comentario
    df['ID'] = range(1, len(df) + 1)

    # Asegurar que la columna de SENTIMIENTO existe
    df['TOPICO'] = ""
    
    # Obtener las APIES únicas
    apies_unicas = df['APIES'].unique()

    logger.info(f"Total de APIES únicas: {len(apies_unicas)}")

    for apies_input in apies_unicas:
        logger.info(f"Procesando APIES {apies_input}...")

        # Filtrar comentarios por APIES y crear un diccionario {ID: Comentario}
        comentarios_filtrados = df[df['APIES'] == apies_input][['ID', 'COMENTARIO']]
        comentarios_dict = dict(zip(comentarios_filtrados['ID'], comentarios_filtrados['COMENTARIO']))

        # Crear el prompt para OpenAI
        prompt = """
            Para cada comentario a continuación, responde SOLO con el formato 'ID-{id}: nombre_del_tópico'. Evalúa el comentario para determinar a cuál de los siguientes 10 tópicos pertenece. No inventes tópicos nuevos, si crees que el comentario no encaja en ningún tópico, clasifícalo como EXPERIENCIA_GENERICA. Aquí están los tópicos:  

            1. Si el comentario menciona temas como trato, actitud,atención general, atención de cortesia, conocimiento del vendedor, y solo cuando sea evidente que se esté hablando de la atención al cliente, probablemente se trate del tópico ATENCION_AL_CLIENTE.  
            2. Si el comentario menciona temas como la calidad de la nafta infinia, la calidad del café, la calidad de las hamburguesas, probablemente se trate del tópico CALIDAD_DE_PRODUCTOS.  
            3. Si el comentario menciona temas como descuentos aplicados, falta de descuentos, descuentos en general, app o aplicaciones generales, uso de tarjetas digitales, aplicaciones web o de celular, lo más probable es que se trate del tópico DIGITAL.  
            4. Si el comentario menciona temas como experiencia positiva, experiencia general, cosas irrelevantes, o es específicamente la palabra 'ok', o contiene las palabras 'bien', 'muy bien', 'mb' sin contexto, y variantes parecidas, o además las evaluaciones con puntajes sin contexto como por ejemplo '10', 'de 10', '10 puntos' o similares, probablemente todos esos ejemplos se traten del tópico EXPERIENCIA_GENERICA.  
            5. Si el comentario menciona temas como imagen de instalaciones,menciona servicios integrales generales como carga de aire o agua caliente, probablemente se trate del tópico IMAGEN_INSTALACIONES_Y_SERVICIOS_GENERALES.  
            6. Si el comentario menciona temas como problemas muy críticos como peligro real, contaminación con combustibles o agresiones físicas, probablemente se trate del tópico PROBLEMATICAS_CRITICAS.  
            7. Si el comentario menciona temas como limpieza de baños, higiene de sanitarios, probablemente se trate del tópico SANITARIOS.  
            8. Si el comentario menciona temas como falta de stock, disponibilidad de productos, probablemente se trate del tópico STOCK_DE_PRODUCTOS.  
            9. Si el comentario menciona temas como demoras en el servicio, rapidez de atención, servicio rápido, atención lenta o desorganizada, probablemente se trate del tópico TIEMPO_DE_ESPERA.  
            10. Si el comentario menciona temas como persepción de precios altos, se aceptan o no tarjetas bancarias, probablemente se trate del tópico VARIABLES_ECONOMICAS_Y_BANCOS.  

            Responde SOLO con el formato 'ID-{id}: nombre_del_tópico'. No utilices otros símbolos, comillas o texto adicional. Respuesta ejemplo:  
            123: EXPERIENCIA_GENERICA  

            Aquí están los comentarios:\n
            """
        for comentario_id, comentario in comentarios_dict.items():
            prompt += f"ID-{comentario_id}: {comentario}\n"

        # Hacer el pedido a OpenAI
        try:
            logger.info(f"Enviando solicitud a OpenAI para APIES {apies_input}...")
            completion = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Eres un analista que clasifica comentarios por tópico."},
                    {"role": "user", "content": prompt}
                ]
            )

            respuesta = completion.choices[0].message.content
            logger.info(f"Respuesta obtenida para APIES {apies_input}")

            # Guardar la respuesta en el log (COMENTADO)
            # log_file.write(f"APIES {apies_input}:\n{respuesta}\n\n")

            # Parsear la respuesta usando expresiones regulares para extraer el ID y el tópico
            matches = re.findall(
                r'ID-(\d+):\s*(ATENCION_AL_CLIENTE|CALIDAD_DE_PRODUCTOS|DIGITAL|EXPERIENCIA_GENERICA|IMAGEN_INSTALACIONES_Y_SERVICIOS_GENERALES|PROBLEMATICAS_CRITICAS|SANITARIOS|STOCK_DE_PRODUCTOS|TIEMPO_DE_ESPERA|VARIABLES_ECONOMICAS_Y_BANCOS)',respuesta)

            # Actualizar la columna 'TOPICO' usando los IDs
            for match in matches:
                comentario_id, topico = match
                df.loc[df['ID'] == int(comentario_id), 'TOPICO'] = topico


        except Exception as e:
            logger.error(f"Error al procesar el APIES {apies_input}: {e}")

    # Guardar el DataFrame actualizado en formato binario (como CSV)
    logger.info("Guardando DataFrame actualizado con sentimiento...")
    output = BytesIO()
    df.to_csv(output, index=False, encoding='utf-8', sep=',', quotechar='"', quoting=1)
    output.seek(0)
    archivo_binario = output.read()

    logger.info("Proceso completado. Guardando en base de datos...")

    # Guardar el archivo en la tabla AllCommentsWithEvaluation
    archivo_anterior = AllCommentsWithEvaluation.query.first()
    if archivo_anterior:
        db.session.delete(archivo_anterior)
        db.session.commit()

    # Crear un nuevo registro y guardar el archivo binario
    archivo_resumido = AllCommentsWithEvaluation(archivo_binario=archivo_binario)
    db.session.add(archivo_resumido)
    db.session.commit()

    logger.info("Archivo guardado exitosamente en la tabla AllCommentsWithEvaluation.")
    return


# Version con iteraciones limitadas y guardado por cada iteracion en db:
def process_missing_topics(comments_df):
    logger.info("Iniciando el proceso de corrección de tópicos...")

    MAX_ITERACIONES = 9  # Límite de iteraciones

    for iteracion in range(MAX_ITERACIONES):
        logger.info(f"Iteración {iteracion + 1}/{MAX_ITERACIONES}: Leyendo archivo CSV...")

        # Leer el archivo directamente desde los bytes
        df = pd.read_csv(BytesIO(comments_df), sep=',')
        logger.info(f"DataFrame cargado con {len(df)} registros.")
        logger.info(f"Columnas del DataFrame: {df.columns}")

        # Filtrar los registros que tienen el campo 'TOPICO' vacío
        df_faltante_topico = df[df['TOPICO'].isna() | (df['TOPICO'].str.strip() == "")]
        logger.info(f"Registros con TOPICO vacío: {len(df_faltante_topico)}")

        if df_faltante_topico.empty:
            logger.info("No se encontraron más registros con TOPICO vacío. Deteniendo el proceso.")
            break

        # Procesar las APIES únicas como siempre
        apies_unicas = df_faltante_topico['APIES'].unique()
        logger.info(f"Total de APIES a procesar: {len(apies_unicas)}")

        for apies_input in apies_unicas:
            logger.info(f"Procesando APIES {apies_input}...")

            # Filtrar comentarios por APIES y crear un diccionario {ID: Comentario}
            comentarios_filtrados = df_faltante_topico[df_faltante_topico['APIES'] == apies_input][['ID', 'COMENTARIO']]
            comentarios_dict = dict(zip(comentarios_filtrados['ID'], comentarios_filtrados['COMENTARIO']))

            # Crear el prompt y pedir respuestas a OpenAI
            prompt = """
            Para cada comentario a continuación, responde SOLO con el formato 'ID-{id}: nombre_del_tópico'. Evalúa el comentario para determinar a cuál de los siguientes 10 tópicos pertenece. No inventes tópicos nuevos, si crees que el comentario no encaja en ningún tópico, clasifícalo como EXPERIENCIA_GENERICA. Aquí están los tópicos:  

            1. Si el comentario menciona temas como trato, actitud,atención general, atención de cortesia, conocimiento del vendedor, y solo cuando sea evidente que se esté hablando de la atención al cliente, probablemente se trate del tópico ATENCION_AL_CLIENTE.  
            2. Si el comentario menciona temas como la calidad de la nafta infinia, la calidad del café, la calidad de las hamburguesas, probablemente se trate del tópico CALIDAD_DE_PRODUCTOS.  
            3. Si el comentario menciona temas como descuentos aplicados, falta de descuentos, descuentos en general, app o aplicaciones generales, uso de tarjetas digitales, aplicaciones web o de celular, lo más probable es que se trate del tópico DIGITAL.  
            4. Si el comentario menciona temas como experiencia positiva, experiencia general, cosas irrelevantes, o es específicamente la palabra 'ok', o contiene las palabras 'bien', 'muy bien', 'mb' sin contexto, y variantes parecidas, o además las evaluaciones con puntajes sin contexto como por ejemplo '10', 'de 10', '10 puntos' o similares, probablemente todos esos ejemplos se traten del tópico EXPERIENCIA_GENERICA.  
            5. Si el comentario menciona temas como imagen de instalaciones,menciona servicios integrales generales como carga de aire o agua caliente, probablemente se trate del tópico IMAGEN_INSTALACIONES_Y_SERVICIOS_GENERALES.  
            6. Si el comentario menciona temas como problemas muy críticos como peligro real, contaminación con combustibles o agresiones físicas, probablemente se trate del tópico PROBLEMATICAS_CRITICAS.  
            7. Si el comentario menciona temas como limpieza de baños, higiene de sanitarios, probablemente se trate del tópico SANITARIOS.  
            8. Si el comentario menciona temas como falta de stock, disponibilidad de productos, probablemente se trate del tópico STOCK_DE_PRODUCTOS.  
            9. Si el comentario menciona temas como demoras en el servicio, rapidez de atención, servicio rápido, atención lenta o desorganizada, probablemente se trate del tópico TIEMPO_DE_ESPERA.  
            10. Si el comentario menciona temas como persepción de precios altos, se aceptan o no tarjetas bancarias, probablemente se trate del tópico VARIABLES_ECONOMICAS_Y_BANCOS.  

            Responde SOLO con el formato 'ID-{id}: nombre_del_tópico'. No utilices otros símbolos, comillas o texto adicional. Respuesta ejemplo:  
            123: EXPERIENCIA_GENERICA  

            Aquí están los comentarios:\n
            """
            for comentario_id, comentario in comentarios_dict.items():
                prompt += f"ID-{comentario_id}: {comentario}\n"

            try:
                logger.info(f"Enviando solicitud a OpenAI para APIES {apies_input}...")
                completion = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "Eres un analista que clasifica comentarios por tópico."},
                        {"role": "user", "content": prompt}
                    ]
                )

                respuesta = completion.choices[0].message.content
                logger.info(f"Respuesta obtenida para APIES {apies_input}")

                # Parsear la respuesta y actualizar
                matches = re.findall(r'ID-(\d+):\s*([\w_]+)', respuesta)

                for match in matches:
                    comentario_id, topico = match
                    df_faltante_topico.loc[df_faltante_topico['ID'] == int(comentario_id), 'TOPICO'] = topico

            except Exception as e:
                logger.error(f"Error al procesar el APIES {apies_input}: {e}")

        # Reemplazar las filas actualizadas en el DataFrame original
        logger.info("Reemplazando filas actualizadas en la tabla original...")
        df.update(df_faltante_topico)

        # Guardar el progreso en la base de datos
        logger.info("Guardando progreso actual en la base de datos...")
        output = BytesIO()
        df.to_csv(output, index=False, encoding='utf-8', sep=',', quotechar='"', quoting=1)
        output.seek(0)
        archivo_binario = output.read()

        # Guardar en la base de datos
        archivo_anterior = FilteredExperienceComments.query.first()
        if archivo_anterior:
            db.session.delete(archivo_anterior)
            db.session.commit()

        nuevo_archivo = FilteredExperienceComments(archivo_binario=archivo_binario)
        db.session.add(nuevo_archivo)
        db.session.commit()
        logger.info("Progreso guardado exitosamente en la base de datos.")

        # Generar un nuevo `comments_df` para la próxima iteración
        comments_df = archivo_binario

    else:
        logger.warning("Se alcanzó el límite máximo de iteraciones. El proceso se detuvo.")
        
    return
