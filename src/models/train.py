# src/models/train.py

"""
Entraînement du modèle XGBoost de prédiction de pénurie de sang.

Pipeline complet :
  1. Chargement du dataset ML
  2. Split temporel (train=2023 / test=2024)
  3. Entraînement XGBoost
  4. Évaluation complète
  5. Sauvegarde du modèle
"""

import os
import json
import pickle
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

from sklearn.metrics import (
    classification_report, confusion_matrix,
    roc_auc_score, roc_curve, precision_recall_curve,
    average_precision_score
)
from sklearn.preprocessing import StandardScaler
import xgboost as xgb
from loguru import logger

# ─────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────

DATA_PATH  = "data/processed/ml_dataset.csv"
MODEL_DIR  = "data/models"
PLOTS_DIR  = "data/processed"

# Features utilisées par le modèle
FEATURE_COLS = [
    # On retire "quantity" et "minimum_threshold" (trop directs)
    # On garde uniquement les infos PASSÉES et CONTEXTUELLES
    "expiring_soon",
    "stock_lag_1", "stock_lag_2", "stock_lag_3",
    "stock_lag_7", "stock_lag_14",
    "stock_rolling_7d", "stock_rolling_30d",
    "transf_rolling_7d", "transf_rolling_30d",
    "dons_rolling_7d",
    "day_of_week", "month",
    "is_weekend", "is_rainy_season", "is_ramadan",
    "days_to_next_event", "is_during_event",
    "blood_type_enc", "product_type_enc",
    "capacity_enc", "blood_type_rarity",
]

TARGET_COL = "target_shortage_j3"


# ─────────────────────────────────────────────────────
# 1. CHARGEMENT & SPLIT
# ─────────────────────────────────────────────────────

def load_and_split(path: str):
    """
    Charge le dataset et effectue un split temporel strict.
    Train = toute l'année 2023
    Test  = toute l'année 2024

    Pourquoi pas un split aléatoire ?
    Parce que nos données sont des séries temporelles.
    Un split aléatoire laisserait fuiter des infos du futur
    vers le passé (data leakage), ce qui gonflerait
    artificiellement les métriques.
    """
    logger.info(f"Chargement du dataset : {path}")
    df = pd.read_csv(path, parse_dates=["date"])

    # Suppression des lignes avec NaN dans les features
    df = df.dropna(subset=FEATURE_COLS + [TARGET_COL])
    df[TARGET_COL] = df[TARGET_COL].astype(int)

    # Split temporel
    train = df[df["date"].dt.year == 2023].copy()
    test  = df[df["date"].dt.year == 2024].copy()

    X_train = train[FEATURE_COLS]
    y_train = train[TARGET_COL]
    X_test  = test[FEATURE_COLS]
    y_test  = test[TARGET_COL]

    logger.info(f"  Train (2023) : {len(X_train):,} lignes | "
                f"pénuries : {y_train.sum():,} ({y_train.mean()*100:.1f}%)")
    logger.info(f"  Test  (2024) : {len(X_test):,} lignes  | "
                f"pénuries : {y_test.sum():,} ({y_test.mean()*100:.1f}%)")

    return X_train, X_test, y_train, y_test, train, test


# ─────────────────────────────────────────────────────
# 2. ENTRAÎNEMENT
# ─────────────────────────────────────────────────────

