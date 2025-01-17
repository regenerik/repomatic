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

# Corrección de campos vacios en SENTIMIENTO de forma automatica hasta rellenarlos todos con un while:
def process_missing_sentiment(comments_df):
    logger.info("Iniciando el proceso de corrección de sentimientos...")

    flag_vacios = True  # Iniciamos el flag en True para entrar en el ciclo while

    while flag_vacios:
        logger.info("Leyendo archivo CSV...")

        # Leer el archivo directamente desde los bytes
        df = pd.read_csv(BytesIO(comments_df), sep=',')
        
        logger.info(f"DataFrame cargado con {len(df)} registros.")
        logger.info(f"Columnas del DataFrame: {df.columns}")

        # Filtrar los registros que tienen el campo 'SENTIMIENTO' vacío
        df_faltante_sentimiento = df[df['SENTIMIENTO'].isna() | (df['SENTIMIENTO'].str.strip() == "")]
        logger.info(f"Registros con SENTIMIENTO vacío: {len(df_faltante_sentimiento)}")
        
        if df_faltante_sentimiento.empty:
            logger.info("No se encontraron más registros con SENTIMIENTO vacío. Deteniendo el proceso.")
            flag_vacios = False  # No hay más campos vacíos, salimos del while
            break  # Rompemos el ciclo del while
        
        # Obtener las APIES únicas de los registros filtrados
        apies_unicas = df_faltante_sentimiento['APIES'].unique()

        logger.info(f"Total de APIES a procesar: {len(apies_unicas)}")

        for apies_input in apies_unicas:
            logger.info(f"Procesando APIES {apies_input}...")

            # Filtrar comentarios por APIES y crear un diccionario {ID: Comentario}
            comentarios_filtrados = df_faltante_sentimiento[df_faltante_sentimiento['APIES'] == apies_input][['ID', 'COMENTARIO']]
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

                # Parsear la respuesta usando expresiones regulares para extraer el ID y el sentimiento
                matches = re.findall(r'ID-(\d+):\s*(positivo|negativo|invalido)', respuesta)

                # Actualizar la columna 'SENTIMIENTO' en df_faltante_sentimiento usando los IDs
                for match in matches:
                    comentario_id, sentimiento = match
                    df_faltante_sentimiento.loc[df_faltante_sentimiento['ID'] == int(comentario_id), 'SENTIMIENTO'] = sentimiento

            except Exception as e:
                logger.error(f"Error al procesar el APIES {apies_input}: {e}")

        # Reemplazar las filas correspondientes en la tabla original
        logger.info("Reemplazando filas en tabla original...")

        # Verificar si los objetos df y df_faltante_sentimiento son DataFrames
        logger.info(f"Tipo de df: {type(df)}")
        logger.info(f"Tipo de df_faltante_sentimiento: {type(df_faltante_sentimiento)}")

        # Verificar si los DataFrames están vacíos
        logger.info(f"df está vacío: {df.empty}")
        logger.info(f"df_faltante_sentimiento está vacío: {df_faltante_sentimiento.empty}")

        # Verificar el tamaño de los DataFrames antes de seguir
        logger.info(f"df tiene {df.shape[0]} filas y {df.shape[1]} columnas")
        logger.info(f"df_faltante_sentimiento tiene {df_faltante_sentimiento.shape[0]} filas y {df_faltante_sentimiento.shape[1]} columnas")

        # Verificar si hay valores nulos en la columna 'ID'
        if df['ID'].isnull().any() or df_faltante_sentimiento['ID'].isnull().any():
            logger.error("Existen valores nulos en la columna 'ID'. Esto puede causar problemas en el merge.")
            return
        else:
            logger.error("No hay valores nulos en la columna ID")

        # Verificar si hay duplicados en la columna 'ID'
        if df['ID'].duplicated().any() or df_faltante_sentimiento['ID'].duplicated().any():
            logger.error("Existen valores duplicados en la columna 'ID'. Esto puede causar problemas en el merge.")
            return
        else:
            logger.error("No existen duplicados en la columna ID")

        # Asegurarse de que los tipos de la columna ID coincidan
        df['ID'] = df['ID'].astype(int)
        df_faltante_sentimiento['ID'] = df_faltante_sentimiento['ID'].astype(int)
        logger.error("Se supone que hasta acá hicimos coincidir los tipos de la columna ID para ser int en ambos")

        # Probar un merge simple para verificar que el merge funcione
        try:
            # Hacemos un merge, pero solo actualizamos los valores faltantes en 'SENTIMIENTO'
            df_merged = df.merge(
                df_faltante_sentimiento[['ID', 'SENTIMIENTO']],
                on='ID',
                how='left',
                suffixes=('', '_nuevo')
            )

            # Solo reemplazar los valores de SENTIMIENTO que están vacíos
            df_merged['SENTIMIENTO'] = df_merged['SENTIMIENTO'].combine_first(df_merged['SENTIMIENTO_nuevo'])

            # Eliminar la columna de los nuevos sentimientos
            df_merged = df_merged.drop(columns=['SENTIMIENTO_nuevo'])

            logger.info(f"Primeras filas de df_merged:\n{df_merged.head()}")
            logger.info(f"Total de filas en df_merged: {len(df_merged)}")

            logger.info("Filas actualizadas en la tabla original con el merge.")
        
            # Guardar el DataFrame actualizado como un archivo binario para la siguiente iteración
            output = BytesIO()
            df_merged.to_csv(output, index=False, encoding='utf-8', sep=',', quotechar='"', quoting=1)
            output.seek(0)
            comments_df = output.read()  # Convertirlo nuevamente en binario para la próxima iteración


        except Exception as e:
            logger.error(f"Error durante el merge: {e}")
            return
    

    
    # Guardar el DataFrame actualizado en la base de datos cuando no haya más vacíos
    logger.info("Guardando DataFrame actualizado en la tabla FilteredExperienceComments...")
    output = BytesIO()
    df_merged.to_csv(output, index=False, encoding='utf-8', sep=',', quotechar='"', quoting=1)
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

