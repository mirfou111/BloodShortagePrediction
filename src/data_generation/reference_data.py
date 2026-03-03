# src/data_generation/reference_data.py

"""
Données de référence fixes du projet BloodFlow Sénégal.
Ces données ne changent pas : hôpitaux, coordonnées GPS, événements récurrents.
On les centralise ici pour ne pas les réécrire dans chaque script.
"""

# ─────────────────────────────────────────────────────
# HÔPITAUX
# ─────────────────────────────────────────────────────

HOSPITALS = [
    {
        "name": "Hôpital Principal de Dakar",
        "city": "Dakar",
        "region": "Dakar",
        "latitude": 14.6937,
        "longitude": -17.4441,
        "capacity_level": "grand",
        "has_blood_bank": True,
    },
    {
        "name": "CHU Aristide Le Dantec",
        "city": "Dakar",
        "region": "Dakar",
        "latitude": 14.6747,
        "longitude": -17.4362,
        "capacity_level": "grand",
        "has_blood_bank": True,
    },
    {
        "name": "Hôpital Général de Grand Yoff",
        "city": "Dakar",
        "region": "Dakar",
        "latitude": 14.7272,
        "longitude": -17.4572,
        "capacity_level": "moyen",
        "has_blood_bank": True,
    },
    {
        "name": "CHR de Thiès",
        "city": "Thiès",
        "region": "Thiès",
        "latitude": 14.7910,
        "longitude": -16.9359,
        "capacity_level": "moyen",
        "has_blood_bank": True,
    },
    {
        "name": "CHR de Saint-Louis",
        "city": "Saint-Louis",
        "region": "Saint-Louis",
        "latitude": 16.0179,
        "longitude": -16.4897,
        "capacity_level": "moyen",
        "has_blood_bank": True,
    },
    {
        "name": "CHR de Ziguinchor",
        "city": "Ziguinchor",
        "region": "Ziguinchor",
        "latitude": 12.5605,
        "longitude": -16.2719,
        "capacity_level": "moyen",
        "has_blood_bank": True,
    },
    {
        "name": "Hôpital Régional de Kaolack",
        "city": "Kaolack",
        "region": "Kaolack",
        "latitude": 14.1520,
        "longitude": -16.0726,
        "capacity_level": "petit",
        "has_blood_bank": True,
    },
    {
        "name": "Hôpital Régional de Tambacounda",
        "city": "Tambacounda",
        "region": "Tambacounda",
        "latitude": 13.7707,
        "longitude": -13.6673,
        "capacity_level": "petit",
        "has_blood_bank": True,
    },
]


# ─────────────────────────────────────────────────────
# GROUPES SANGUINS & LEUR RARETÉ
# ─────────────────────────────────────────────────────

# Distribution approximative de la population sénégalaise
# Source : distributions africaines sub-sahariennes
BLOOD_TYPE_DISTRIBUTION = {
    "O+":  0.46,   # Le plus fréquent
    "A+":  0.27,
    "B+":  0.19,
    "AB+": 0.04,
    "O-":  0.02,   # Rare mais universel → très demandé
    "A-":  0.01,
    "B-":  0.01,
    "AB-": 0.003,  # Le plus rare
}

# Score de rareté (utilisé comme feature ML) : plus c'est élevé, plus c'est rare
BLOOD_TYPE_RARITY = {
    "O+":  1,
    "A+":  2,
    "B+":  3,
    "AB+": 4,
    "O-":  5,
    "A-":  6,
    "B-":  7,
    "AB-": 8,
}


# ─────────────────────────────────────────────────────
# PRODUITS SANGUINS & LEUR DEMANDE RELATIVE
# ─────────────────────────────────────────────────────

# Le CGR représente ~70% des transfusions, PFC ~20%, CPA ~8%, CPD ~2%
PRODUCT_DEMAND_RATIO = {
    "CGR": 0.70,
    "PFC": 0.20,
    "CPA": 0.08,
    "CPD": 0.02,
}

# Seuils minimaux de stock (en unités) selon la taille de l'hôpital
MINIMUM_THRESHOLDS = {
    "grand": {"CGR": 50, "PFC": 20, "CPA": 10, "CPD": 5},
    "moyen": {"CGR": 25, "PFC": 10, "CPA": 5,  "CPD": 2},
    "petit": {"CGR": 10, "PFC": 5,  "CPA": 3,  "CPD": 1},
}

# Stock initial selon la taille de l'hôpital (en unités par groupe/produit)
INITIAL_STOCK = {
    "grand": {"CGR": 80, "PFC": 35, "CPA": 20, "CPD": 8},
    "moyen": {"CGR": 40, "PFC": 18, "CPA": 10, "CPD": 4},
    "petit": {"CGR": 15, "PFC": 8,  "CPA": 5,  "CPD": 2},
}


# ─────────────────────────────────────────────────────
# ÉVÉNEMENTS NATIONAUX (2023 & 2024)
# ─────────────────────────────────────────────────────

"""
Les dates des fêtes islamiques varient chaque année (calendrier lunaire).
On utilise des approximations pour 2023 et 2024.

demand_multiplier  : facteur appliqué aux transfusions pendant l'événement
donation_multiplier: facteur appliqué aux dons pendant l'événement
affected_regions   : régions principalement impactées
"""

