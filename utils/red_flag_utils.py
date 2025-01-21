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


# Captura inicial de CLASIFICADO de la tabla totales:
def red_flag_finder(file_content):
    logger.info("4 - Util red_flag_finder inicializado")
    
    # Leer el archivo Excel desde el contenido en memoria (file_content)
    logger.info("4.1 - Leyendo archivo Excel y filtrando registros con sentimiento negativo...")
    df = pd.read_excel(BytesIO(file_content))
    
    # Filtrar registros eliminando aquellos donde el campo SENTIMIENTO es positivo
    df = df[df['SENTIMIENTO'] != 'positivo']

    # Filtrar registros eliminando aquellos donde el campo SENTIMIENTO es invalido
    df = df[df['SENTIMIENTO'] != 'inválido']

    # Filtrar registros eliminando aquellos donde el campo COMENTARIO tenga menos de 60 caracteres
    df = df[df['COMENTARIO'].str.len() >= 100]

    # Continuar el flujo utilizando el DataFrame filtrado
    logger.info("4.2 - Continuando con registros filtrados...")

    # Agregar columna de ID con un número secuencial para cada comentario
    logger.info("5 - Agregando ID...")
    df['ID'] = range(1, len(df) + 1)

    # Asegurar que la columna de CLASIFICADO existe
    df['CLASIFICADO'] = ""
    
    # Obtener las APIES únicas
    apies_unicas = df['APIES'].unique()

    logger.info(f"Total de APIES únicas: {len(apies_unicas)}")

    for apies_input in apies_unicas:
        logger.info(f"Procesando APIES {apies_input}...")

        # Filtrar comentarios por APIES y crear un diccionario {ID: Comentario}
        comentarios_filtrados = df[df['APIES'] == apies_input][['ID', 'COMENTARIO']]
        comentarios_dict = dict(zip(comentarios_filtrados['ID'], comentarios_filtrados['COMENTARIO']))

        # Crear el prompt para OpenAI
        prompt = "Para cada comentario listado a continuación, responde únicamente en el formato 'ID-{id}: redflag' o 'ID-{id}: normal'. Clasifica un comentario como redflag si detectas alguno de los siguientes escenarios críticos: situaciones peligrosas como accidentes, lesiones de empleados o clientes, intoxicaciones por alimentos o comidas en muy mal estado; casos de robo de objetos materiales o dinero, hurto o vandalismo en las instalaciones de la empresa; problemas con la infraestructura como techos que se caen, fugas de gas, riesgos de incendio; comentarios donde empleados hablen mal de YPF, recomienden otras gasolineras o desacrediten la empresa ante clientes; faltas graves de empleados como maltrato exagerado a clientes, negligencia o discriminación; quejas recurrentes sobre falta de limpieza extrema, estaciones cerradas sin aviso o productos de muy mala calidad que dañen la experiencia del cliente; menciones de derrames, contaminación o prácticas que pongan en riesgo el medio ambiente o la comunidad; cualquier indicio de prácticas ilegales como fraude. Si un comentario no encaja en estas categorías o no implica riesgos significativos para la empresa, clasifícalo como 'normal'.Si el comentario dice cosas como 'anda todo mal', 'me atendio con mala gana', 'el empleado fue grosero' o parecidos, o no se sabe que es lo que está mal explicitamente, clasifícalo como 'normal'.Cuando veas palabras como 'fraude','estafa' y/o 'afano' en realación a precios y o puntos clasifica como 'normal'. Aquí están los comentarios:\n"
        for comentario_id, comentario in comentarios_dict.items():
            prompt += f"ID-{comentario_id}: {comentario}\n"

        # Hacer el pedido a OpenAI
        try:
            logger.info(f"Enviando solicitud a OpenAI para APIES {apies_input}...")
            completion = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Eres un analista que clasifica comentarios por gravedad, reconociendo red flags o comentarios comunes."},
                    {"role": "user", "content": prompt}
                ]
            )

            respuesta = completion.choices[0].message.content
            logger.info(f"Respuesta obtenida para APIES {apies_input}")

            # Guardar la respuesta en el log (COMENTADO)
            # log_file.write(f"APIES {apies_input}:\n{respuesta}\n\n")

            # Parsear la respuesta usando expresiones regulares para extraer el ID y el clasificado
            matches = re.findall(r'ID-(\d+):\s*(redflag|normal)', respuesta)

            # Actualizar la columna 'CLASIFICADO' usando los IDs
            for match in matches:
                comentario_id, clasificado = match
                df.loc[df['ID'] == int(comentario_id), 'CLASIFICADO'] = clasificado

        except Exception as e:
            logger.error(f"Error al procesar el APIES {apies_input}: {e}")



    # Guardar el DataFrame actualizado en formato binario (como CSV)
    logger.info("Guardando DataFrame actualizado con clasificado...")
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