# Corrección de los comentarios negativos para mejorarlos ( pero anexado con el de invalidos en conjutno ):
def process_negative_comments(file_content):
    logger.info("Iniciando el proceso de reevaluación de sentimientos negativos...")

    # Leer el archivo desde los bytes recibidos
    df = pd.read_csv(BytesIO(file_content))
    logger.info(f"DataFrame cargado con {len(df)} registros.")
    
    # Filtrar comentarios con sentimiento negativo
    df_negativos = df[df['SENTIMIENTO'] == 'negativo']

    # Cantidad total de registros de la tabla de negativos
    total_negativos = len(df_negativos)
    logger.info(f"Total de registros en la tabla de comentarios negativos: {total_negativos}")

    # Crear el archivo paralelo con todos los comentarios negativos
    output_negative_comments = BytesIO()
    df_negativos.to_excel(output_negative_comments, index=False)
    output_negative_comments.seek(0)
    
    # Obtener las APIES únicas de los comentarios negativos
    apies_unicas = df_negativos['APIES'].unique()
    logger.info(f"Total de APIES a procesar: {len(apies_unicas)}")

    # Contador para llevar el seguimiento de actualizaciones
    actualizaciones_realizadas = 0

    for apies_input in apies_unicas:
        logger.info(f"Procesando APIES {apies_input}...")

        # Filtrar comentarios de la APIES actual y crear un diccionario {ID: Comentario}
        comentarios_filtrados = df_negativos[df_negativos['APIES'] == apies_input][['ID', 'COMENTARIO']]
        comentarios_dict = dict(zip(comentarios_filtrados['ID'], comentarios_filtrados['COMENTARIO']))

        # Crear el prompt para OpenAI
        prompt = "Para cada comentario a continuación, responde SOLO con el formato 'ID-{id}: positivo', 'ID-{id}: negativo' o 'ID-{id}: invalido'.Si el comentario solamente tiene la palabra 'no', '0' o 'ne', responde 'invalido'. Si el comentario menciona a 'milei' o 'privaticen', responde 'invalido'. Si el comentario no es claro o no tiene un sentimiento definido, responde 'invalido'.Si el comentario contiene aluciones a positividad como ':)','muy bueno','muy bien',u otros emojis positivos o comentarios que tengan algun tipo de aprovación, serán clasificados como 'positivo'.Necesitamos evitar a toda costa falsos negativos. Aquí están los comentarios:\n"
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

            # Parsear la respuesta para extraer el ID y el sentimiento
            matches = re.findall(r'ID-(\d+):\s*(positivo|negativo|invalido)', respuesta)

            # Actualizar la columna 'SENTIMIENTO' en df_negativos usando los IDs
            for comentario_id, sentimiento in matches:
                df_negativos.loc[df_negativos['ID'] == int(comentario_id), 'SENTIMIENTO'] = sentimiento
                actualizaciones_realizadas += 1  # Incrementamos el contador de actualizaciones

        except Exception as e:
            logger.error(f"Error al procesar el APIES {apies_input}: {e}")

    # Logueamos la cantidad total de actualizaciones realizadas
    logger.info(f"Total de actualizaciones realizadas en los sentimientos: {actualizaciones_realizadas}, de el total de negativos:{total_negativos}")

    # Reemplazar las filas correspondientes en la tabla original
    logger.info("Reemplazando filas en la tabla original con los resultados reevaluados...")
    df.update(df_negativos[['ID', 'SENTIMIENTO']])

    # Llamar a la función hermana para procesar los "inválidos"
    df = process_invalid_comments(df)

    # Guardar el DataFrame actualizado en la base de datos o como archivo binario
    logger.info("Guardando DataFrame actualizado en la tabla FilteredExperienceComments...")
    output = BytesIO()
    df.to_csv(output, index=False)
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

    logger.info("Archivo actualizado guardado exitosamente en la tabla FilteredExperienceComments.")
    return

