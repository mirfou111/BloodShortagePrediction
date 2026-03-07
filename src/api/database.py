"""
Point d'entrée de la connexion à la base de données.
Ce fichier est importé par tous les autres modules qui ont besoin de la DB.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

# Charge les variables du fichier .env
load_dotenv()

# Récupère l'URL de connexion depuis .env
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Render fournit une URL postgresql:// mais SQLAlchemy 2.x
# avec psycopg2 nécessite postgresql+psycopg2://
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgresql://", "postgresql+psycopg2://", 1
    )

# Le moteur : c'est lui qui gère le pool de connexions à PostgreSQL
# engine = create_engine(
#     DATABASE_URL,
#     echo=False,       # Mettre True pour voir les requêtes SQL dans le terminal (utile en debug)
#     pool_pre_ping=True # Vérifie que la connexion est vivante avant chaque requête
# )
engine = create_engine(
    DATABASE_URL.replace("postgresql://", "postgresql+psycopg://"),
    echo=False,
    pool_pre_ping=True
)

# La factory de sessions : chaque "session" est une transaction avec la DB
SessionLocal = sessionmaker(
    autocommit=False,  # On gère nous-mêmes les commits
    autoflush=False,
    bind=engine
)

# La classe de base dont hériteront tous nos modèles
Base = declarative_base()


def get_db():
    """
    Générateur de session. Utilisé comme dépendance dans FastAPI.
    Garantit que la session est toujours fermée après usage.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()