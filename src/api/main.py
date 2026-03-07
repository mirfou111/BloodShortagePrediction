"""
Application FastAPI — point d'entrée du backend BloodFlow.

Organisation :
  /api/hospitals     → données de référence
  /api/stocks        → stocks actuels
  /api/predictions   → prédictions ML
  /api/transfers     → suggestions de transfert
  /api/agent         → conversation LLM
  /api/network       → vue d'ensemble
"""

import json
from datetime import date
from typing import Optional
import os

import pandas as pd
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

from .database import get_db, engine
from .models import Hospital, Stock, Transfer
from .schemas import (
    HospitalResponse, StockResponse, PredictionResponse,
    TransferResponse, NetworkSummaryResponse,
    ChatRequest, ChatResponse
)
from ..agent.transfer_engine import (
    run_transfer_engine, load_model,
    get_latest_features, identify_needs_and_surpluses,
    build_distance_matrix
)
from ..agent.llm_agent import BloodFlowAgent


# ─────────────────────────────────────────────────────
# INITIALISATION
# ─────────────────────────────────────────────────────

app = FastAPI(
    title="BloodFlow Sénégal API",
    description="API de prédiction de pénurie et gestion des transferts de sang",
    version="1.0.0",
)

# CORS : permet au frontend React (port 3000) d'appeler l'API (port 8000)
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
]

# En production, on ajoute l'URL Vercel
VERCEL_URL = os.getenv("VERCEL_URL", "")
if VERCEL_URL:
    ALLOWED_ORIGINS.append(f"https://{VERCEL_URL}")

# URL frontend explicite si définie
FRONTEND_URL = os.getenv("FRONTEND_URL", "")
if FRONTEND_URL:
    ALLOWED_ORIGINS.append(FRONTEND_URL)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Instance unique de l'agent (conserve l'historique de conversation)
agent_instance = None

def get_agent() -> BloodFlowAgent:
    """Crée l'agent à la première utilisation (lazy loading)."""
    global agent_instance
    if agent_instance is None:
        agent_instance = BloodFlowAgent()
    return agent_instance


# ─────────────────────────────────────────────────────
# UTILITAIRES
# ─────────────────────────────────────────────────────

def get_latest_date(db: Session) -> date:
    """Retourne la dernière date disponible en base."""
    result = db.execute(text("SELECT MAX(date) FROM stocks")).scalar()
    if not result:
        raise HTTPException(status_code=404, detail="Aucune donnée disponible")
    return result


# ─────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────

@app.get("/")
def root():
    """Health check — vérifie que l'API est en ligne."""
    return {
        "status": "online",
        "service": "BloodFlow Sénégal API",
        "version": "1.0.0"
    }


# ── Hôpitaux ──────────────────────────────────────────

@app.get("/api/hospitals", response_model=list[HospitalResponse])
def get_hospitals(db: Session = Depends(get_db)):
    """
    Retourne la liste de tous les hôpitaux du réseau.
    Utilisé par le dashboard pour afficher la carte.
    """
    hospitals = db.query(Hospital).all()
    return hospitals


@app.get("/api/hospitals/{hospital_id}", response_model=HospitalResponse)
def get_hospital(hospital_id: int, db: Session = Depends(get_db)):
    """Retourne les détails d'un hôpital spécifique."""
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hôpital non trouvé")
    return hospital


# ── Stocks ────────────────────────────────────────────

