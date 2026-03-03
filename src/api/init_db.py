from loguru import logger
from .database import engine, Base

# Import explicite de chaque modèle
# Sans ça, SQLAlchemy ne "voit" pas les tables à créer
from .models import Hospital, Stock, Transfusion, Don, Event, Alert, Transfer


def init_db():
    logger.info("Création des tables dans PostgreSQL...")
    Base.metadata.create_all(bind=engine)
    logger.success("✅ Tables créées avec succès !")


if __name__ == "__main__":
    init_db()