# Corrección de los comentarios invalidos para mejorarlos ( es parte del flow del util anterior )
def process_invalid_comments(df):
    logger.info("Iniciando el proceso de corrección de comentarios inválidos...")

    # Filtrar comentarios con sentimiento inválido
    df_invalidos = df[df['SENTIMIENTO'] == 'invalido']

    # Cantidad total de registros inválidos
    total_invalidos = len(df_invalidos)
    logger.info(f"Total de registros en la tabla de comentarios inválidos: {total_invalidos}")

    # Obtener las APIES únicas de los comentarios inválidos
    apies_unicas = df_invalidos['APIES'].unique()
    logger.info(f"Total de APIES a procesar para comentarios inválidos: {len(apies_unicas)}")

    # Contador para llevar el seguimiento de actualizaciones
    actualizaciones_realizadas = 0

    for apies_input in apies_unicas:
        logger.info(f"Procesando APIES {apies_input} para comentarios inválidos...")

        # Filtrar comentarios de la APIES actual y crear un diccionario {ID: Comentario}
        comentarios_filtrados = df_invalidos[df_invalidos['APIES'] == apies_input][['ID', 'COMENTARIO']]
        comentarios_dict = dict(zip(comentarios_filtrados['ID'], comentarios_filtrados['COMENTARIO']))

        # Crear el prompt para OpenAI
        prompt = "Para cada comentario a continuación, responde SOLO con el formato 'ID-{id}: positivo', 'ID-{id}: negativo' o 'ID-{id}: invalido'. Si el comentario no es claro o no tiene un sentimiento definido, responde 'invalido'.Si el comentario contiene aluciones a positividad como ':)','muy bueno','completo','lujo','todo bien','excelente','muy bien','mb' u otros emojis positivos o comentarios que tengan algun tipo de aprovación, serán clasificados como 'positivo'.El comentario podria encontrarse también despues de uno o dos saltos de linea, revisar bien el texto. Necesitamos evitar a toda costa falsos negativos. Aquí están los comentarios:\n"
        for comentario_id, comentario in comentarios_dict.items():
            prompt += f"ID-{comentario_id}: {comentario}\n"

        # Hacer el pedido a OpenAI
        try:
            logger.info(f"Enviando solicitud a OpenAI para APIES {apies_input} (corrección de inválidos)...")
            completion = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Eres un analista que clasifica comentarios por sentimiento."},
                    {"role": "user", "content": prompt}
                ]
            )

            respuesta = completion.choices[0].message.content
            logger.info(f"Respuesta obtenida para APIES {apies_input} (corrección de inválidos)")

            # Parsear la respuesta para extraer el ID y el sentimiento
            matches = re.findall(r'ID-(\d+):\s*(positivo|negativo|invalido)', respuesta)

            # Actualizar la columna 'SENTIMIENTO' en df_invalidos usando los IDs
            for comentario_id, sentimiento in matches:
                df_invalidos.loc[df_invalidos['ID'] == int(comentario_id), 'SENTIMIENTO'] = sentimiento
                actualizaciones_realizadas += 1  # Incrementamos el contador de actualizaciones

        except Exception as e:
            logger.error(f"Error al procesar el APIES {apies_input} (corrección de inválidos): {e}")

    # Logueamos la cantidad total de actualizaciones realizadas
    logger.info(f"Total de actualizaciones realizadas en los sentimientos inválidos: {actualizaciones_realizadas}, de el total de inválidos: {total_invalidos}")

    # Reemplazar las filas correspondientes en el DataFrame original
    df.update(df_invalidos[['ID', 'SENTIMIENTO']])

    logger.info("Corrección de comentarios inválidos finalizada.")
    return df







