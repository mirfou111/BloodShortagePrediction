# src/data_generation/generator.py

"""
Générateur de données synthétiques réalistes pour BloodFlow Sénégal.

Logique générale :
  Pour chaque jour sur 2 ans (2023-2024) :
    Pour chaque hôpital :
      Pour chaque groupe sanguin :
        Pour chaque produit :
          1. Calculer les dons du jour (base + modificateurs événements/weekend)
          2. Calculer les transfusions du jour (base + modificateurs)
          3. Mettre à jour le stock (stock_hier + dons - transfusions - péremptions)
          4. Enregistrer tout en base
"""

import random
import json
from datetime import date, timedelta
from loguru import logger

from ..api.database import SessionLocal
from ..api.models import (
    Hospital, Stock, Transfusion, Don, Event,
    BloodType, ProductType, CollectionType, TransfusionReason
)
from .reference_data import (
    HOSPITALS, EVENTS, BLOOD_TYPE_DISTRIBUTION,
    PRODUCT_DEMAND_RATIO, MINIMUM_THRESHOLDS, INITIAL_STOCK,
    BLOOD_TYPE_RARITY
)


# ─────────────────────────────────────────────────────
# CONSTANTES DE SIMULATION
# ─────────────────────────────────────────────────────

START_DATE = date(2023, 1, 1)
END_DATE   = date(2024, 12, 31)

# Dons quotidiens de base par taille d'hôpital (toutes collectes confondues)
BASE_DAILY_DONATIONS = {
    "grand": 25,
    "moyen": 12,
    "petit": 5,
}

# Transfusions quotidiennes de base par taille d'hôpital
BASE_DAILY_TRANSFUSIONS = {
    "grand": 20,
    "moyen": 10,
    "petit": 4,
}

# Durée de vie max d'une poche (jours)
MAX_SHELF_LIFE = 42

# Bruit aléatoire : ±N% de variation journalière naturelle
NOISE_FACTOR = 0.25


# ─────────────────────────────────────────────────────
# FONCTIONS UTILITAIRES
# ─────────────────────────────────────────────────────

def load_events(db) -> list[dict]:
    """Charge les événements depuis la DB et les retourne comme liste de dicts."""
    events = db.query(Event).all()
    return [
        {
            "start": e.start_date,
            "end": e.end_date,
            "affected_regions": json.loads(e.affected_regions),
            "demand_multiplier": e.demand_multiplier,
            "donation_multiplier": e.donation_multiplier,
        }
        for e in events
    ]


def get_day_multipliers(current_date: date, region: str, events: list[dict]) -> tuple[float, float]:
    """
    Calcule les multiplicateurs de demande et de dons pour un jour donné
    en tenant compte de tous les événements actifs ce jour-là.

    Retourne : (demand_multiplier, donation_multiplier)
    """
    demand_mult = 1.0
    donation_mult = 1.0

    for event in events:
        if event["start"] <= current_date <= event["end"]:
            # L'événement est actif ce jour
            if region in event["affected_regions"] or event["affected_regions"] == []:
                # On prend le multiplicateur le plus impactant (pas additif)
                demand_mult = max(demand_mult, event["demand_multiplier"])
                donation_mult = min(donation_mult, event["donation_multiplier"])

    # Réduction weekend pour les dons (-30%)
    if current_date.weekday() >= 5:  # 5=samedi, 6=dimanche
        donation_mult *= 0.7

    return demand_mult, donation_mult


def add_noise(value: float, factor: float = NOISE_FACTOR) -> int:
    """
    Ajoute une variation aléatoire réaliste à une valeur.
    Ex: add_noise(10, 0.25) → peut donner entre 7 et 13
    """
    noisy = value * random.uniform(1 - factor, 1 + factor)
    return max(0, int(round(noisy)))