# Corrección de campos vacíos en CLASIFICADO de forma automática
def process_missing_fields(comments_df):
    logger.info("Iniciando el proceso de corrección de CLASIFICADO...")

    # Leer el archivo directamente desde los bytes
    df = pd.read_csv(BytesIO(comments_df), sep=',')
    logger.info(f"DataFrame cargado con {len(df)} registros.")
    logger.info(f"Columnas del DataFrame: {df.columns}")

    # Inicializar variables
    prev_vacios = None  # Seguimiento del número de registros vacíos

    while True:
        # Filtrar los registros que tienen el campo 'CLASIFICADO' vacío
        df_faltante_clasificado = df[df['CLASIFICADO'].isna() | (df['CLASIFICADO'].str.strip() == "")]
        logger.info(f"Registros con CLASIFICADO vacío: {len(df_faltante_clasificado)}")

        # Detectar si los vacíos no están disminuyendo
        if prev_vacios == len(df_faltante_clasificado):
            logger.warning("Los registros con CLASIFICADO vacío no están disminuyendo. Saliendo del bucle para evitar un ciclo infinito.")
            break
        prev_vacios = len(df_faltante_clasificado)

        if df_faltante_clasificado.empty:
            logger.info("No se encontraron más registros con CLASIFICADO vacío. Deteniendo el proceso.")
            break

        # Obtener las APIES únicas de los registros filtrados
        apies_unicas = df_faltante_clasificado['APIES'].unique()
        logger.info(f"Total de APIES a procesar: {len(apies_unicas)}")

        for apies_input in apies_unicas:
            logger.info(f"Procesando APIES {apies_input}...")

            # Filtrar comentarios por APIES y crear un diccionario {ID: Comentario}
            comentarios_filtrados = df_faltante_clasificado[df_faltante_clasificado['APIES'] == apies_input][['ID', 'COMENTARIO']]
            comentarios_dict = dict(zip(comentarios_filtrados['ID'], comentarios_filtrados['COMENTARIO']))

            # Crear el prompt para OpenAI
            prompt = "Para cada comentario listado a continuación, responde únicamente en el formato 'ID-{id}: redflag' o 'ID-{id}: normal'. Clasifica un comentario como redflag si detectas alguno de los siguientes escenarios críticos: situaciones peligrosas como accidentes, lesiones de empleados o clientes, intoxicaciones por alimentos o comidas en muy mal estado; casos de robo de objetos materiales o dinero, hurto o vandalismo en las instalaciones de la empresa; problemas con la infraestructura como techos que se caen, fugas de gas, riesgos de incendio; comentarios donde empleados hablen mal de YPF, recomienden otras gasolineras o desacrediten la empresa ante clientes; faltas graves de empleados como maltrato exagerado a clientes, negligencia o discriminación; quejas recurrentes sobre falta de limpieza extrema, estaciones cerradas sin aviso o productos de muy mala calidad que dañen la experiencia del cliente; menciones de derrames, contaminación o prácticas que pongan en riesgo el medio ambiente o la comunidad; cualquier indicio de prácticas ilegales como fraude. Aquí están los comentarios:\n"
            for comentario_id, comentario in comentarios_dict.items():
                prompt += f"ID-{comentario_id}: {comentario}\n"

            # Hacer el pedido a OpenAI
            try:
                logger.info(f"Enviando solicitud a OpenAI para APIES {apies_input}...")
                completion = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "Eres un analista que clasifica comentarios encontrando según su gravedad."},
                        {"role": "user", "content": prompt}
                    ]
                )

                respuesta = completion.choices[0].message.content
                logger.info(f"Respuesta obtenida para APIES {apies_input}")

                # Parsear la respuesta usando expresiones regulares para extraer el ID y el clasificado
                matches = re.findall(r'ID-(\d+):\s*(redflag|normal)', respuesta)

                # Actualizar la columna 'CLASIFICADO' en df_faltante_clasificado usando los IDs
                for match in matches:
                    comentario_id, clasificado = match
                    df.loc[df['ID'] == int(comentario_id), 'CLASIFICADO'] = clasificado

            except Exception as e:
                logger.error(f"Error al procesar el APIES {apies_input}: {e}")

    # Validar el DataFrame final antes de guardar
    if df.empty:
        logger.error("El DataFrame final está vacío. No se puede guardar.")
        return

    # Filtrar los registros para eliminar aquellos donde CLASIFICADO sea "normal"
    logger.info("Filtrando registros para dejar únicamente los redflags...")
    df = df[df['CLASIFICADO'] == 'redflag']

    # Validar nuevamente después del filtrado
    if df.empty:
        logger.warning("Después del filtrado, el DataFrame está vacío. No hay redflags para guardar.")
        return
    else:
        logger.info(f"Cantidad de registros después del filtrado: {len(df)}")

    # Guardar el DataFrame actualizado en la base de datos
    logger.info("Guardando DataFrame actualizado en la tabla FilteredExperienceComments...")
    output = BytesIO()
    df.to_csv(output, index=False, encoding='utf-8', sep=',', quotechar='"', quoting=1)
    output.seek(0)
    archivo_binario = output.read()

    # Eliminar cualquier registro anterior en la tabla FilteredExperienceComments
    archivo_anterior = FilteredExperienceComments.query.first()
    if archivo_anterior:
        db.session.delete(archivo_anterior)
        db.session.commit()

    # Crear un nuevo registro y guardar el archivo binario
    archivo_resumido = FilteredExperienceComments(archivo_binario=archivo_binario)
    db.session.add(archivo_resumido)
    db.session.commit()

    logger.info("Archivo guardado exitosamente en la tabla FilteredExperienceComments.")

    return











