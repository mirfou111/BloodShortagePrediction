# src/data_generation/ode_generator.py

"""
Générateur de données basé sur un système d'équations différentielles.

Modèle dynamique du stock sanguin :
    dS/dt = D(t) - T(t) - E(t)

    D(t) = dons au temps t
    T(t) = transfusions au temps t  
    E(t) = expirations au temps t (stock âgé de 42j)

Chaque terme est modélisé par des fonctions sinusoïdales + multiplicateurs
événementiels pour reproduire les patterns réels.
"""

import numpy as np
import pandas as pd
import json
import random
from datetime import date, timedelta
from loguru import logger

from ..api.database import SessionLocal
from ..api.models import (
    Hospital, Stock, Transfusion, Don, Event,
    BloodType, ProductType, CollectionType, TransfusionReason
)
from .reference_data import (
    HOSPITALS, EVENTS, BLOOD_TYPE_DISTRIBUTION,
    MINIMUM_THRESHOLDS, BLOOD_TYPE_RARITY
)

# ─────────────────────────────────────────────────────
# PARAMÈTRES DE CALIBRATION
# Ajustés pour atteindre pct_pénurie cible par produit
# ─────────────────────────────────────────────────────

# Dons de base quotidiens par taille d'hôpital (toutes transfusions)
D_BASE = {
    "grand": 30,
    "moyen": 15,
    "petit": 6,
}

# Ratio consommation/don par produit
# Plus ce ratio est proche de 1, plus les tensions sont fréquentes
CONSUMPTION_RATIO = {
    "CGR": 0.70,   # réduit depuis 0.88
    "PFC": 0.55,   # réduit depuis 0.72
    "CPA": 0.65,   # réduit depuis 0.80
    "CPD": 0.65,   # inchangé
}

# Fraction de chaque don convertie en produit
DON_TO_PRODUCT = {
    "CGR": 1.00,   # 1 don = 1 CGR
    "PFC": 0.90,   # 1 don = 0.9 PFC (légères pertes)
    "CPA": 0.22,   # 4-5 dons nécessaires pour 1 CPA
    "CPD": 0.14,   # 6-7 dons nécessaires pour 1 CPD
}

# Stock initial en jours de consommation
# Ex: 14 → stock initial = 14 jours de consommation normale
INITIAL_DAYS_OF_STOCK = {
    "grand": {"CGR": 12, "PFC": 18, "CPA": 16, "CPD": 20},
    "moyen": {"CGR": 10, "PFC": 15, "CPA": 14, "CPD": 18},
    "petit": {"CGR": 8,  "PFC": 12, "CPA": 12, "CPD": 16},
}

# Durée de vie max (jours)
MAX_SHELF_LIFE = 42

# Dates de simulation
START_DATE = date(2023, 1, 1)
END_DATE   = date(2024, 12, 31)


# ─────────────────────────────────────────────────────
# FONCTIONS TEMPORELLES
# ─────────────────────────────────────────────────────

def seasonality_donation(day_of_year: int) -> float:
    """
    Modèle sinusoïdal des dons sur l'année.
    - Pic en juin (journée mondiale du don)
    - Creux en janvier (fêtes) et août (saison des pluies)
    
    f(t) = 1 + A × sin(2π(t - φ) / 365)
    A = amplitude, φ = déphasage
    """
    A   = 0.15   # amplitude : ±15% de variation saisonnière
    phi = 150    # pic vers le jour 150 (fin mai/juin)
    return 1.0 + A * np.sin(2 * np.pi * (day_of_year - phi) / 365)


def seasonality_transfusion(day_of_year: int) -> float:
    """
    Modèle sinusoïdal des transfusions.
    - Pic en août (saison des pluies = accidents)
    - Creux en janvier/février
    """
    A   = 0.20   # amplitude : ±20% (plus variable que les dons)
    phi = 60     # pic vers le jour 220 (août)
    return 1.0 + A * np.sin(2 * np.pi * (day_of_year - phi) / 365)


