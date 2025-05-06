from database import db
from datetime import datetime


class User(db.Model):
    dni = db.Column(db.Integer, primary_key=True)
    id = db.Column(db.Integer)
    name = db.Column(db.String(50))
    email = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(255))
    url_image = db.Column(db.String(255))
    admin = db.Column(db.Boolean)

class Permitido(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    dni = db.Column(db.Integer, db.ForeignKey('user.id'))


class Reporte(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    report_url = db.Column(db.String(255), nullable=False)
    data = db.Column(db.LargeBinary, nullable=False)
    size = db.Column(db.Float, nullable=False)
    elapsed_time = db.Column(db.String(50), nullable=True)
    title = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow) # revisar si .UTC va o si cambiamos a .utcnow

class TodosLosReportes(db.Model):
    id = db.Column(db.Integer, primary_key=True)  # Primary Key
    report_url = db.Column(db.String(255), unique=True, nullable=False)  # La URL del reporte
    title = db.Column(db.String(255), nullable=False)  # El título del reporte
    size_megabytes = db.Column(db.Float, nullable=True)  # El tamaño del reporte en megabytes, puede ser NULL si no está disponible
    created_at = db.Column(db.DateTime, nullable=True)  # La fecha de creación, puede ser NULL si no está disponible

class Survey(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.LargeBinary, nullable=False)

class TotalComents(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.LargeBinary, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class AllApiesResumes(db.Model):
    __tablename__ = 'archivo_resumido'
    id = db.Column(db.Integer, primary_key=True)
    archivo_binario = db.Column(db.LargeBinary)

class AllCommentsWithEvaluation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    archivo_binario = db.Column(db.LargeBinary)


class FilteredExperienceComments(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    archivo_binario = db.Column(db.LargeBinary)


class DailyCommentsWithEvaluation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    archivo_binario = db.Column(db.LargeBinary)

class FormularioGestor(db.Model):
    __tablename__ = 'formulario_gestor'

    id = db.Column(db.Integer, primary_key=True)
    apies = db.Column(db.String(50), nullable=False)
    curso = db.Column(db.String(100), nullable=False)
    fecha_usuario = db.Column(db.Date, nullable=False)
    gestor = db.Column(db.String(100), nullable=False)
    duracion_horas = db.Column(db.Integer, nullable=False)
    objetivo = db.Column(db.Text, nullable=True)
    contenido_desarrollado = db.Column(db.Text, nullable=True)
    ausentes = db.Column(db.Integer, nullable=False)
    presentes = db.Column(db.Integer, nullable=False)
    resultados_logros = db.Column(db.Text, nullable=True)
    compromiso = db.Column(db.String(20), nullable=True)
    participacion_actividades = db.Column(db.String(20), nullable=True)
    concentracion = db.Column(db.String(20), nullable=True)
    cansancio = db.Column(db.String(20), nullable=True)
    interes_temas = db.Column(db.String(20), nullable=True)
    recomendaciones = db.Column(db.Text, nullable=True)
    otros_aspectos = db.Column(db.Text, nullable=True)
    jornada = db.Column(db.String(20), nullable=False)
    dotacion_real_estacion = db.Column(db.Integer, nullable=True)
    dotacion_en_campus = db.Column(db.Integer, nullable=True)
    dotacion_dni_faltantes = db.Column(db.Text, nullable=True)
    firma_file = db.Column(db.LargeBinary, nullable=True)
    nombre_firma = db.Column(db.String(100), nullable=True)
    email_gestor = db.Column(db.String(120), nullable=False)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def serialize(self):
        return {
            "id": self.id,
            "apies": self.apies,
            "curso": self.curso,
            "fecha_usuario": self.fecha_usuario.isoformat(),
            "gestor": self.gestor,
            "duracion_horas": self.duracion_horas,
            "objetivo": self.objetivo,
            "contenido_desarrollado": self.contenido_desarrollado,
            "ausentes": self.ausentes,
            "presentes": self.presentes,
            "resultados_logros": self.resultados_logros,
            "compromiso": self.compromiso,
            "participacion_actividades": self.participacion_actividades,
            "concentracion": self.concentracion,
            "cansancio": self.cansancio,
            "interes_temas": self.interes_temas,
            "recomendaciones": self.recomendaciones,
            "otros_aspectos": self.otros_aspectos,
            "jornada": self.jornada,
            "dotacion_real_estacion": self.dotacion_real_estacion,
            "dotacion_dni_faltantes": self.dotacion_dni_faltantes,
            "nombre_firma": self.nombre_firma,
            "email_gestor": self.email_gestor,
            "creado_en": self.creado_en.isoformat()
        }