# ESTA VERSION FUNCIONA SOLO CUANDO RECIBE CAMPOS VACIOS:
# Corrección de campos vacios en CLASIFICADO de forma automatica hasta rellenarlos todos con un while:
# def process_missing_fields(comments_df):
#     logger.info("Iniciando el proceso de corrección de CLASIFICADO...")

#     flag_vacios = True  # Iniciamos el flag en True para entrar en el ciclo while

#     while flag_vacios:
#         logger.info("Leyendo archivo CSV...")

#         # Leer el archivo directamente desde los bytes
#         df = pd.read_csv(BytesIO(comments_df), sep=',')
        
#         logger.info(f"DataFrame cargado con {len(df)} registros.")
#         logger.info(f"Columnas del DataFrame: {df.columns}")

#         # Filtrar los registros que tienen el campo 'CLASIFICADO' vacío
#         df_faltante_clasificado = df[df['CLASIFICADO'].isna() | (df['CLASIFICADO'].str.strip() == "")]
#         logger.info(f"Registros con CLASIFICADO vacío: {len(df_faltante_clasificado)}")
        
#         if df_faltante_clasificado.empty:
#             logger.info("No se encontraron más registros con CLASIFICADO vacío. Deteniendo el proceso.")
#             flag_vacios = False  # No hay más campos vacíos, salimos del while
#             break  # Rompemos el ciclo del while
        