def train_model(X_train, y_train, X_test, y_test):
    """
    Entraîne le modèle XGBoost.

    Paramètres clés expliqués :
    - scale_pos_weight : compense le déséquilibre de classes
      (si 80% non-pénurie / 20% pénurie → scale_pos_weight=4)
    - max_depth : profondeur max des arbres (évite l'overfitting)
    - learning_rate : pas d'apprentissage (faible = plus robuste)
    - n_estimators : nombre d'arbres (plus = mieux, jusqu'à un plateau)
    - early_stopping_rounds : arrête si pas d'amélioration après N rounds
    - eval_metric : métrique de suivi pendant l'entraînement
    """

    # Calcul du poids pour compenser le déséquilibre de classes
    neg = (y_train == 0).sum()
    pos = (y_train == 1).sum()
    scale_pos_weight = neg / pos
    logger.info(f"  Déséquilibre classes → scale_pos_weight = {scale_pos_weight:.2f}")

    model = xgb.XGBClassifier(
        # Architecture
        n_estimators=500,
        max_depth=6,
        min_child_weight=3,

        # Apprentissage
        learning_rate=0.05,
        subsample=0.8,           # 80% des données par arbre (évite overfitting)
        colsample_bytree=0.8,    # 80% des features par arbre

        # Gestion du déséquilibre
        scale_pos_weight=scale_pos_weight,

        # Régularisation
        reg_alpha=0.1,           # L1 regularization
        reg_lambda=1.0,          # L2 regularization

        # Évaluation & arrêt précoce
        eval_metric=["logloss", "auc"],
        early_stopping_rounds=30,

        # Technique
        tree_method="hist",      # Algorithme rapide pour grands datasets
        random_state=42,
        n_jobs=-1,               # Utilise tous les cœurs CPU disponibles
        verbosity=0,
    )

    logger.info("Entraînement en cours...")
    model.fit(
        X_train, y_train,
        eval_set=[(X_train, y_train), (X_test, y_test)],
        verbose=50,   # Affiche les métriques tous les 50 arbres
    )

    best_iter = model.best_iteration
    logger.success(f"✅ Entraînement terminé ! Meilleur arbre : #{best_iter}")

    return model


# ─────────────────────────────────────────────────────
# 3. ÉVALUATION
# ─────────────────────────────────────────────────────

def evaluate_model(model, X_test, y_test):
    """
    Évalue le modèle sur le jeu de test avec plusieurs métriques.

    Métriques importantes pour notre cas :
    - Recall (sensibilité) : % de vraies pénuries détectées
      → On veut maximiser ça ! Manquer une pénurie = danger patient
    - Precision : % de vraies pénuries parmi les alertes levées
      → Si trop faible, les médecins ignorent les fausses alertes
    - AUC-ROC : performance globale du modèle (1.0 = parfait)
    - F1 : équilibre precision/recall
    """
    logger.info("Évaluation du modèle...")

    y_pred       = model.predict(X_test)
    y_pred_proba = model.predict_proba(X_test)[:, 1]

    # ── Rapport de classification ──────────────────
    print("\n" + "="*55)
    print("📊 RAPPORT DE CLASSIFICATION")
    print("="*55)
    print(classification_report(
        y_test, y_pred,
        target_names=["Pas de pénurie", "Pénurie J+3"],
        digits=3
    ))

    auc = roc_auc_score(y_test, y_pred_proba)
    ap  = average_precision_score(y_test, y_pred_proba)
    print(f"AUC-ROC          : {auc:.4f}")
    print(f"Average Precision: {ap:.4f}")
    print("="*55)

    # ── Matrice de confusion ───────────────────────
    _plot_confusion_matrix(y_test, y_pred)

    # ── Courbe ROC ────────────────────────────────
    _plot_roc_curve(y_test, y_pred_proba, auc)

    # ── Importance des features ───────────────────
    _plot_feature_importance(model)

    return {
        "auc_roc": round(auc, 4),
        "avg_precision": round(ap, 4),
        "classification_report": classification_report(
            y_test, y_pred,
            target_names=["Pas de pénurie", "Pénurie J+3"],
            output_dict=True
        )
    }


def _plot_confusion_matrix(y_test, y_pred):
    cm = confusion_matrix(y_test, y_pred)
    fig, ax = plt.subplots(figsize=(7, 5))
    sns.heatmap(
        cm, annot=True, fmt="d", cmap="Reds",
        xticklabels=["Pas pénurie", "Pénurie J+3"],
        yticklabels=["Pas pénurie", "Pénurie J+3"],
        ax=ax, linewidths=1
    )
    ax.set_title("Matrice de Confusion — Test 2024", fontsize=13, fontweight="bold")
    ax.set_ylabel("Réel")
    ax.set_xlabel("Prédit")

    # Annotations explicatives
    tn, fp, fn, tp = cm.ravel()
    ax.text(0.5, -0.15,
            f"Vrais Négatifs={tn:,}  |  Faux Positifs={fp:,}  |  "
            f"Faux Négatifs={fn:,}  |  Vrais Positifs={tp:,}",
            transform=ax.transAxes, ha="center", fontsize=9, color="gray")

    plt.tight_layout()
    plt.savefig(f"{PLOTS_DIR}/confusion_matrix.png", dpi=150)
    plt.show()
    logger.info(f"  ⚠️  Faux Négatifs (pénuries manquées) : {fn:,}")
    logger.info(f"  ✅  Vrais Positifs (pénuries détectées) : {tp:,}")