# PROXIMAMENTE UTIL PARA COMPARACION DE COMENTARIOS HUMANOS VS OPENAI ( FALTA NORMALIZAR LOS POSITIVOS ): 

# Modificar la función para aceptar DataFrames directamente
def comparar_comentarios(humanos_df: pd.DataFrame, openai_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compara comentarios entre dos DataFrames (humanos y openai) y genera una tabla de resultados.

    Argumentos:
        humanos_df (pd.DataFrame): DataFrame con los comentarios de humanos.
        openai_df (pd.DataFrame): DataFrame con los comentarios de OpenAI.

    Retorna:
        pd.DataFrame: DataFrame con columnas ['COMENTARIO', 'HUMANO', 'OPENAI'] mostrando los comentarios, la
                      clasificación manual y la clasificación de OpenAI.
    """
    
    # Renombrar columnas para facilidad de uso
    humanos_df = humanos_df.rename(columns={
        'Comentario para re-clasificar (Transcribí el comentario que debemos analizar nuevamente)': 'Comentario',
        'Nueva clasificación del comentario (Colocá la clasificación que consideras que debería ser la correcta)': 'Humano'
    })
    openai_df = openai_df.rename(columns={'COMENTARIO': 'Comentario', 'SENTIMIENTO': 'OpenAI'})
    
    # Normalizar comentarios y clasificaciones para evitar errores de formato y diferencias de mayúsculas/minúsculas
    humanos_df['Comentario'] = humanos_df['Comentario'].astype(str).str.strip().str.lower()
    openai_df['Comentario'] = openai_df['Comentario'].astype(str).str.strip().str.lower()

    # Eliminar duplicados en la columna 'Comentario' para evitar combinaciones innecesarias
    humanos_df = humanos_df.drop_duplicates(subset=['Comentario'])
    openai_df = openai_df.drop_duplicates(subset=['Comentario'])
    
    # Hacer un merge entre ambos DataFrames para obtener los comentarios que coinciden y sus clasificaciones
    resultado_df = pd.merge(humanos_df[['Comentario', 'Humano']], openai_df[['Comentario', 'OpenAI']], on='Comentario', how='inner')
    
    return resultado_df
