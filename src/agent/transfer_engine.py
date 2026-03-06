# src/agent/transfer_engine.py

"""
Moteur de suggestion de transfert de poches de sang.

Algorithme :
  1. Identifier les hôpitaux en besoin (pénurie prédite J+3)
  2. Identifier les hôpitaux en surplus ou avec péremption imminente
  3. Scorer chaque paire (source, destination) selon urgence/distance/surplus
  4. Générer les suggestions optimales
  5. Sauvegarder en base
"""

import math
import pickle
import json
import pandas as pd
import numpy as np
from datetime import date, timedelta
from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..api.database import SessionLocal
from ..api.models import Hospital, Stock, Transfer, Alert, AlertType, AlertSeverity


# ─────────────────────────────────────────────────────
# CONSTANTES
# ─────────────────────────────────────────────────────

MODEL_PATH    = "data/models/xgboost_shortage_predictor.pkl"
FEATURES_PATH = "data/models/feature_columns.json"

# Distance maximale acceptable pour un transfert (km)
MAX_TRANSFER_DISTANCE_KM = 500

# Surplus minimum requis pour qu'un hôpital puisse donner
# (en multiple du seuil minimum)
MIN_SURPLUS_RATIO = 2.0

# Quantité minimale à transférer (pas la peine pour 1 poche)
MIN_TRANSFER_QTY = 3


# ─────────────────────────────────────────────────────
# 1. FORMULE DE HAVERSINE
# ─────────────────────────────────────────────────────

def haversine_distance(lat1: float, lon1: float,
                       lat2: float, lon2: float) -> float:
    """
    Calcule la distance en km entre deux points GPS.
    Utilise la formule de Haversine qui tient compte
    de la courbure terrestre.

    Ex: Dakar → Tambacounda ≈ 470 km
    """
    R = 6371  # Rayon de la Terre en km

    # Conversion degrés → radians
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)

    c = 2 * math.asin(math.sqrt(a))
    return round(R * c, 1)


def build_distance_matrix(hospitals: list[Hospital]) -> dict:
    """
    Précalcule toutes les distances entre hôpitaux.
    Retourne un dict : {(h1_id, h2_id) → distance_km}

    On précalcule pour éviter de recalculer à chaque itération.
    8 hôpitaux → 28 paires uniques.
    """
    distances = {}
    for i, h1 in enumerate(hospitals):
        for h2 in hospitals[i+1:]:
            d = haversine_distance(h1.latitude, h1.longitude,
                                   h2.latitude, h2.longitude)
            distances[(h1.id, h2.id)] = d
            distances[(h2.id, h1.id)] = d  # symétrique
        distances[(h1.id, h1.id)] = 0.0
    return distances


# ─────────────────────────────────────────────────────
# 2. CHARGEMENT DU MODÈLE ET PRÉDICTIONS
# ─────────────────────────────────────────────────────

def load_model():
    """Charge le modèle XGBoost entraîné."""
    with open(MODEL_PATH, "rb") as f:
        model = pickle.load(f)
    with open(FEATURES_PATH, "r") as f:
        feature_cols = json.load(f)
    return model, feature_cols