def weekend_factor(weekday: int) -> float:
    """
    Réduction des dons le weekend.
    weekday: 0=lundi ... 6=dimanche
    """
    if weekday == 5:   # samedi
        return 0.60
    elif weekday == 6: # dimanche
        return 0.40
    return 1.0


def noise(sigma: float = 0.12) -> float:
    """
    Bruit gaussien multiplicatif.
    sigma=0.12 → variation de ±12% autour de la valeur attendue.
    Distribution normale tronquée entre 0.6 et 1.4.
    """
    return float(np.clip(np.random.normal(1.0, sigma), 0.6, 1.4))


# ─────────────────────────────────────────────────────
# CHARGEMENT DES ÉVÉNEMENTS
# ─────────────────────────────────────────────────────

def build_event_calendar(db) -> dict:
    """
    Construit un calendrier des multiplicateurs événementiels
    sous forme de dict : {date → {region → (demand_mult, donation_mult)}}
    Plus efficace que de boucler sur les événements à chaque itération.
    """
    events = db.query(Event).all()
    calendar = {}

    current = START_DATE
    while current <= END_DATE:
        calendar[current] = {}
        for event in events:
            if event.start_date <= current <= event.end_date:
                regions = json.loads(event.affected_regions)
                for region in regions:
                    # On garde le multiplicateur le plus impactant par région
                    if region not in calendar[current]:
                        calendar[current][region] = (
                            event.demand_multiplier,
                            event.donation_multiplier
                        )
                    else:
                        existing = calendar[current][region]
                        calendar[current][region] = (
                            max(existing[0], event.demand_multiplier),
                            min(existing[1], event.donation_multiplier)
                        )
        current += timedelta(days=1)

    return calendar


# ─────────────────────────────────────────────────────
# INTÉGRATION NUMÉRIQUE (méthode d'Euler forward)
# ─────────────────────────────────────────────────────

def compute_daily_flows(
    current_date: date,
    day_of_year: int,
    hospital_size: str,
    region: str,
    blood_type: str,
    product: str,
    event_calendar: dict,
) -> tuple[int, int]:
    """
    Calcule les dons et transfusions du jour pour un
    hôpital/groupe/produit donné.

    Retourne : (dons_du_jour, transfusions_du_jour)

    Formules :
        D(t) = D_base × bt_ratio × product_ratio
                × season_D(t) × weekend(t) × event_D(t) × noise()

        T(t) = D(t) × product_ratio × consumption_ratio
                × season_T(t) × event_T(t) × noise()
    """
    weekday    = current_date.weekday()
    bt_ratio   = BLOOD_TYPE_DISTRIBUTION[blood_type]
    prod_ratio = DON_TO_PRODUCT[product]
    cons_ratio = CONSUMPTION_RATIO[product]

    # ── Modificateurs événementiels ────────────────
    event_demand_mult   = 1.0
    event_donation_mult = 1.0
    if current_date in event_calendar and region in event_calendar[current_date]:
        event_demand_mult, event_donation_mult = event_calendar[current_date][region]

    # ── Dons D(t) ──────────────────────────────────
    D_base = D_BASE[hospital_size]
    D_t = (
        D_base
        * bt_ratio
        * prod_ratio
        * seasonality_donation(day_of_year)
        * weekend_factor(weekday)
        * event_donation_mult
        * noise(sigma=0.10)
    )
    D_t = max(0, int(round(D_t)))

    # ── Transfusions T(t) ──────────────────────────
    # Base transfusion = dons × ratio consommation
    # + modulation saisonnière indépendante
    T_t = (
        D_BASE[hospital_size]
        * bt_ratio
        * prod_ratio
        * cons_ratio
        * seasonality_transfusion(day_of_year)
        * event_demand_mult
        * noise(sigma=0.15)   # plus de variabilité sur la demande
    )
    T_t = max(0, int(round(T_t)))

    return D_t, T_t


