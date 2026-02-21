"""
Base de datos con SQLAlchemy.

Soporta SQLite local (desarrollo) y PostgreSQL (producción/Fly.io).
Incluye modelos User y Project con todas las relaciones.
"""

import os
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy import create_engine, Column, String, DateTime, ForeignKey, JSON, Integer
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session
from sqlalchemy.pool import StaticPool


# URL de la base de datos - Fly.io provee DATABASE_URL en producción
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "sqlite:///./data/explainer.db"  # Default local
)

# Configuración del engine según el tipo de base de datos
if DATABASE_URL.startswith("sqlite"):
    # SQLite - configuración para desarrollo local
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False
    )
else:
    # PostgreSQL - configuración para producción
    engine = create_engine(
        DATABASE_URL,
        pool_size=5,
        max_overflow=10,
        echo=False
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# =============================================================================
# MODELOS
# =============================================================================

class User(Base):
    """Modelo de usuario con autenticación y API key encriptada."""
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)

    # API key de Gemini encriptada (puede ser NULL si el usuario no la ha guardado)
    gemini_api_key_encrypted = Column(String, nullable=True)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    projects = relationship("Project", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email})>"


class Project(Base):
    """Modelo de proyecto - reemplaza el JSON file storage anterior."""
    __tablename__ = "projects"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)

    # Información básica
    name = Column(String, nullable=False)
    description = Column(String, nullable=False)
    pdf_filename = Column(String, nullable=False)

    # Gemini File API
    file_uri = Column(String, nullable=True)

    # Estado del procesamiento
    status = Column(String, default="pending")  # pending, uploading, segmenting, processing, completed, error

    # Datos del procesamiento (JSON)
    segmentation = Column(JSON, nullable=True)  # Resultado del segmentador
    partes_contenido = Column(JSON, default=dict)  # Resultados de los agentes
    usage = Column(JSON, default=dict)  # Costos y tokens
    error_message = Column(String, nullable=True)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    user = relationship("User", back_populates="projects")

    def __repr__(self):
        return f"<Project(id={self.id}, name={self.name}, status={self.status})>"

    def to_dict(self) -> Dict[str, Any]:
        """Convierte el proyecto a dict (compatible con el frontend existente)."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "description": self.description,
            "pdf_filename": self.pdf_filename,
            "file_uri": self.file_uri,
            "status": self.status,
            "segmentation": self.segmentation,
            "partes_contenido": self.partes_contenido,
            "usage": self.usage,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# =============================================================================
# FUNCIONES DE UTILIDAD
# =============================================================================

def init_db():
    """Inicializa la base de datos creando todas las tablas."""
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    """Obtiene una sesión de base de datos."""
    db = SessionLocal()
    try:
        return db
    except Exception:
        db.close()
        raise


def close_db(db: Session):
    """Cierra una sesión de base de datos."""
    db.close()


# =============================================================================
# CRUD USUARIOS
# =============================================================================

def create_user(db: Session, email: str, password_hash: str) -> User:
    """Crea un nuevo usuario."""
    user = User(email=email, password_hash=password_hash)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    """Busca un usuario por email."""
    return db.query(User).filter(User.email == email).first()


def get_user_by_id(db: Session, user_id: str) -> Optional[User]:
    """Busca un usuario por ID."""
    return db.query(User).filter(User.id == user_id).first()


def update_user_api_key(db: Session, user_id: str, encrypted_api_key: Optional[str]) -> User:
    """Actualiza la API key encriptada de un usuario."""
    user = get_user_by_id(db, user_id)
    if user:
        user.gemini_api_key_encrypted = encrypted_api_key
        user.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(user)
    return user


# =============================================================================
# CRUD PROYECTOS
# =============================================================================

def create_project(
    db: Session,
    user_id: str,
    name: str,
    description: str,
    pdf_filename: str
) -> Project:
    """Crea un nuevo proyecto."""
    project = Project(
        user_id=user_id,
        name=name,
        description=description,
        pdf_filename=pdf_filename,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def get_project(db: Session, project_id: str, user_id: Optional[str] = None) -> Optional[Project]:
    """
    Busca un proyecto por ID.
    Si user_id se proporciona, verifica que el proyecto pertenezca a ese usuario.
    """
    query = db.query(Project).filter(Project.id == project_id)
    if user_id:
        query = query.filter(Project.user_id == user_id)
    return query.first()


def list_projects(db: Session, user_id: str) -> List[Project]:
    """Lista todos los proyectos de un usuario, ordenados por fecha descendente."""
    return (
        db.query(Project)
        .filter(Project.user_id == user_id)
        .order_by(Project.created_at.desc())
        .all()
    )


def update_project(db: Session, project_id: str, user_id: str, updates: Dict[str, Any]) -> Optional[Project]:
    """Actualiza un proyecto existente."""
    project = get_project(db, project_id, user_id)
    if not project:
        return None

    for key, value in updates.items():
        if hasattr(project, key):
            setattr(project, key, value)

    project.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(project)
    return project


def delete_project(db: Session, project_id: str, user_id: str) -> bool:
    """Elimina un proyecto. Retorna True si se eliminó, False si no existía."""
    project = get_project(db, project_id, user_id)
    if not project:
        return False

    db.delete(project)
    db.commit()
    return True


def delete_all_user_projects(db: Session, user_id: str) -> int:
    """Elimina todos los proyectos de un usuario. Retorna el número de proyectos eliminados."""
    count = db.query(Project).filter(Project.user_id == user_id).delete()
    db.commit()
    return count
