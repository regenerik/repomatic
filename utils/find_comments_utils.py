from openai import OpenAI
from flask import  send_file, make_response, request, jsonify, render_template, current_app, Response 
import re
from models import AllCommentsWithEvaluation,FilteredExperienceComments   # importar tabla "User" de models
from database import db                                          # importa la db desde database.py
from datetime import timedelta, datetime                         # importa tiempo especifico para rendimiento de token válido
from logging_config import logger
import os                                                        # Para datos .env
from dotenv import load_dotenv                                   # Para datos .env
load_dotenv()
import pandas as pd
from io import BytesIO


# - Creando cliente openai
client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    organization="org-cSBk1UaTQMh16D7Xd9wjRUYq"
)


def red_flag_master_util(
    file_content,
    prompt=None,
    sentimientos_aceptados=None,
    topicos_aceptados=None,
    cantidad_minima_caracteres=None
):
    """
    Combina toda la secuencia:
      1) Lee XLSX y aplica Filtros (sentimientos, topicos, min caracteres).
      2) Clasifica con OpenAI (1a pasada).
      3) Guarda CSV intermedio en AllCommentsWithEvaluation.
      4) Lee ese CSV en memoria, rellena 'CLASIFICADO' en bucle (2a pasada).
      5) Filtra 'normal' y guarda 'redflag' en FilteredExperienceComments.
    """

    try:
        logger.info("==== INICIO de red_flag_master_util con parámetros dinámicos ====")

        # ------------------------------------------------------------------
        # 1) Leer el XLSX y aplicar filtros
        # ------------------------------------------------------------------
        df = pd.read_excel(BytesIO(file_content))
        logger.info(f"DataFrame inicial: {len(df)} registros.")

        # Filtro por sentimientos (solo si se recibió la lista, sino no hacemos nada)
        if sentimientos_aceptados is not None:
            df = df[df['SENTIMIENTO'].isin(sentimientos_aceptados)]
            logger.info(f"Filtrado por sentimientos {sentimientos_aceptados}. Quedan {len(df)} registros.")
        else:
            logger.info("No se aplica filtro de sentimientos_aceptados (está en None).")

        # Filtro por tópicos (solo si hay topicos_aceptados y la columna 'TOPICO' existe)
        if topicos_aceptados is not None and 'TOPICO' in df.columns:
            df = df[df['TOPICO'].isin(topicos_aceptados)]
            logger.info(f"Filtrado por tópicos {topicos_aceptados}. Quedan {len(df)} registros.")
        else:
            logger.info("No se aplica filtro de topicos_aceptados (está en None) o 'TOPICO' no existe en DF.")

        # Filtro por cantidad mínima de caracteres
        if cantidad_minima_caracteres is not None:
            df = df[df['COMENTARIO'].str.len() >= cantidad_minima_caracteres]
            logger.info(f"Filtrado por longitud >= {cantidad_minima_caracteres}. Quedan {len(df)} registros.")
        else:
            logger.info("No se aplica filtro por min caracteres (cantidad_minima_caracteres está en None).")

        # ------------------------------------------------------------------
        # 2) Primera pasada: Clasificación
        # ------------------------------------------------------------------
        # Agregar columna ID secuencial + CLASIFICADO vacío
        df['ID'] = range(1, len(df) + 1)
        df['CLASIFICADO'] = ""

        # Prompt por defecto, si no llega uno nuevo
        default_prompt_intro = (
            "Para cada comentario listado a continuación, responde únicamente en el formato 'ID-{id}: redflag' o 'ID-{id}: normal'. "
            "Clasifica un comentario como redflag si detectas alguno de los siguientes escenarios críticos: situaciones peligrosas como accidentes, lesiones de empleados o clientes, intoxicaciones por alimentos o comidas en muy mal estado; "
            "casos de robo de objetos materiales o dinero, hurto o vandalismo en las instalaciones de la empresa; problemas con la infraestructura como techos que se caen, fugas de gas, riesgos de incendio; comentarios donde empleados hablen mal de YPF, recomienden otras gasolineras o desacrediten la empresa ante clientes; "
            "faltas graves de empleados como maltrato exagerado a clientes, negligencia o discriminación; quejas recurrentes sobre falta de limpieza extrema, estaciones cerradas sin aviso o productos de muy mala calidad que dañen la experiencia del cliente; menciones de derrames, contaminación o prácticas que pongan en riesgo el medio ambiente o la comunidad; cualquier indicio de prácticas ilegales como fraude. "
            "Si un comentario no encaja en estas categorías o no implica riesgos significativos para la empresa, clasifícalo como 'normal'. "
            "Si el comentario dice cosas como 'anda todo mal', 'me atendio con mala gana', 'el empleado fue grosero' o parecidos, o no se sabe que está mal explícitamente, clasifícalo como 'normal'. "
            "Cuando veas palabras como 'fraude','estafa' y/o 'afano' en relación a precios y/o puntos clasifica como 'normal'. "
            "Aquí están los comentarios:\n"
        )

        final_prompt_intro = prompt if prompt else default_prompt_intro

        # Iterar por cada APIES
        if 'APIES' in df.columns:
            apies_unicas = df['APIES'].unique()
            logger.info(f"Total de APIES únicas: {len(apies_unicas)}")

            for apies_input in apies_unicas:
                logger.info(f"Clasificando comentarios para APIES {apies_input}...")

                comentarios_filtrados = df[df['APIES'] == apies_input][['ID', 'COMENTARIO']]
                comentarios_dict = dict(zip(comentarios_filtrados['ID'], comentarios_filtrados['COMENTARIO']))

                # Construir prompt completo
                prompt_openai = final_prompt_intro
                for comentario_id, comentario in comentarios_dict.items():
                    prompt_openai += f"ID-{comentario_id}: {comentario}\n"

                try:
                    completion = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": "Eres un analista que clasifica comentarios por gravedad."},
                            {"role": "user", "content": prompt_openai}
                        ]
                    )
                    respuesta = completion.choices[0].message.content
                    matches = re.findall(r'ID-(\d+):\s*(redflag|normal)', respuesta)

                    for match in matches:
                        comentario_id, clasificado = match
                        df.loc[df['ID'] == int(comentario_id), 'CLASIFICADO'] = clasificado

                except Exception as e:
                    logger.error(f"Error al procesar APIES {apies_input}: {e}")
        else:
            logger.warning("No existe columna 'APIES' en el DataFrame. No se hace clasificación segmentada por APIES.")

        # Guardar CSV intermedio en DB (AllCommentsWithEvaluation)
        logger.info("Guardando clasificación intermedia en AllCommentsWithEvaluation.")
        output = BytesIO()
        df.to_csv(output, index=False, encoding='utf-8', sep=',', quotechar='"', quoting=1)
        output.seek(0)
        archivo_binario = output.read()

        archivo_anterior = AllCommentsWithEvaluation.query.first()
        if archivo_anterior:
            db.session.delete(archivo_anterior)
            db.session.commit()

        archivo_resumido = AllCommentsWithEvaluation(archivo_binario=archivo_binario)
        db.session.add(archivo_resumido)
        db.session.commit()
        logger.info("Clasificación intermedia guardada con éxito en AllCommentsWithEvaluation.")

        # ------------------------------------------------------------------
        # 3) Segunda pasada: rellenar CLASIFICADO vacío
        # ------------------------------------------------------------------
        logger.info("Iniciando la corrección de campos vacíos (segunda pasada).")

        df = pd.read_csv(BytesIO(archivo_binario), sep=',')
        logger.info(f"DataFrame recargado con {len(df)} registros para segunda pasada.")

        prev_vacios = None
        while True:
            df_faltante = df[df['CLASIFICADO'].isna() | (df['CLASIFICADO'].str.strip() == "")]
            cant_vacios = len(df_faltante)
            logger.info(f"Registros con CLASIFICADO vacío: {cant_vacios}")

            if cant_vacios == 0:
                logger.info("No hay más registros con CLASIFICADO vacío. Cortamos acá.")
                break

            if prev_vacios == cant_vacios:
                logger.warning("No se reduce la cantidad de vacíos. Evitamos bucle infinito.")
                break
            prev_vacios = cant_vacios

            if 'APIES' in df_faltante.columns:
                apies_unicas_2 = df_faltante['APIES'].unique()
                logger.info(f"APIES pendientes de corrección (segunda pasada): {len(apies_unicas_2)}")

                for apies_input in apies_unicas_2:
                    logger.info(f"Corrigiendo vacíos para APIES {apies_input}.")

                    comentarios_filtrados = df_faltante[df_faltante['APIES'] == apies_input][['ID', 'COMENTARIO']]
                    comentarios_dict = dict(zip(comentarios_filtrados['ID'], comentarios_filtrados['COMENTARIO']))

                    # Mismo prompt final
                    prompt_openai_2da = final_prompt_intro
                    for comentario_id, comentario in comentarios_dict.items():
                        prompt_openai_2da += f"ID-{comentario_id}: {comentario}\n"

                    try:
                        completion = client.chat.completions.create(
                            model="gpt-4o-mini",
                            messages=[
                                {"role": "system", "content": "Eres un analista que clasifica comentarios por gravedad."},
                                {"role": "user", "content": prompt_openai_2da}
                            ]
                        )
                        respuesta = completion.choices[0].message.content
                        matches = re.findall(r'ID-(\d+):\s*(redflag|normal)', respuesta)

                        for match in matches:
                            comentario_id, clasificado = match
                            df.loc[df['ID'] == int(comentario_id), 'CLASIFICADO'] = clasificado

                    except Exception as e:
                        logger.error(f"Error al procesar APIES {apies_input} en segunda pasada: {e}")

            else:
                logger.warning("No existe columna 'APIES' en DF. No se hace clasificación segmentada en segunda pasada.")
                break  # sin 'APIES' no podemos seguir segmentando, rompemos.

        # ------------------------------------------------------------------
        # 4) Filtrar 'normal', guardar solo 'redflag'
        # ------------------------------------------------------------------
        logger.info("Filtrando y dejando únicamente 'redflag' en el DataFrame final.")
        df = df[df['CLASIFICADO'] == 'redflag']

        if df.empty:
            logger.warning("No quedaron registros 'redflag' para guardar en FilteredExperienceComments.")
            return

        logger.info("Guardando DataFrame final en FilteredExperienceComments.")
        output_final = BytesIO()
        df.to_csv(output_final, index=False, encoding='utf-8', sep=',', quotechar='"', quoting=1)
        output_final.seek(0)
        archivo_binario_final = output_final.read()

        archivo_anterior_filt = FilteredExperienceComments.query.first()
        if archivo_anterior_filt:
            db.session.delete(archivo_anterior_filt)
            db.session.commit()

        archivo_resumido_filt = FilteredExperienceComments(archivo_binario=archivo_binario_final)
        db.session.add(archivo_resumido_filt)
        db.session.commit()

        logger.info("Archivo final guardado con éxito en FilteredExperienceComments.")
        logger.info("==== FIN de red_flag_master_util ====")

    except Exception as e:
        logger.error(f"Error en red_flag_master_util: {str(e)}")