#         # Obtener las APIES únicas de los registros filtrados
#         apies_unicas = df_faltante_clasificado['APIES'].unique()

#         logger.info(f"Total de APIES a procesar: {len(apies_unicas)}")

#         for apies_input in apies_unicas:
#             logger.info(f"Procesando APIES {apies_input}...")

#             # Filtrar comentarios por APIES y crear un diccionario {ID: Comentario}
#             comentarios_filtrados = df_faltante_clasificado[df_faltante_clasificado['APIES'] == apies_input][['ID', 'COMENTARIO']]
#             comentarios_dict = dict(zip(comentarios_filtrados['ID'], comentarios_filtrados['COMENTARIO']))

#             # Crear el prompt para OpenAI
#             prompt = "Para cada comentario listado a continuación, responde únicamente en el formato 'ID-{id}: redflag' o 'ID-{id}: normal'. Clasifica un comentario como redflag si detectas alguno de los siguientes escenarios críticos: situaciones peligrosas como accidentes, lesiones de empleados o clientes, intoxicaciones por alimentos o comidas en muy mal estado; casos de robo de objetos materiales o dinero, hurto o vandalismo en las instalaciones de la empresa; problemas con la infraestructura como techos que se caen, fugas de gas, riesgos de incendio; comentarios donde empleados hablen mal de YPF, recomienden otras gasolineras o desacrediten la empresa ante clientes; faltas graves de empleados como maltrato exagerado a clientes, negligencia o discriminación; quejas recurrentes sobre falta de limpieza extrema, estaciones cerradas sin aviso o productos de muy mala calidad que dañen la experiencia del cliente; menciones de derrames, contaminación o prácticas que pongan en riesgo el medio ambiente o la comunidad; cualquier indicio de prácticas ilegales como fraude. Si un comentario no encaja en estas categorías o no implica riesgos significativos para la empresa, clasifícalo como 'normal'.Si el comentario dice cosas como 'anda todo mal', 'me atendio con mala gana', 'el empleado fue grosero' o parecidos, o no se sabe que es lo que está mal explicitamente, clasifícalo como 'normal'.Cuando veas palabras como 'fraude','estafa' y/o 'afano' en realación a precios y o puntos clasifica como 'normal'. Aquí están los comentarios:\n"
#             for comentario_id, comentario in comentarios_dict.items():
#                 prompt += f"ID-{comentario_id}: {comentario}\n"

#             # Hacer el pedido a OpenAI
#             try:
#                 logger.info(f"Enviando solicitud a OpenAI para APIES {apies_input}...")
#                 completion = client.chat.completions.create(
#                     model="gpt-4o-mini",
#                     messages=[
#                         {"role": "system", "content": "Eres un analista que clasifica comentarios encontrando según su gravedad."},
#                         {"role": "user", "content": prompt}
#                     ]
#                 )

#                 respuesta = completion.choices[0].message.content
#                 logger.info(f"Respuesta obtenida para APIES {apies_input}")

#                 # Parsear la respuesta usando expresiones regulares para extraer el ID y el clasificado
#                 matches = re.findall(r'ID-(\d+):\s*(redflag|normal)', respuesta)

#                 # Actualizar la columna 'CLASIFICADO' en df_faltante_clasificado usando los IDs
#                 for match in matches:
#                     comentario_id, clasificado = match
#                     df_faltante_clasificado.loc[df_faltante_clasificado['ID'] == int(comentario_id), 'CLASIFICADO'] = clasificado

#             except Exception as e:
#                 logger.error(f"Error al procesar el APIES {apies_input}: {e}")

#         # Reemplazar las filas correspondientes en la tabla original
#         logger.info("Reemplazando filas en tabla original...")

#         # Verificar si los objetos df y df_faltante_clasificado son DataFrames
#         logger.info(f"Tipo de df: {type(df)}")
#         logger.info(f"Tipo de df_faltante_clasificado: {type(df_faltante_clasificado)}")

