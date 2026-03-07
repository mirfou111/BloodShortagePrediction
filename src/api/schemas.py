"""
Schémas Pydantic — définissent la structure exacte
des données échangées entre l'API et les clients.

Pydantic valide automatiquement :
- Les types (int, str, float...)
- Les valeurs obligatoires vs optionnelles
- Les formats (dates, emails...)

Si une donnée ne correspond pas au schéma,
FastAPI retourne automatiquement une erreur 422.
"""

from pydantic import BaseModel
from typing import Optional
from datetime import date


class HospitalResponse(BaseModel):
    id: int
    name: str
    city: str
    region: str
    latitude: float
    longitude: float
    capacity_level: str
    has_blood_bank: bool

    model_config = {"from_attributes": True}


class StockResponse(BaseModel):
    hospital_id: int
    hospital_name: str
    blood_type: str
    product_type: str
    date: date
    quantity: int
    minimum_threshold: int
    expiring_soon: int
    status: str   # OK / FAIBLE / CRITIQUE

    model_config = {"from_attributes": True}


class PredictionResponse(BaseModel):
    hospital: str
    region: str
    blood_type: str
    product_type: str
    current_stock: int
    minimum_threshold: int
    shortage_probability: float
    severity: str
    predicted_for: str


class TransferResponse(BaseModel):
    from_hospital: str
    to_hospital: str
    blood_type: str
    product_type: str
    quantity: int
    distance_km: float
    urgency: str
    score: float
    shortage_proba: float


class NetworkSummaryResponse(BaseModel):
    last_update: str
    total_hospitals: int
    total_units: int
    stock_by_product: list
    critical_hospitals: list
    expiring_soon_hospitals: list


class ChatRequest(BaseModel):
    message: str
    reset_conversation: Optional[bool] = False


class ChatResponse(BaseModel):
    response: str
    tools_used: Optional[list[str]] = []