def _plot_roc_curve(y_test, y_pred_proba, auc):
    fpr, tpr, thresholds = roc_curve(y_test, y_pred_proba)
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.plot(fpr, tpr, color="#e74c3c", lw=2, label=f"XGBoost (AUC = {auc:.4f})")
    ax.plot([0, 1], [0, 1], color="gray", linestyle="--", label="Aléatoire (AUC = 0.50)")
    ax.fill_between(fpr, tpr, alpha=0.1, color="#e74c3c")
    ax.set_title("Courbe ROC — Test 2024", fontsize=13, fontweight="bold")
    ax.set_xlabel("Taux de Faux Positifs")
    ax.set_ylabel("Taux de Vrais Positifs (Recall)")
    ax.legend(loc="lower right")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(f"{PLOTS_DIR}/roc_curve.png", dpi=150)
    plt.show()


def _plot_feature_importance(model):
    importance = pd.DataFrame({
        "feature": FEATURE_COLS,
        "importance": model.feature_importances_
    }).sort_values("importance", ascending=True).tail(15)

    fig, ax = plt.subplots(figsize=(10, 7))
    bars = ax.barh(
        importance["feature"],
        importance["importance"],
        color=plt.cm.RdYlGn(importance["importance"] / importance["importance"].max())
    )
    ax.set_title("Top 15 Features les plus importantes", fontsize=13, fontweight="bold")
    ax.set_xlabel("Importance (gain)")
    plt.tight_layout()
    plt.savefig(f"{PLOTS_DIR}/feature_importance.png", dpi=150)
    plt.show()

    print("\n💡 Top 5 features :")
    for _, row in importance.tail(5).iloc[::-1].iterrows():
        print(f"   {row['feature']:<30} {row['importance']:.4f}")


# ─────────────────────────────────────────────────────
# 4. SAUVEGARDE
# ─────────────────────────────────────────────────────

def save_model(model, metrics: dict):
    """
    Sauvegarde le modèle entraîné et ses métadonnées.

    On sauvegarde deux choses :
    - Le modèle lui-même (pickle) → pour faire des prédictions
    - Les métadonnées (JSON) → pour tracer les performances dans le temps
    """
    os.makedirs(MODEL_DIR, exist_ok=True)

    # Sauvegarde du modèle
    model_path = f"{MODEL_DIR}/xgboost_shortage_predictor.pkl"
    with open(model_path, "wb") as f:
        pickle.dump(model, f)

    # Sauvegarde des features (pour valider les inputs en production)
    features_path = f"{MODEL_DIR}/feature_columns.json"
    with open(features_path, "w") as f:
        json.dump(FEATURE_COLS, f, indent=2)

    # Sauvegarde des métriques
    metrics_path = f"{MODEL_DIR}/metrics.json"
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2, default=str)

    logger.success(f"✅ Modèle sauvegardé : {model_path}")
    logger.success(f"✅ Features sauvegardées : {features_path}")
    logger.success(f"✅ Métriques sauvegardées : {metrics_path}")


# ─────────────────────────────────────────────────────
# 5. PIPELINE PRINCIPAL
# ─────────────────────────────────────────────────────

def run_training_pipeline():
    """Point d'entrée : exécute tout le pipeline d'entraînement."""

    logger.info("🚀 Démarrage du pipeline d'entraînement BloodFlow")
    logger.info("="*55)

    # Étape 1 : Chargement & split
    X_train, X_test, y_train, y_test, _, _ = load_and_split(DATA_PATH)

    # Étape 2 : Entraînement
    model = train_model(X_train, y_train, X_test, y_test)

    # Étape 3 : Évaluation
    metrics = evaluate_model(model, X_test, y_test)

    # Étape 4 : Sauvegarde
    save_model(model, metrics)

    logger.success("\n🎉 Pipeline terminé avec succès !")
    return model, metrics


if __name__ == "__main__":
    run_training_pipeline()