def get_latest_features(db: Session, prediction_date: date) -> pd.DataFrame:
    """
    Récupère les features ML pour chaque hôpital/groupe/produit
    à la date donnée, pour faire des prédictions.

    On reconstruit les features exactement comme dans le notebook EDA.
    """
    # Stock du jour courant et des 14 derniers jours
    query = text("""
        SELECT 
            s.hospital_id,
            s.blood_type,
            s.product_type,
            s.date,
            s.quantity,
            s.minimum_threshold,
            s.expiring_soon,
            h.capacity_level,
            h.region,
            h.name as hospital_name,
            h.latitude,
            h.longitude
        FROM stocks s
        JOIN hospitals h ON s.hospital_id = h.id
        WHERE s.date BETWEEN :start_date AND :end_date
        ORDER BY s.hospital_id, s.blood_type, s.product_type, s.date
    """)

    df = pd.read_sql(
        query,
        db.bind,
        params={
            "start_date": prediction_date - timedelta(days=35),
            "end_date": prediction_date
        },
        parse_dates=["date"]
    )
    if df.empty:
        logger.warning("Aucune donnée de stock trouvée pour cette période")
        return pd.DataFrame()

    # ── Features temporelles ──────────────────────
    df["day_of_week"]     = df["date"].dt.dayofweek
    df["month"]           = df["date"].dt.month
    df["is_weekend"]      = (df["day_of_week"] >= 5).astype(int)
    df["is_rainy_season"] = df["month"].isin([7, 8, 9, 10]).astype(int)
    df["is_ramadan"]      = df["date"].between(
        "2024-03-11", "2024-04-09"
    ).astype(int)

    # ── Lag features ─────────────────────────────
    group_keys = ["hospital_id", "blood_type", "product_type"]
    for lag in [1, 2, 3, 7, 14]:
        df[f"stock_lag_{lag}"] = df.groupby(group_keys)["quantity"].shift(lag)

    # ── Rolling features ──────────────────────────
    df["stock_rolling_7d"] = df.groupby(group_keys)["quantity"].transform(
        lambda x: x.shift(1).rolling(7, min_periods=1).mean()
    )
    df["stock_rolling_30d"] = df.groupby(group_keys)["quantity"].transform(
        lambda x: x.shift(1).rolling(30, min_periods=1).mean()
    )

    # ── Transfusions rolling ──────────────────────
    transf_query = text("""
    SELECT hospital_id, blood_type, product_type, date,
           SUM(quantity) as daily_transf
    FROM transfusions
    WHERE date BETWEEN :start_date AND :end_date
    GROUP BY hospital_id, blood_type, product_type, date
    """)

    # 2. On exécute avec pandas
    df_transf = pd.read_sql(
        transf_query,
        db.bind,
        params={
            "start_date": prediction_date - timedelta(days=35),
            "end_date": prediction_date
        },
        parse_dates=["date"]
    )
    df = df.merge(df_transf, on=group_keys + ["date"], how="left")
    df["daily_transf"] = df["daily_transf"].fillna(0)
    df["transf_rolling_7d"] = df.groupby(group_keys)["daily_transf"].transform(
        lambda x: x.shift(1).rolling(7, min_periods=1).mean()
    )
    df["transf_rolling_30d"] = df.groupby(group_keys)["daily_transf"].transform(
        lambda x: x.shift(1).rolling(30, min_periods=1).mean()
    )

    # ── Dons rolling ──────────────────────────────
    dons_query = text("""
    SELECT hospital_id, blood_type, date,
           SUM(quantity) as daily_dons
    FROM dons
    WHERE date BETWEEN :start_date AND :end_date
    GROUP BY hospital_id, blood_type, date
    """)
    df_dons = pd.read_sql(
        dons_query,
        db.bind,
        params={
            "start_date": prediction_date - timedelta(days=35),
            "end_date": prediction_date
        },
        parse_dates=["date"]
    )
    df = df.merge(
        df_dons,
        on=["hospital_id", "blood_type", "date"],
        how="left"
    )
    df["daily_dons"] = df["daily_dons"].fillna(0)
    df["dons_rolling_7d"] = df.groupby(group_keys)["daily_dons"].transform(
        lambda x: x.shift(1).rolling(7, min_periods=1).mean()
    )

    # ── Événements ────────────────────────────────
    df["days_to_next_event"] = 30   # simplifié pour le moteur
    df["is_during_event"]    = 0

    # ── Encodages ─────────────────────────────────
    bt_map = {
        "A_NEG":0, "A_POS":1, "AB_NEG":2, "AB_POS":3,
        "B_NEG":4, "B_POS":5, "O_NEG":6,  "O_POS":7
    }
    prod_map = {"CPA":0, "CPD":1, "CGR":2, "PFC":3}
    cap_map  = {"grand":0, "moyen":1, "petit":2}
    rarity   = {
        "O_POS":1, "A_POS":2, "B_POS":3, "AB_POS":4,
        "O_NEG":5, "A_NEG":6, "B_NEG":7, "AB_NEG":8
    }

    df["blood_type_enc"]   = df["blood_type"].map(bt_map)
    df["product_type_enc"] = df["product_type"].map(prod_map)
    df["capacity_enc"]     = df["capacity_level"].map(cap_map)
    df["blood_type_rarity"] = df["blood_type"].map(rarity)

    # ── Filtrer sur la date de prédiction ─────────
    df_today = df[df["date"] == pd.Timestamp(prediction_date)].copy()
    df_today = df_today.dropna(subset=["stock_lag_7"])

    return df_today