def compute_expiration(stock_history: list, max_shelf_life: int = MAX_SHELF_LIFE) -> int:
    """
    Calcule les expirations du jour.

    Principe : les poches reçues il y a exactement MAX_SHELF_LIFE jours
    expirent aujourd'hui si elles n'ont pas été consommées.

    On utilise l'historique des dons pour approximer
    combien de poches de ce jour-là restent en stock.

    stock_history : liste des dons des 42 derniers jours [j-42, j-41, ..., j-1]
    """
    if len(stock_history) < max_shelf_life:
        return 0

    # Les dons d'il y a 42 jours qui n'ont pas encore été consommés
    oldest_donation = stock_history[-max_shelf_life]

    # On estime que 8-15% des poches les plus anciennes expirent
    # (les autres ont été consommées entre-temps)
    expiration_rate = random.uniform(0.08, 0.15)
    return max(0, int(oldest_donation * expiration_rate))


# ─────────────────────────────────────────────────────
# INSERTION DES DONNÉES DE RÉFÉRENCE
# ─────────────────────────────────────────────────────

def insert_hospitals(db) -> list:
    logger.info("Insertion des hôpitaux...")
    hospitals = []
    for h in HOSPITALS:
        hospital = Hospital(**h)
        db.add(hospital)
        hospitals.append(hospital)
    db.commit()
    for h in hospitals:
        db.refresh(h)
    logger.success(f"  ✅ {len(hospitals)} hôpitaux insérés")
    return hospitals


def insert_events(db) -> None:
    logger.info("Insertion des événements...")
    for e in EVENTS:
        event = Event(
            name=e["name"],
            event_type=e["event_type"],
            start_date=date.fromisoformat(e["start_date"]),
            end_date=date.fromisoformat(e["end_date"]),
            affected_regions=e["affected_regions"],
            demand_multiplier=e["demand_multiplier"],
            donation_multiplier=e["donation_multiplier"],
        )
        db.add(event)
    db.commit()
    logger.success(f"  ✅ {len(EVENTS)} événements insérés")


# ─────────────────────────────────────────────────────
# GÉNÉRATEUR PRINCIPAL
# ─────────────────────────────────────────────────────