def distribute_by_blood_type(total: int) -> dict[str, int]:
    """
    Distribue un total de poches selon la distribution réelle
    des groupes sanguins au Sénégal.
    """
    result = {}
    remaining = total

    blood_types = list(BLOOD_TYPE_DISTRIBUTION.keys())

    for i, bt in enumerate(blood_types):
        if i == len(blood_types) - 1:
            result[bt] = max(0, remaining)
        else:
            qty = int(round(total * BLOOD_TYPE_DISTRIBUTION[bt]))
            result[bt] = qty
            remaining -= qty

    return result


def distribute_by_product(total: int) -> dict[str, int]:
    """
    Distribue un total selon les ratios de demande par produit.
    """
    result = {}
    remaining = total
    products = list(PRODUCT_DEMAND_RATIO.keys())

    for i, prod in enumerate(products):
        if i == len(products) - 1:
            result[prod] = max(0, remaining)
        else:
            qty = int(round(total * PRODUCT_DEMAND_RATIO[prod]))
            result[prod] = qty
            remaining -= qty

    return result


# ─────────────────────────────────────────────────────
# INSERTION DES DONNÉES DE RÉFÉRENCE
# ─────────────────────────────────────────────────────

def insert_hospitals(db) -> list[Hospital]:
    """Insère les 8 hôpitaux en base et retourne les objets créés."""
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
    """Insère les événements nationaux en base."""
    logger.info("Insertion des événements nationaux...")
    from datetime import date as dt
    for e in EVENTS:
        event = Event(
            name=e["name"],
            event_type=e["event_type"],
            start_date=dt.fromisoformat(e["start_date"]),
            end_date=dt.fromisoformat(e["end_date"]),
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
    Génère 2 ans de données pour tous les hôpitaux.
    """
    db = SessionLocal()

    try:
        # ── Étape 1 : insérer les références ──────────
        hospitals = insert_hospitals(db)
        insert_events(db)
        events = load_events(db)

        logger.info(f"Génération de données du {START_DATE} au {END_DATE}...")
        logger.info(f"  → {len(hospitals)} hôpitaux")
        logger.info(f"  → {len(list(BloodType))} groupes sanguins")
        logger.info(f"  → {len(list(ProductType))} produits")

        blood_types = [bt.value for bt in BloodType]
        products    = [pt.value for pt in ProductType]

        # ── Étape 2 : initialiser les stocks ──────────
        # stock_state[hospital_id][blood_type][product] = quantité actuelle
        stock_state = {}

        for hospital in hospitals:
            stock_state[hospital.id] = {}
            init = INITIAL_STOCK[hospital.capacity_level]
            for bt in blood_types:
                stock_state[hospital.id][bt] = {}
                for prod in products:
                    # Stock initial pondéré par la distribution sanguine
                    base = init[prod] * BLOOD_TYPE_DISTRIBUTION[bt]
                    stock_state[hospital.id][bt][prod] = max(1, int(base))

        # ── Étape 3 : boucle temporelle ───────────────
        total_days = (END_DATE - START_DATE).days + 1
        current_date = START_DATE

        batch_stocks = []
        batch_transfusions = []
        batch_dons = []

        for day_idx in range(total_days):

            if day_idx % 30 == 0:
                logger.info(f"  Traitement : {current_date} ({day_idx}/{total_days} jours)")

            for hospital in hospitals:
                demand_mult, donation_mult = get_day_multipliers(
                    current_date, hospital.region, events
                )

                # ── Dons du jour ──────────────────────
                base_don = BASE_DAILY_DONATIONS[hospital.capacity_level]
                total_dons_today = add_noise(base_don * donation_mult)
                dons_by_bt = distribute_by_blood_type(total_dons_today)

                for bt, don_qty in dons_by_bt.items():
                    if don_qty > 0:
                        # Chaque don est enregistré comme CGR principalement
                        # (une poche = principalement CGR)
                        batch_dons.append(Don(
                            hospital_id=hospital.id,
                            blood_type=bt,
                            date=current_date,
                            quantity=don_qty,
                            collection_type=random.choice(["fixe", "mobile"]),
                        ))
                        # Mise à jour du stock
                        stock_state[hospital.id][bt]["CGR"] += don_qty
                        stock_state[hospital.id][bt]["PFC"] += int(don_qty * 0.8)
                        stock_state[hospital.id][bt]["CPA"] += int(don_qty * 0.4)
                        stock_state[hospital.id][bt]["CPD"] += int(don_qty * 0.1)

                # ── Transfusions du jour ──────────────
                base_transf = BASE_DAILY_TRANSFUSIONS[hospital.capacity_level]
                total_transf_today = add_noise(base_transf * demand_mult)
                transf_by_bt = distribute_by_blood_type(total_transf_today)

                for bt, transf_total in transf_by_bt.items():
                    transf_by_prod = distribute_by_product(transf_total)

                    for prod, transf_qty in transf_by_prod.items():
                        if transf_qty > 0:
                            # On ne transfuse pas plus que ce qu'on a
                            actual_qty = min(
                                transf_qty,
                                stock_state[hospital.id][bt][prod]
                            )
                            if actual_qty > 0:
                                batch_transfusions.append(Transfusion(
                                    hospital_id=hospital.id,
                                    blood_type=bt,
                                    product_type=prod,
                                    date=current_date,
                                    quantity=actual_qty,
                                    reason=random.choices(
                                        ["chirurgie", "urgence", "maladie_chronique", "accouchement"],
                                        weights=[0.35, 0.30, 0.25, 0.10]
                                    )[0],
                                ))
                                stock_state[hospital.id][bt][prod] -= actual_qty

                # ── Péremption simulée ─────────────────
                # Tous les 42 jours, on simule une perte de ~5% du stock
                if day_idx % MAX_SHELF_LIFE == 0:
                    for bt in blood_types:
                        for prod in products:
                            expired = int(stock_state[hospital.id][bt][prod] * 0.05)
                            stock_state[hospital.id][bt][prod] = max(
                                0,
                                stock_state[hospital.id][bt][prod] - expired
                            )

                # ── Enregistrement du stock du jour ───
                for bt in blood_types:
                    for prod in products:
                        qty = stock_state[hospital.id][bt][prod]
                        threshold = MINIMUM_THRESHOLDS[hospital.capacity_level][prod]
                        expiring = int(qty * random.uniform(0.02, 0.08))

                        batch_stocks.append(Stock(
                            hospital_id=hospital.id,
                            blood_type=bt,
                            product_type=prod,
                            date=current_date,
                            quantity=qty,
                            minimum_threshold=threshold,
                            expiring_soon=expiring,
                        ))

            current_date += timedelta(days=1)

            # ── Flush par batch de 30 jours ────────────
            # On insère par lots pour ne pas saturer la mémoire
            if day_idx % 30 == 29:
                logger.debug(f"  Flush batch : {len(batch_stocks)} stocks, "
                             f"{len(batch_dons)} dons, "
                             f"{len(batch_transfusions)} transfusions")
                db.bulk_save_objects(batch_stocks)
                db.bulk_save_objects(batch_dons)
                db.bulk_save_objects(batch_transfusions)
                db.commit()
                batch_stocks, batch_dons, batch_transfusions = [], [], []

        # ── Flush final ────────────────────────────────
        if batch_stocks:
            db.bulk_save_objects(batch_stocks)
            db.bulk_save_objects(batch_dons)
            db.bulk_save_objects(batch_transfusions)
            db.commit()

        logger.success("✅ Génération terminée !")
        _print_summary(db)

    except Exception as e:
        logger.error(f"Erreur durant la génération : {e}")
        db.rollback()
        raise
    finally:
        db.close()


def _print_summary(db):
    """Affiche un résumé des données générées."""
    from ..api.models import Don, Transfusion, Stock
    print("\n" + "="*50)
    print("📊 RÉSUMÉ DE LA GÉNÉRATION")
    print("="*50)
    print(f"  Hôpitaux    : {db.query(Hospital).count()}")
    print(f"  Événements  : {db.query(Event).count()}")
    print(f"  Stocks      : {db.query(Stock).count()}")
    print(f"  Dons        : {db.query(Don).count()}")
    print(f"  Transfusions: {db.query(Transfusion).count()}")
    print("="*50 + "\n")


if __name__ == "__main__":
    generate_all_data()