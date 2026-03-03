"""
Définition de toutes les tables de la base de données.
Chaque classe = une table PostgreSQL.
"""

from sqlalchemy import (
    Column, Integer, String, Float, Boolean,
    Date, DateTime, Enum, ForeignKey, Text, ARRAY
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from .database import Base


# ─────────────────────────────────────────
# ENUMS : valeurs fixes acceptées par la DB
# ─────────────────────────────────────────

class BloodType(str, enum.Enum):
    """Les 8 groupes sanguins."""
    A_POS = "A+"
    A_NEG = "A-"
    B_POS = "B+"
    B_NEG = "B-"
    AB_POS = "AB+"
    AB_NEG = "AB-"
    O_POS = "O+"
    O_NEG = "O-"


class ProductType(str, enum.Enum):
    """
    Les produits dérivés d'une poche de sang.
    CGR = Concentré de Globules Rouges (le plus courant)
    CPA = Concentré de Plaquettes d'Aphérèse
    PFC = Plasma Frais Congelé
    CPD = Concentré de Plaquettes Déleucocytées
    """
    CGR = "CGR"
    CPA = "CPA"
    PFC = "PFC"
    CPD = "CPD"


class HospitalSize(str, enum.Enum):
    GRAND = "grand"
    MOYEN = "moyen"
    PETIT = "petit"


class TransfusionReason(str, enum.Enum):
    CHIRURGIE = "chirurgie"
    URGENCE = "urgence"
    MALADIE_CHRONIQUE = "maladie_chronique"
    ACCOUCHEMENT = "accouchement"


class AlertType(str, enum.Enum):
    PENURIE = "penurie"
    PEREMPTION_IMMINENTE = "peremption_imminente"


class AlertSeverity(str, enum.Enum):
    CRITIQUE = "critique"
    MODERE = "modere"
    FAIBLE = "faible"


class TransferStatus(str, enum.Enum):
    SUGGERE = "suggere"
    ACCEPTE = "accepte"
    EFFECTUE = "effectue"


class EventType(str, enum.Enum):
    RELIGIEUX = "religieux"
    SAISONNIER = "saisonnier"
    SPORTIF = "sportif"
    ACCIDENT_MASSE = "accident_masse"
    CAMPAGNE_DON = "campagne_don"


class CollectionType(str, enum.Enum):
    FIXE = "fixe"        # Collecte au centre de transfusion
    MOBILE = "mobile"    # Collecte externe (école, entreprise...)


# ─────────────────────────────────────────
# MODÈLES / TABLES
# ─────────────────────────────────────────

class Hospital(Base):
    """
    Représente un hôpital ou centre de transfusion.
    C'est l'entité centrale autour de laquelle tout s'articule.
    """
    __tablename__ = "hospitals"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    city = Column(String(100), nullable=False)
    region = Column(String(100), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    capacity_level = Column(Enum(HospitalSize), nullable=False)
    has_blood_bank = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())

    # Relations : un hôpital peut avoir plusieurs stocks, dons, etc.
    stocks = relationship("Stock", back_populates="hospital")
    transfusions = relationship("Transfusion", back_populates="hospital")
    dons = relationship("Don", back_populates="hospital")
    alerts = relationship("Alert", back_populates="hospital")


class Stock(Base):
    """
    Stock quotidien d'un produit sanguin dans un hôpital.
    On stocke un enregistrement PAR JOUR, PAR HÔPITAL, PAR GROUPE,
    PAR PRODUIT. C'est ce qui nous permettra de faire des séries temporelles.
    """
    __tablename__ = "stocks"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    blood_type = Column(Enum(BloodType), nullable=False)
    product_type = Column(Enum(ProductType), nullable=False)
    date = Column(Date, nullable=False, index=True)
    quantity = Column(Integer, nullable=False, default=0)
    minimum_threshold = Column(Integer, nullable=False)
    # Nombre de poches dont la péremption est dans moins de 7 jours
    expiring_soon = Column(Integer, default=0)

    hospital = relationship("Hospital", back_populates="stocks")


class Transfusion(Base):
    """
    Enregistre chaque demande de transfusion.
    C'est notre principale variable cible pour la prédiction de la demande.
    """
    __tablename__ = "transfusions"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    blood_type = Column(Enum(BloodType), nullable=False)
    product_type = Column(Enum(ProductType), nullable=False)
    date = Column(Date, nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
    reason = Column(Enum(TransfusionReason), nullable=False)

    hospital = relationship("Hospital", back_populates="transfusions")


class Don(Base):
    """
    Enregistre chaque collecte de sang.
    Influencée par les événements (Ramadan = baisse, Journée mondiale = hausse).
    """
    __tablename__ = "dons"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    blood_type = Column(Enum(BloodType), nullable=False)
    date = Column(Date, nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
    collection_type = Column(Enum(CollectionType), nullable=False)

    hospital = relationship("Hospital", back_populates="dons")


class Event(Base):
    """
    Événements nationaux qui influencent la demande ou les dons.
    Le demand_multiplier et donation_multiplier sont utilisés
    lors de la génération des données ET comme features ML.
    Ex: Magal → demand_multiplier=1.8 signifie 80% de demande en plus.
    """
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    event_type = Column(Enum(EventType), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    affected_regions = Column(String(500))  # Stocké comme JSON string
    demand_multiplier = Column(Float, default=1.0)
    donation_multiplier = Column(Float, default=1.0)


class Alert(Base):
    """
    Alertes générées par l'agent IA.
    Trace de toutes les prédictions faites par le modèle.
    """
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    blood_type = Column(Enum(BloodType), nullable=False)
    product_type = Column(Enum(ProductType), nullable=False)
    alert_type = Column(Enum(AlertType), nullable=False)
    predicted_date = Column(Date, nullable=False)
    severity = Column(Enum(AlertSeverity), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    hospital = relationship("Hospital", back_populates="alerts")


class Transfer(Base):
    """
    Suggestions de transfert générées par le moteur d'optimisation.
    Un transfert va d'un hôpital source (surplus) vers un hôpital
    destinataire (pénurie imminente).
    """
    __tablename__ = "transfers"

    id = Column(Integer, primary_key=True, index=True)
    from_hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    to_hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    blood_type = Column(Enum(BloodType), nullable=False)
    product_type = Column(Enum(ProductType), nullable=False)
    quantity = Column(Integer, nullable=False)
    distance_km = Column(Float, nullable=False)
    urgency = Column(String(20), nullable=False)  # urgent / planifie
    suggested_date = Column(Date, nullable=False)
    status = Column(Enum(TransferStatus), default=TransferStatus.SUGGERE)
    created_at = Column(DateTime, server_default=func.now())