#         # Verificar si los DataFrames están vacíos
#         logger.info(f"df está vacío: {df.empty}")
#         logger.info(f"df_faltante_clasificado está vacío: {df_faltante_clasificado.empty}")

#         # Verificar el tamaño de los DataFrames antes de seguir
#         logger.info(f"df tiene {df.shape[0]} filas y {df.shape[1]} columnas")
#         logger.info(f"df_faltante_clasificado tiene {df_faltante_clasificado.shape[0]} filas y {df_faltante_clasificado.shape[1]} columnas")

#         # Verificar si hay valores nulos en la columna 'ID'
#         if df['ID'].isnull().any() or df_faltante_clasificado['ID'].isnull().any():
#             logger.error("Existen valores nulos en la columna 'ID'. Esto puede causar problemas en el merge.")
#             return
#         else:
#             logger.error("No hay valores nulos en la columna ID")

#         # Verificar si hay duplicados en la columna 'ID'
#         if df['ID'].duplicated().any() or df_faltante_clasificado['ID'].duplicated().any():
#             logger.error("Existen valores duplicados en la columna 'ID'. Esto puede causar problemas en el merge.")
#             return
#         else:
#             logger.error("No existen duplicados en la columna ID")

#         # Asegurarse de que los tipos de la columna ID coincidan
#         df['ID'] = df['ID'].astype(int)
#         df_faltante_clasificado['ID'] = df_faltante_clasificado['ID'].astype(int)
#         logger.error("Se supone que hasta acá hicimos coincidir los tipos de la columna ID para ser int en ambos")

#         # Probar un merge simple para verificar que el merge funcione
#         try:
#             # Hacemos un merge, pero solo actualizamos los valores faltantes en 'CLASIFICADO'
#             df_merged = df.merge(
#                 df_faltante_clasificado[['ID', 'CLASIFICADO']],
#                 on='ID',
#                 how='left',
#                 suffixes=('', '_nuevo')
#             )

#             # Solo reemplazar los valores de CLASIFICADO que están vacíos
#             df_merged['CLASIFICADO'] = df_merged['CLASIFICADO'].combine_first(df_merged['CLASIFICADO_nuevo'])

#             # Eliminar la columna de los nuevos CLASIFICADOS
#             df_merged = df_merged.drop(columns=['CLASIFICADO_nuevo'])

#             logger.info(f"Primeras filas de df_merged:\n{df_merged.head()}")
#             logger.info(f"Total de filas en df_merged: {len(df_merged)}")

#             logger.info("Filas actualizadas en la tabla original con el merge.")
        
#             # Guardar el DataFrame actualizado como un archivo binario para la siguiente iteración
#             output = BytesIO()
#             df_merged.to_csv(output, index=False, encoding='utf-8', sep=',', quotechar='"', quoting=1)
#             output.seek(0)
#             comments_df = output.read()  # Convertirlo nuevamente en binario para la próxima iteración


#         except Exception as e:
#             logger.error(f"Error durante el merge: {e}")
#             return
        


#     # Guardar el DataFrame actualizado en la base de datos cuando no haya más vacíos
#     logger.info("Guardando DataFrame filtrado en la tabla FilteredExperienceComments...")
#     output = BytesIO()
#     df_merged.to_csv(output, index=False, encoding='utf-8', sep=',', quotechar='"', quoting=1)
#     output.seek(0)
#     archivo_binario = output.read()


#     # Eliminar cualquier registro anterior en la tabla FilteredExperienceComments
#     archivo_anterior = FilteredExperienceComments.query.first()
#     if archivo_anterior:
#         db.session.delete(archivo_anterior)
#         db.session.commit()

#     # Crear un nuevo registro y guardar el archivo binario
#     archivo_resumido = FilteredExperienceComments(archivo_binario=archivo_binario)
#     db.session.add(archivo_resumido)
#     db.session.commit()

#     logger.info("Archivo guardado exitosamente en la tabla FilteredExperienceComments.")

#     return