# ─────────────────────────────────────────────────────
# 3. IDENTIFICATION BESOINS & SURPLUS
# ─────────────────────────────────────────────────────

def identify_needs_and_surpluses(
    df_today: pd.DataFrame,
    model,
    feature_cols: list
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Utilise le modèle pour identifier :
    - Les besoins : hôpitaux où une pénurie est prédite dans J+3
    - Les surplus : hôpitaux avec stock > seuil × MIN_SURPLUS_RATIO
                    OU avec péremption imminente

    Retourne : (df_needs, df_surpluses)
    """
    if df_today.empty:
        return pd.DataFrame(), pd.DataFrame()

    # ── Prédictions du modèle ─────────────────────
    X = df_today[feature_cols].fillna(0)
    df_today = df_today.copy()
    df_today["shortage_proba"] = model.predict_proba(X)[:, 1]
    df_today["shortage_predicted"] = model.predict(X)

    # ── Besoins : pénurie prédite ─────────────────
    df_needs = df_today[
        df_today["shortage_predicted"] == 1
    ].copy()
    df_needs["urgency_score"] = df_needs["shortage_proba"]

    # Sévérité selon probabilité
    df_needs["severity"] = df_needs["shortage_proba"].apply(
        lambda p: "critique" if p > 0.85
        else "modere" if p > 0.65
        else "faible"
    )

    # ── Surplus : stock élevé ou péremption proche ─
    df_surpluses = df_today[
        (df_today["quantity"] > df_today["minimum_threshold"] * MIN_SURPLUS_RATIO)
        | (df_today["expiring_soon"] > MIN_TRANSFER_QTY)
    ].copy()

    # Quantité transférable = stock - (seuil × 1.3) pour garder un tampon
    df_surpluses["transferable_qty"] = (
        df_surpluses["quantity"]
        - df_surpluses["minimum_threshold"] * 1.3
    ).clip(lower=0).astype(int)

    # Priorité péremption : si expiring_soon élevé, on transfère en priorité
    df_surpluses["expiry_urgency"] = (
        df_surpluses["expiring_soon"] / df_surpluses["quantity"].clip(lower=1)
    )

    df_surpluses = df_surpluses[df_surpluses["transferable_qty"] >= MIN_TRANSFER_QTY]

    logger.info(f"  Besoins identifiés  : {len(df_needs)} situations")
    logger.info(f"  Surplus identifiés  : {len(df_surpluses)} situations")

    return df_needs, df_surpluses


# ─────────────────────────────────────────────────────
# 4. ALGORITHME DE SCORING & MATCHING
# ─────────────────────────────────────────────────────

def score_transfer(
    need_row: pd.Series,
    surplus_row: pd.Series,
    distance_km: float
) -> float:
    """
    Calcule le score d'un transfert potentiel.
    Plus le score est élevé, plus le transfert est pertinent.

    Score = w1×urgence + w2×surplus_dispo + w3×(1/distance) + w4×péremption

    Poids calibrés selon priorités médicales :
    - Urgence    : 40% (priorité patient)
    - Surplus    : 25% (faisabilité)
    - Distance   : 20% (coût logistique)
    - Péremption : 15% (éviter gaspillage)
    """
    if distance_km > MAX_TRANSFER_DISTANCE_KM:
        return 0.0  # Trop loin, on ignore

    # Normalisation de la distance (0=loin, 1=proche)
    distance_score = 1.0 - (distance_km / MAX_TRANSFER_DISTANCE_KM)

    # Normalisation du surplus disponible (0=peu, 1=beaucoup)
    surplus_score = min(1.0, surplus_row["transferable_qty"] / 50)

    # Score urgence depuis la probabilité de pénurie
    urgency_score = need_row["shortage_proba"]

    # Score péremption
    expiry_score = surplus_row["expiry_urgency"]

    # Score final pondéré
    final_score = (
        0.40 * urgency_score
        + 0.25 * surplus_score
        + 0.20 * distance_score
        + 0.15 * expiry_score
    )

    return round(final_score, 4)


def generate_transfer_suggestions(
    df_needs: pd.DataFrame,
    df_surpluses: pd.DataFrame,
    distances: dict,
    hospitals: list[Hospital]
) -> list[dict]:
    """
    Génère la liste optimale de transferts suggérés.

    Algorithme greedy (gourmand) :
    Pour chaque besoin (trié par urgence décroissante) :
      → Trouver le meilleur surplus compatible
         (même groupe sanguin, même produit, distance acceptable)
      → Calculer la quantité à transférer
      → Déduire du surplus disponible
      → Passer au besoin suivant
    """
    suggestions = []

    # Trier les besoins par urgence décroissante
    needs_sorted = df_needs.sort_values("urgency_score", ascending=False)

    # Copie pour pouvoir déduire les surplus utilisés
    surpluses_available = df_surpluses.copy()

    for _, need in needs_sorted.iterrows():
        need_hospital_id = need["hospital_id"]
        blood_type       = need["blood_type"]
        product_type     = need["product_type"]

        # Trouver les surplus compatibles (même groupe + produit)
        compatible = surpluses_available[
            (surpluses_available["blood_type"]   == blood_type)
            & (surpluses_available["product_type"] == product_type)
            & (surpluses_available["hospital_id"]  != need_hospital_id)
            & (surpluses_available["transferable_qty"] >= MIN_TRANSFER_QTY)
        ].copy()

        if compatible.empty:
            continue

        # Scorer chaque source potentielle
        best_score  = 0.0
        best_source = None

        for _, surplus in compatible.iterrows():
            dist = distances.get(
                (surplus["hospital_id"], need_hospital_id), 9999
            )
            score = score_transfer(need, surplus, dist)

            if score > best_score:
                best_score  = score
                best_source = surplus
                best_dist   = dist

        if best_source is None or best_score == 0:
            continue

        # Quantité à transférer = min(surplus dispo, besoin estimé)
        estimated_need = max(
            MIN_TRANSFER_QTY,
            int(need["minimum_threshold"] * 1.5 - need["quantity"])
        )
        transfer_qty = min(
            int(best_source["transferable_qty"]),
            estimated_need
        )
        transfer_qty = max(MIN_TRANSFER_QTY, transfer_qty)

        suggestions.append({
            "from_hospital_id": int(best_source["hospital_id"]),
            "from_hospital":    best_source["hospital_name"],
            "to_hospital_id":   int(need_hospital_id),
            "to_hospital":      need["hospital_name"],
            "blood_type":       blood_type,
            "product_type":     product_type,
            "quantity":         transfer_qty,
            "distance_km":      best_dist,
            "urgency":          need["severity"],
            "score":            best_score,
            "shortage_proba":   round(float(need["shortage_proba"]), 3),
            "expiring_soon":    int(best_source["expiring_soon"]),
        })

        # Déduire la quantité transférée du surplus disponible
        idx = surpluses_available[
            surpluses_available["hospital_id"] == best_source["hospital_id"]
        ].index
        surpluses_available.loc[idx, "transferable_qty"] -= transfer_qty

    # Trier par score décroissant
    suggestions.sort(key=lambda x: x["score"], reverse=True)
    return suggestions


# ─────────────────────────────────────────────────────
# 5. SAUVEGARDE EN BASE & AFFICHAGE
# ─────────────────────────────────────────────────────

def save_suggestions(suggestions: list[dict], db: Session, prediction_date: date):
    """Sauvegarde les suggestions de transfert en base."""
    saved = 0
    for s in suggestions:
        transfer = Transfer(
            from_hospital_id=s["from_hospital_id"],
            to_hospital_id=s["to_hospital_id"],
            blood_type=s["blood_type"],
            product_type=s["product_type"],
            quantity=s["quantity"],
            distance_km=s["distance_km"],
            urgency=s["urgency"],
            suggested_date=prediction_date + timedelta(days=1),
            status="suggere",
        )
        db.add(transfer)
        saved += 1

    db.commit()
    logger.success(f"✅ {saved} transferts sauvegardés en base")


def print_suggestions(suggestions: list[dict], prediction_date: date):
    """Affiche un rapport lisible des suggestions."""
    print("\n" + "="*70)
    print(f"🩸 SUGGESTIONS DE TRANSFERT — {prediction_date}")
    print("="*70)

    if not suggestions:
        print("  Aucun transfert suggéré pour cette date.")
        return

    # Grouper par urgence
    for urgency in ["critique", "modere", "faible"]:
        group = [s for s in suggestions if s["urgency"] == urgency]
        if not group:
            continue

        emoji = "🔴" if urgency == "critique" else "🟡" if urgency == "modere" else "🟢"
        print(f"\n{emoji} URGENCE {urgency.upper()} ({len(group)} transferts)")
        print("-" * 70)

        for s in group:
            print(
                f"  {s['blood_type']}/{s['product_type']:3s} | "
                f"{s['from_hospital']:35s} → {s['to_hospital']:35s} | "
                f"{s['quantity']:3d} unités | "
                f"{s['distance_km']:5.0f} km | "
                f"P(pénurie)={s['shortage_proba']:.0%}"
            )

    print(f"\n  Total : {len(suggestions)} transferts suggérés")
    print("="*70 + "\n")


# ─────────────────────────────────────────────────────
# 6. POINT D'ENTRÉE PRINCIPAL
# ─────────────────────────────────────────────────────

def run_transfer_engine(prediction_date: date = None):
    """
    Exécute le moteur complet pour une date donnée.
    Par défaut : dernière date disponible en base.
    """
    db = SessionLocal()

    try:
        # Date de prédiction
        if prediction_date is None:
            result = db.execute(
                __import__("sqlalchemy").text("SELECT MAX(date) FROM stocks")
            ).scalar()
            prediction_date = result
        logger.info(f"🔍 Prédiction pour : {prediction_date}")

        # Chargement du modèle
        model, feature_cols = load_model()
        logger.info("✅ Modèle chargé")

        # Matrice des distances
        hospitals = db.query(Hospital).all()
        distances = build_distance_matrix(hospitals)
        logger.info(f"✅ Distances calculées ({len(distances)//2} paires)")

        # Features du jour
        df_today = get_latest_features(db, prediction_date)
        if df_today.empty:
            logger.error("Aucune feature disponible pour cette date")
            return []

        # Identification besoins/surplus
        df_needs, df_surpluses = identify_needs_and_surpluses(
            df_today, model, feature_cols
        )

        # Génération des suggestions
        suggestions = generate_transfer_suggestions(
            df_needs, df_surpluses, distances, hospitals
        )

        # Affichage
        print_suggestions(suggestions, prediction_date)

        # Sauvegarde
        if suggestions:
            save_suggestions(suggestions, db, prediction_date)

        return suggestions

    except Exception as e:
        logger.error(f"Erreur moteur transfert : {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run_transfer_engine()