def generate_all_data():
    """
    Point d'entrée principal.
    Génère 2 ans de données via intégration numérique d'Euler.
    """
    np.random.seed(42)   # Reproductibilité
    random.seed(42)

    db = SessionLocal()

    try:
        # ── Références ────────────────────────────
        hospitals = insert_hospitals(db)
        insert_events(db)
        event_calendar = build_event_calendar(db)

        blood_types = [bt.value for bt in BloodType]
        products    = [pt.value for pt in ProductType]

        total_days = (END_DATE - START_DATE).days + 1
        logger.info(f"Génération ODE : {total_days} jours × "
                    f"{len(hospitals)} hôpitaux × "
                    f"{len(blood_types)} groupes × "
                    f"{len(products)} produits")

        # ── État du système ────────────────────────
        # stock_state[h_id][bt][prod] = stock actuel
        # don_history[h_id][bt][prod] = liste des 42 derniers dons (FIFO)
        stock_state = {}
        don_history = {}

        for hospital in hospitals:
            stock_state[hospital.id] = {}
            don_history[hospital.id] = {}
            size = hospital.capacity_level

            for bt in blood_types:
                stock_state[hospital.id][bt] = {}
                don_history[hospital.id][bt] = {}
                bt_ratio = BLOOD_TYPE_DISTRIBUTION[bt]

                for prod in products:
                    prod_ratio   = DON_TO_PRODUCT[prod]
                    cons_ratio   = CONSUMPTION_RATIO[prod]
                    days_of_stock = INITIAL_DAYS_OF_STOCK[size][prod]

                    # Stock initial = N jours de consommation normale
                    daily_consumption = (
                        D_BASE[size] * bt_ratio * prod_ratio * cons_ratio
                    )
                    initial_stock = max(2, int(daily_consumption * days_of_stock))
                    stock_state[hospital.id][bt][prod] = initial_stock

                    # Historique initial : simuler les 42 derniers jours de dons
                    daily_don = max(1, int(D_BASE[size] * bt_ratio * prod_ratio))
                    don_history[hospital.id][bt][prod] = [daily_don] * MAX_SHELF_LIFE

        # ── Boucle temporelle ─────────────────────
        batch_stocks       = []
        batch_transfusions = []
        batch_dons         = []

        current_date = START_DATE

        for day_idx in range(total_days):
            day_of_year = current_date.timetuple().tm_yday

            if day_idx % 60 == 0:
                logger.info(f"  {current_date} ({day_idx}/{total_days})")

            for hospital in hospitals:
                size   = hospital.capacity_level
                region = hospital.region

                for bt in blood_types:
                    for prod in products:

                        # ── 1. Calcul des flux ─────────────────
                        D_t, T_t = compute_daily_flows(
                            current_date, day_of_year,
                            size, region, bt, prod,
                            event_calendar
                        )

                        # ── 2. Expiration ──────────────────────
                        E_t = compute_expiration(
                            don_history[hospital.id][bt][prod]
                        )

                        # ── 3. Intégration d'Euler ─────────────
                        # S(t+1) = S(t) + D(t) - T(t) - E(t)
                        # Contrainte physique : S ≥ 0
                        current_stock = stock_state[hospital.id][bt][prod]

                        # On ne transfuse pas plus que ce qu'on a
                        actual_T = min(T_t, current_stock)

                        new_stock = current_stock + D_t - actual_T - E_t
                        new_stock = max(0, new_stock)

                        stock_state[hospital.id][bt][prod] = new_stock

                        # ── 4. Mise à jour historique dons ─────
                        don_history[hospital.id][bt][prod].append(D_t)
                        if len(don_history[hospital.id][bt][prod]) > MAX_SHELF_LIFE:
                            don_history[hospital.id][bt][prod].pop(0)

                        # ── 5. Enregistrement ──────────────────
                        threshold = MINIMUM_THRESHOLDS[size][prod]
                        expiring  = int(new_stock * random.uniform(0.05, 0.12))

                        batch_stocks.append(Stock(
                            hospital_id=hospital.id,
                            blood_type=bt,
                            product_type=prod,
                            date=current_date,
                            quantity=new_stock,
                            minimum_threshold=threshold,
                            expiring_soon=expiring,
                        ))

                        if D_t > 0:
                            batch_dons.append(Don(
                                hospital_id=hospital.id,
                                blood_type=bt,
                                date=current_date,
                                quantity=D_t,
                                collection_type=random.choice(["fixe", "mobile"]),
                            ))

                        if actual_T > 0:
                            batch_transfusions.append(Transfusion(
                                hospital_id=hospital.id,
                                blood_type=bt,
                                product_type=prod,
                                date=current_date,
                                quantity=actual_T,
                                reason=random.choices(
                                    ["chirurgie", "urgence",
                                     "maladie_chronique", "accouchement"],
                                    weights=[0.35, 0.30, 0.25, 0.10]
                                )[0],
                            ))

            # ── Flush batch tous les 30 jours ──────────
            if day_idx % 30 == 29:
                db.bulk_save_objects(batch_stocks)
                db.bulk_save_objects(batch_dons)
                db.bulk_save_objects(batch_transfusions)
                db.commit()
                batch_stocks, batch_dons, batch_transfusions = [], [], []

            current_date += timedelta(days=1)

        # ── Flush final ────────────────────────────
        if batch_stocks:
            db.bulk_save_objects(batch_stocks)
            db.bulk_save_objects(batch_dons)
            db.bulk_save_objects(batch_transfusions)
            db.commit()

        logger.success("✅ Génération ODE terminée !")
        _print_summary(db)

    except Exception as e:
        logger.error(f"Erreur : {e}")
        db.rollback()
        raise
    finally:
        db.close()


def _print_summary(db):
    print("\n" + "="*50)
    print("📊 RÉSUMÉ")
    print("="*50)
    print(f"  Hôpitaux     : {db.query(Hospital).count()}")
    print(f"  Événements   : {db.query(Event).count()}")
    print(f"  Stocks       : {db.query(Stock).count():,}")
    print(f"  Dons         : {db.query(Don).count():,}")
    print(f"  Transfusions : {db.query(Transfusion).count():,}")
    print("="*50)


if __name__ == "__main__":
    generate_all_data()