EVENTS = [

    # ── MAGAL DE TOUBA ──────────────────────────────
    # Plus grand rassemblement religieux du Sénégal
    # Des millions de pèlerins → accidents de la route massifs
    {
        "name": "Magal de Touba 2023",
        "event_type": "religieux",
        "start_date": "2023-08-27",
        "end_date": "2023-08-29",
        "affected_regions": '["Diourbel", "Dakar", "Thiès"]',
        "demand_multiplier": 1.8,
        "donation_multiplier": 0.9,
    },
    {
        "name": "Magal de Touba 2024",
        "event_type": "religieux",
        "start_date": "2024-08-15",
        "end_date": "2024-08-17",
        "affected_regions": '["Diourbel", "Dakar", "Thiès"]',
        "demand_multiplier": 1.8,
        "donation_multiplier": 0.9,
    },

    # ── TABASKI (Aïd el-Kebir) ──────────────────────
    # Forte augmentation des accidents liés aux sacrifices et déplacements
    {
        "name": "Tabaski 2023",
        "event_type": "religieux",
        "start_date": "2023-06-28",
        "end_date": "2023-06-30",
        "affected_regions": '["Dakar", "Thiès", "Kaolack", "Saint-Louis", "Ziguinchor", "Tambacounda"]',
        "demand_multiplier": 1.6,
        "donation_multiplier": 0.8,
    },
    {
        "name": "Tabaski 2024",
        "event_type": "religieux",
        "start_date": "2024-06-16",
        "end_date": "2024-06-18",
        "affected_regions": '["Dakar", "Thiès", "Kaolack", "Saint-Louis", "Ziguinchor", "Tambacounda"]',
        "demand_multiplier": 1.6,
        "donation_multiplier": 0.8,
    },

    # ── KORITÉ (Aïd el-Fitr) ────────────────────────
    {
        "name": "Korité 2023",
        "event_type": "religieux",
        "start_date": "2023-04-21",
        "end_date": "2023-04-22",
        "affected_regions": '["Dakar", "Thiès", "Kaolack"]',
        "demand_multiplier": 1.3,
        "donation_multiplier": 0.85,
    },
    {
        "name": "Korité 2024",
        "event_type": "religieux",
        "start_date": "2024-04-10",
        "end_date": "2024-04-11",
        "affected_regions": '["Dakar", "Thiès", "Kaolack"]',
        "demand_multiplier": 1.3,
        "donation_multiplier": 0.85,
    },

    # ── GAMOU DE TIVAOUANE ───────────────────────────
    {
        "name": "Gamou de Tivaouane 2023",
        "event_type": "religieux",
        "start_date": "2023-09-27",
        "end_date": "2023-09-28",
        "affected_regions": '["Thiès", "Dakar"]',
        "demand_multiplier": 1.4,
        "donation_multiplier": 0.9,
    },
    {
        "name": "Gamou de Tivaouane 2024",
        "event_type": "religieux",
        "start_date": "2024-09-15",
        "end_date": "2024-09-16",
        "affected_regions": '["Thiès", "Dakar"]',
        "demand_multiplier": 1.4,
        "donation_multiplier": 0.9,
    },

    # ── RAMADAN ──────────────────────────────────────
    # Période de jeûne → baisse significative des dons
    {
        "name": "Ramadan 2023",
        "event_type": "religieux",
        "start_date": "2023-03-23",
        "end_date": "2023-04-20",
        "affected_regions": '["Dakar", "Thiès", "Kaolack", "Saint-Louis", "Ziguinchor", "Tambacounda"]',
        "demand_multiplier": 1.0,
        "donation_multiplier": 0.5,  # Baisse de 50% des dons
    },
    {
        "name": "Ramadan 2024",
        "event_type": "religieux",
        "start_date": "2024-03-11",
        "end_date": "2024-04-09",
        "affected_regions": '["Dakar", "Thiès", "Kaolack", "Saint-Louis", "Ziguinchor", "Tambacounda"]',
        "demand_multiplier": 1.0,
        "donation_multiplier": 0.5,
    },

    # ── SAISON DES PLUIES ────────────────────────────
    # Juillet à Octobre : routes glissantes, inondations, accidents
    {
        "name": "Saison des pluies 2023",
        "event_type": "saisonnier",
        "start_date": "2023-07-01",
        "end_date": "2023-10-31",
        "affected_regions": '["Dakar", "Thiès", "Kaolack", "Ziguinchor", "Tambacounda"]',
        "demand_multiplier": 1.3,
        "donation_multiplier": 0.85,
    },
    {
        "name": "Saison des pluies 2024",
        "event_type": "saisonnier",
        "start_date": "2024-07-01",
        "end_date": "2024-10-31",
        "affected_regions": '["Dakar", "Thiès", "Kaolack", "Ziguinchor", "Tambacounda"]',
        "demand_multiplier": 1.3,
        "donation_multiplier": 0.85,
    },

    # ── JOURNÉE MONDIALE DU DON DE SANG ─────────────
    # 14 juin : campagnes nationales → hausse des dons
    {
        "name": "Journée Mondiale Don de Sang 2023",
        "event_type": "campagne_don",
        "start_date": "2023-06-12",
        "end_date": "2023-06-16",
        "affected_regions": '["Dakar", "Thiès", "Kaolack", "Saint-Louis"]',
        "demand_multiplier": 1.0,
        "donation_multiplier": 2.0,  # Doublement des dons
    },
    {
        "name": "Journée Mondiale Don de Sang 2024",
        "event_type": "campagne_don",
        "start_date": "2024-06-10",
        "end_date": "2024-06-14",
        "affected_regions": '["Dakar", "Thiès", "Kaolack", "Saint-Louis"]',
        "demand_multiplier": 1.0,
        "donation_multiplier": 2.0,
    },
]