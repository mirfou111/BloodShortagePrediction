# src/data_generation/debug_flow.py
"""
Script de diagnostic : trace le flux exact
dons → transfusions → stock pour UN hôpital, UN groupe, UN produit
sur les 30 premiers jours.
"""

from datetime import date, timedelta
import random
import json
from ..api.database import SessionLocal
from ..api.models import Hospital, Event
from .reference_data import (
    BLOOD_TYPE_DISTRIBUTION, PRODUCT_DEMAND_RATIO,
    MINIMUM_THRESHOLDS, INITIAL_STOCK
)
from .generator import get_day_multipliers, add_noise, distribute_by_blood_type, distribute_by_product, BASE_DAILY_DONATIONS, BASE_DAILY_TRANSFUSIONS

def debug_flow():
    db = SessionLocal()
    events = []
    
    # Simulation sur 30 jours pour Hôpital Principal (grand) / O+ / CGR
    hospital_size = "grand"
    blood_type = "O+"
    product = "CGR"
    region = "Dakar"
    
    stock = INITIAL_STOCK[hospital_size][product] * BLOOD_TYPE_DISTRIBUTION[blood_type]
    stock = int(stock)
    threshold = MINIMUM_THRESHOLDS[hospital_size][product]
    
    print(f"{'Jour':<6} {'Dons':>6} {'Transf':>8} {'Péremption':>12} {'Stock':>7} {'Seuil':>7} {'Pénurie':>9}")
    print("-" * 65)
    
    current_date = date(2023, 1, 1)
    
    for day in range(60):
        demand_mult, donation_mult = get_day_multipliers(current_date, region, events)
        
        # Dons
        base_don = BASE_DAILY_DONATIONS[hospital_size]
        total_dons = add_noise(base_don * donation_mult)
        dons_by_bt = distribute_by_blood_type(total_dons)
        don_cgr = dons_by_bt.get(blood_type, 0)
        
        # Transfusions
        base_transf = BASE_DAILY_TRANSFUSIONS[hospital_size]
        total_transf = add_noise(base_transf * demand_mult)
        transf_by_bt = distribute_by_blood_type(total_transf)
        transf_total_bt = transf_by_bt.get(blood_type, 0)
        transf_by_prod = distribute_by_product(transf_total_bt)
        transf_cgr = transf_by_prod.get(product, 0)
        actual_transf = min(transf_cgr, stock)
        
        # Péremption
        expired = 0
        if day % 42 == 0 and day > 0:
            expired = int(stock * 0.05)
        
        # Mise à jour stock
        stock = stock + don_cgr - actual_transf - expired
        stock = max(0, stock)
        
        shortage = "⚠️ OUI" if stock < threshold else "non"
        
        print(f"{str(current_date):<12} {don_cgr:>4} {actual_transf:>8} {expired:>12} {stock:>7} {threshold:>7} {shortage:>9}")
        
        current_date += timedelta(days=1)
    
    db.close()

if __name__ == "__main__":
    debug_flow()