@app.get("/api/stocks/latest")
def get_latest_stocks(
    hospital_id: Optional[int] = None,
    product_type: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Retourne les stocks du dernier jour disponible.
    Filtrable par hôpital et/ou produit.
    """
    latest_date = get_latest_date(db)

    query = """
    SELECT
        s.hospital_id,
        h.name as hospital_name,
        h.region,
        h.capacity_level,
        s.blood_type,
        s.product_type,
        s.date,
        s.quantity,
        s.minimum_threshold,
        s.expiring_soon,
        CASE
            WHEN s.quantity < s.minimum_threshold       THEN 'CRITIQUE'
            WHEN s.quantity < s.minimum_threshold * 1.5 THEN 'FAIBLE'
            ELSE 'OK'
        END as status
    FROM stocks s
    JOIN hospitals h ON s.hospital_id = h.id
    WHERE s.date = :latest_date
    """
    params = {"latest_date": latest_date}

    if hospital_id:
        query += " AND s.hospital_id = :hospital_id"
        params["hospital_id"] = hospital_id

    if product_type:
        query += " AND s.product_type = :product_type"
        params["product_type"] = product_type

    query += " ORDER BY h.name, s.blood_type, s.product_type"

    df = pd.read_sql(text(query), engine, params=params)
    return {
        "date": str(latest_date),
        "count": len(df),
        "stocks": df.to_dict("records")
    }


@app.get("/api/stocks/history/{hospital_id}")
def get_stock_history(
    hospital_id: int,
    blood_type: str,
    product_type: str,
    days: int = 30,
    db: Session = Depends(get_db)
):
    """
    Retourne l'historique des stocks sur N jours.
    Utilisé pour les graphiques de tendance dans le dashboard.
    """
    query = """
    SELECT s.date, s.quantity, s.minimum_threshold, s.expiring_soon
    FROM stocks s
    WHERE s.hospital_id = :hospital_id
    AND s.blood_type = :blood_type
    AND s.product_type = :product_type
    AND s.date >= (SELECT MAX(date) - INTERVAL ':days days' FROM stocks)
    ORDER BY s.date
    """
    df = pd.read_sql(
        text(query), engine,
        params={
            "hospital_id": hospital_id,
            "blood_type": blood_type,
            "product_type": product_type,
            "days": days
        }
    )
    return df.to_dict("records")


# ── Prédictions ML ────────────────────────────────────

@app.get("/api/predictions")
def get_predictions(
    severity: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Retourne les prédictions de pénurie J+3 pour tout le réseau.
    Utilise le modèle XGBoost entraîné.
    """
    try:
        latest_date = get_latest_date(db)
        model, feature_cols = load_model()
        df_today = get_latest_features(db, latest_date)

        if df_today.empty:
            return {"predictions": [], "total": 0}

        df_needs, _ = identify_needs_and_surpluses(df_today, model, feature_cols)

        if severity and severity != "tous":
            df_needs = df_needs[df_needs["severity"] == severity]

        predictions = []
        for _, row in df_needs.iterrows():
            predictions.append({
                "hospital": row["hospital_name"],
                "hospital_id": int(row["hospital_id"]),
                "region": row["region"],
                "blood_type": row["blood_type"],
                "product_type": row["product_type"],
                "current_stock": int(row["quantity"]),
                "minimum_threshold": int(row["minimum_threshold"]),
                "shortage_probability": round(float(row["shortage_proba"]), 3),
                "severity": row["severity"],
            })

        predictions.sort(key=lambda x: x["shortage_probability"], reverse=True)

        return {
            "prediction_date": str(latest_date),
            "total": len(predictions),
            "critique": len([p for p in predictions if p["severity"] == "critique"]),
            "modere":   len([p for p in predictions if p["severity"] == "modere"]),
            "faible":   len([p for p in predictions if p["severity"] == "faible"]),
            "predictions": predictions
        }

    except Exception as e:
        logger.error(f"Erreur prédictions : {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Transferts ────────────────────────────────────────

@app.get("/api/transfers/suggestions")
def get_transfer_suggestions(db: Session = Depends(get_db)):
    """
    Lance le moteur d'optimisation et retourne les suggestions
    de transfert pour la dernière date disponible.
    """
    try:
        suggestions = run_transfer_engine()
        return {
            "total": len(suggestions),
            "critique": len([s for s in suggestions if s["urgency"] == "critique"]),
            "modere":   len([s for s in suggestions if s["urgency"] == "modere"]),
            "faible":   len([s for s in suggestions if s["urgency"] == "faible"]),
            "suggestions": suggestions
        }
    except Exception as e:
        logger.error(f"Erreur transferts : {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/transfers/history")
def get_transfer_history(limit: int = 50, db: Session = Depends(get_db)):
    """Retourne l'historique des transferts suggérés et effectués."""
    query = """
    SELECT
        t.id,
        h1.name as from_hospital,
        h2.name as to_hospital,
        t.blood_type,
        t.product_type,
        t.quantity,
        t.distance_km,
        t.urgency,
        t.status,
        t.suggested_date,
        t.created_at
    FROM transfers t
    JOIN hospitals h1 ON t.from_hospital_id = h1.id
    JOIN hospitals h2 ON t.to_hospital_id = h2.id
    ORDER BY t.created_at DESC
    LIMIT :limit
    """
    df = pd.read_sql(text(query), engine, params={"limit": limit})
    return df.to_dict("records")


# ── Résumé réseau ─────────────────────────────────────

@app.get("/api/network/summary")
def get_network_summary(db: Session = Depends(get_db)):
    """Vue d'ensemble du réseau de banques de sang."""
    latest_date = get_latest_date(db)

    stock_query = """
    SELECT
        product_type,
        SUM(quantity)                                           as total_units,
        SUM(CASE WHEN quantity < minimum_threshold THEN 1 ELSE 0 END) as shortage_count,
        COUNT(*)                                                as total_records,
        ROUND(AVG(CASE WHEN quantity < minimum_threshold
                  THEN 1.0 ELSE 0.0 END) * 100, 1)            as pct_shortage
    FROM stocks
    WHERE date = :date
    GROUP BY product_type
    """
    df_stock = pd.read_sql(text(stock_query), engine, params={"date": latest_date})

    critical_query = """
    SELECT h.name, h.region, COUNT(*) as nb_critical
    FROM stocks s
    JOIN hospitals h ON s.hospital_id = h.id
    WHERE s.date = :date AND s.quantity < s.minimum_threshold
    GROUP BY h.name, h.region
    ORDER BY nb_critical DESC
    """
    df_critical = pd.read_sql(text(critical_query), engine, params={"date": latest_date})

    expiry_query = """
    SELECT h.name, SUM(s.expiring_soon) as expiring
    FROM stocks s
    JOIN hospitals h ON s.hospital_id = h.id
    WHERE s.date = :date AND s.expiring_soon > 0
    GROUP BY h.name
    ORDER BY expiring DESC
    LIMIT 5
    """
    df_expiry = pd.read_sql(text(expiry_query), engine, params={"date": latest_date})

    return {
        "last_update": str(latest_date),
        "total_hospitals": db.query(Hospital).count(),
        "total_units": int(df_stock["total_units"].sum()),
        "stock_by_product": df_stock.to_dict("records"),
        "critical_hospitals": df_critical.to_dict("records"),
        "expiring_soon": df_expiry.to_dict("records"),
    }


# ── Agent conversationnel ─────────────────────────────

@app.post("/api/agent/chat", response_model=ChatResponse)
def chat_with_agent(request: ChatRequest):
    """
    Endpoint conversationnel — envoie un message à l'agent LLM
    et retourne sa réponse.

    Le paramètre reset_conversation permet de démarrer
    une nouvelle conversation (efface l'historique).
    """
    try:
        agent = get_agent()   # ← remplace agent_instance
        if request.reset_conversation:
            agent.reset_conversation()
        response = agent.chat(request.message)
        return ChatResponse(response=response)
    except Exception as e:
        logger.error(f"Erreur agent : {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/agent/conversation")
def reset_agent_conversation():
    agent = get_agent()       # ← remplace agent_instance
    agent.reset_conversation()
    return {"status": "conversation réinitialisée"}