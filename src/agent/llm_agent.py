# src/agent/llm_agent.py

"""
Agent LLM BloodFlow basé sur Claude API.

Concepts clés :
- Tools (outils) : fonctions que Claude peut appeler pour obtenir des données
- Tool use : mécanisme par lequel Claude décide quel outil utiliser
- Conversation history : mémoire de la conversation pour le contexte
"""

import json
import pickle
import anthropic
import pandas as pd
from datetime import date, timedelta
from loguru import logger
from sqlalchemy import text

from ..api.database import SessionLocal
from ..api.models import Hospital, Stock, Transfer
from .transfer_engine import (
    run_transfer_engine,
    build_distance_matrix,
    get_latest_features,
    identify_needs_and_surpluses,
    load_model
)


# ─────────────────────────────────────────────────────
# DÉFINITION DES OUTILS (TOOLS)
# ─────────────────────────────────────────────────────

"""
Les "tools" sont des fonctions qu'on décrit à Claude en JSON.
Claude lit la description et décide quand les appeler.
C'est comme donner une boîte à outils à un assistant
en lui expliquant à quoi sert chaque outil.
"""

TOOLS = [
    {
        "name": "get_hospital_status",
        "description": """
            Récupère le statut actuel des stocks de sang d'un ou plusieurs hôpitaux.
            Retourne les niveaux de stock par groupe sanguin et produit,
            les seuils minimaux, et les alertes de péremption imminente.
            Utiliser quand l'utilisateur demande l'état d'un hôpital spécifique
            ou la situation générale du réseau.
        """,
        "input_schema": {
            "type": "object",
            "properties": {
                "hospital_name": {
                    "type": "string",
                    "description": "Nom partiel ou complet de l'hôpital. Laisser vide pour tous les hôpitaux."
                },
                "blood_type": {
                    "type": "string",
                    "description": "Groupe sanguin filtré (ex: O_POS, A_NEG). Laisser vide pour tous."
                }
            },
            "required": []
        }
    },
    {
        "name": "get_shortage_predictions",
        "description": """
            Prédit les pénuries de sang attendues dans les 3 prochains jours
            pour tous les hôpitaux du réseau.
            Retourne la liste des situations à risque avec leur probabilité
            et leur niveau de sévérité (critique/modéré/faible).
            Utiliser quand l'utilisateur demande les prévisions ou risques futurs.
        """,
        "input_schema": {
            "type": "object",
            "properties": {
                "severity_filter": {
                    "type": "string",
                    "enum": ["critique", "modere", "faible", "tous"],
                    "description": "Filtrer par niveau de sévérité"
                }
            },
            "required": []
        }
    },
    {
        "name": "get_transfer_suggestions",
        "description": """
            Lance le moteur d'optimisation et retourne les suggestions
            de transfert de poches de sang entre hôpitaux.
            Chaque suggestion inclut : hôpital source, hôpital destinataire,
            groupe sanguin, produit, quantité, distance et niveau d'urgence.
            Utiliser quand l'utilisateur demande quoi faire face aux pénuries
            ou comment optimiser la distribution.
        """,
        "input_schema": {
            "type": "object",
            "properties": {
                "urgency_filter": {
                    "type": "string",
                    "enum": ["critique", "modere", "faible", "tous"],
                    "description": "Filtrer par urgence"
                }
            },
            "required": []
        }
    },
    {
        "name": "get_network_summary",
        "description": """
            Retourne un résumé global du réseau de banques de sang :
            nombre total de poches disponibles par produit,
            hôpitaux en situation critique, taux de pénurie global,
            et comparaison avec la semaine précédente.
            Utiliser pour avoir une vue d'ensemble rapide de la situation.
        """,
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
]


# ─────────────────────────────────────────────────────
# IMPLÉMENTATION DES OUTILS
# ─────────────────────────────────────────────────────

def get_hospital_status(hospital_name: str = "", blood_type: str = "") -> dict:
    """
    Récupère le statut des stocks depuis la base de données.
    """
    db = SessionLocal()
    try:
        query = """
        SELECT
            h.name as hospital,
            h.region,
            h.capacity_level,
            s.blood_type,
            s.product_type,
            s.quantity,
            s.minimum_threshold,
            s.expiring_soon,
            CASE
                WHEN s.quantity < s.minimum_threshold THEN 'CRITIQUE'
                WHEN s.quantity < s.minimum_threshold * 1.5 THEN 'FAIBLE'
                ELSE 'OK'
            END as status
        FROM stocks s
        JOIN hospitals h ON s.hospital_id = h.id
        WHERE s.date = (SELECT MAX(date) FROM stocks)
        """
        params = {}

        if hospital_name:
            query += " AND h.name ILIKE :hospital_name"
            params["hospital_name"] = f"%{hospital_name}%"
        if blood_type:
            query += " AND s.blood_type = :blood_type"
            params["blood_type"] = blood_type

        query += " ORDER BY h.name, s.blood_type, s.product_type"

        df = pd.read_sql(text(query), db.bind, params=params)

        # Résumé structuré
        result = {
            "date": str(df["quantity"].index.max()) if not df.empty else "N/A",
            "hospitals": {}
        }

        for hospital, group in df.groupby("hospital"):
            critical = group[group["status"] == "CRITIQUE"]
            result["hospitals"][hospital] = {
                "region": group["region"].iloc[0],
                "capacity": group["capacity_level"].iloc[0],
                "total_units": int(group["quantity"].sum()),
                "critical_shortages": len(critical),
                "details": group[[
                    "blood_type", "product_type",
                    "quantity", "minimum_threshold",
                    "expiring_soon", "status"
                ]].to_dict("records")
            }

        return result

    finally:
        db.close()


def get_shortage_predictions(severity_filter: str = "tous") -> dict:
    """
    Utilise le modèle ML pour prédire les pénuries J+3.
    """
    db = SessionLocal()
    try:
        model, feature_cols = load_model()
        hospitals = db.query(Hospital).all()

        # Date de prédiction = dernière date en base
        result = db.execute(text("SELECT MAX(date) FROM stocks")).scalar()
        prediction_date = result

        df_today = get_latest_features(db, prediction_date)
        if df_today.empty:
            return {"error": "Données insuffisantes pour la prédiction"}

        df_needs, _ = identify_needs_and_surpluses(df_today, model, feature_cols)

        # Filtrer par sévérité
        if severity_filter != "tous":
            df_needs = df_needs[df_needs["severity"] == severity_filter]

        predictions = []
        for _, row in df_needs.iterrows():
            predictions.append({
                "hospital": row["hospital_name"],
                "region": row["region"],
                "blood_type": row["blood_type"],
                "product_type": row["product_type"],
                "current_stock": int(row["quantity"]),
                "minimum_threshold": int(row["minimum_threshold"]),
                "shortage_probability": round(float(row["shortage_proba"]), 3),
                "severity": row["severity"],
                "predicted_for": str(prediction_date + timedelta(days=3))
            })

        # Trier par probabilité décroissante
        predictions.sort(key=lambda x: x["shortage_probability"], reverse=True)

        return {
            "prediction_date": str(prediction_date),
            "total_risks": len(predictions),
            "critique": len([p for p in predictions if p["severity"] == "critique"]),
            "modere": len([p for p in predictions if p["severity"] == "modere"]),
            "faible": len([p for p in predictions if p["severity"] == "faible"]),
            "predictions": predictions[:20]  # Top 20 pour ne pas surcharger
        }

    finally:
        db.close()


def get_transfer_suggestions_tool(urgency_filter: str = "tous") -> dict:
    """
    Lance le moteur de transfert et retourne les suggestions.
    """
    suggestions = run_transfer_engine()

    if urgency_filter != "tous":
        suggestions = [s for s in suggestions if s["urgency"] == urgency_filter]

    return {
        "total_suggestions": len(suggestions),
        "suggestions": suggestions
    }


def get_network_summary() -> dict:
    """
    Résumé global du réseau de banques de sang.
    """
    db = SessionLocal()
    try:
        # Stock total par produit
        stock_query = """
        SELECT
            product_type,
            SUM(quantity) as total_units,
            SUM(CASE WHEN quantity < minimum_threshold THEN 1 ELSE 0 END) as shortage_count,
            COUNT(*) as total_records,
            ROUND(AVG(CASE WHEN quantity < minimum_threshold
                      THEN 1.0 ELSE 0.0 END) * 100, 1) as pct_shortage
        FROM stocks
        WHERE date = (SELECT MAX(date) FROM stocks)
        GROUP BY product_type
        ORDER BY product_type
        """
        df_stock = pd.read_sql(text(stock_query), db.bind)

        # Hôpitaux critiques
        critical_query = """
        SELECT h.name, COUNT(*) as nb_critical
        FROM stocks s
        JOIN hospitals h ON s.hospital_id = h.id
        WHERE s.date = (SELECT MAX(date) FROM stocks)
        AND s.quantity < s.minimum_threshold
        GROUP BY h.name
        ORDER BY nb_critical DESC
        """
        df_critical = pd.read_sql(text(critical_query), db.bind)

        # Péremptions imminentes
        expiry_query = """
        SELECT h.name, SUM(s.expiring_soon) as expiring
        FROM stocks s
        JOIN hospitals h ON s.hospital_id = h.id
        WHERE s.date = (SELECT MAX(date) FROM stocks)
        AND s.expiring_soon > 0
        GROUP BY h.name
        ORDER BY expiring DESC
        LIMIT 5
        """
        df_expiry = pd.read_sql(text(expiry_query), db.bind)

        return {
            "last_update": str(pd.read_sql(
                text("SELECT MAX(date) FROM stocks"), db.bind
            ).iloc[0, 0]),
            "stock_by_product": df_stock.to_dict("records"),
            "critical_hospitals": df_critical.to_dict("records"),
            "expiring_soon_hospitals": df_expiry.to_dict("records"),
            "total_hospitals": db.query(Hospital).count()
        }

    finally:
        db.close()


# ─────────────────────────────────────────────────────
# DISPATCHER D'OUTILS
# ─────────────────────────────────────────────────────

def execute_tool(tool_name: str, tool_input: dict) -> str:
    """
    Exécute l'outil demandé par Claude et retourne le résultat en JSON.

    C'est le "pont" entre Claude et nos fonctions Python.
    Claude dit "j'appelle get_hospital_status avec ces paramètres"
    et cette fonction fait le vrai appel Python.
    """
    logger.info(f"🔧 Outil appelé : {tool_name} | Params : {tool_input}")

    try:
        if tool_name == "get_hospital_status":
            result = get_hospital_status(**tool_input)
        elif tool_name == "get_shortage_predictions":
            result = get_shortage_predictions(**tool_input)
        elif tool_name == "get_transfer_suggestions":
            result = get_transfer_suggestions_tool(**tool_input)
        elif tool_name == "get_network_summary":
            result = get_network_summary()
        else:
            result = {"error": f"Outil inconnu : {tool_name}"}

        return json.dumps(result, ensure_ascii=False, default=str)

    except Exception as e:
        logger.error(f"Erreur outil {tool_name} : {e}")
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────────────
# AGENT PRINCIPAL
# ─────────────────────────────────────────────────────

class BloodFlowAgent:
    """
    Agent conversationnel BloodFlow.

    Fonctionnement :
    1. L'utilisateur envoie un message
    2. On l'envoie à Claude avec les outils disponibles
    3. Claude décide s'il a besoin d'un outil
    4. Si oui → on exécute l'outil → on renvoie le résultat à Claude
    5. Claude formule sa réponse finale
    6. On mémorise la conversation pour le contexte

    Cette boucle s'appelle "agentic loop" ou "tool use loop".
    """

    def __init__(self):
        self.client = anthropic.Anthropic()
        self.conversation_history = []
        self.system_prompt = """
Tu es BloodFlow, un assistant médical spécialisé dans la gestion
des banques de sang au Sénégal.

Ton rôle est d'aider les gestionnaires de banques de sang à :
- Surveiller les niveaux de stock en temps réel
- Anticiper les pénuries grâce à l'IA prédictive
- Optimiser les transferts entre hôpitaux
- Prendre des décisions rapides pour sauver des vies

Règles de communication :
- Réponds TOUJOURS en français
- Sois direct et précis : les gestionnaires n'ont pas de temps à perdre
- Priorise clairement : commence par le plus urgent
- Utilise des emojis médicaux pour la lisibilité (🔴🟡🟢🩸🏥)
- Cite toujours les chiffres exacts (probabilités, quantités, distances)
- Si une situation est critique, dis-le clairement sans atténuer

Contexte : Tu gères un réseau de 8 hôpitaux sénégalais.
Les produits sanguins gérés sont : CGR, PFC, CPA, CPD.
La durée de vie d'une poche est de 42 jours maximum.
"""

    def chat(self, user_message: str) -> str:
        """
        Envoie un message à l'agent et retourne sa réponse.

        C'est la fonction principale à appeler depuis l'interface.
        """
        # Ajouter le message de l'utilisateur à l'historique
        self.conversation_history.append({
            "role": "user",
            "content": user_message
        })

        # Boucle agentique : Claude peut appeler plusieurs outils
        # avant de formuler sa réponse finale
        max_iterations = 5   # Sécurité : max 5 appels d'outils par message
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            # Appel à Claude
            response = self.client.messages.create(
                model="claude-opus-4-5",
                max_tokens=2048,
                system=self.system_prompt,
                tools=TOOLS,
                messages=self.conversation_history
            )

            # ── Cas 1 : Claude veut utiliser un outil ──
            if response.stop_reason == "tool_use":

                # Ajouter la réponse de Claude (avec tool_use) à l'historique
                self.conversation_history.append({
                    "role": "assistant",
                    "content": response.content
                })

                # Exécuter chaque outil demandé par Claude
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        logger.info(f"  Claude utilise : {block.name}")
                        tool_result = execute_tool(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": tool_result
                        })

                # Renvoyer les résultats des outils à Claude
                self.conversation_history.append({
                    "role": "user",
                    "content": tool_results
                })

                # Continuer la boucle : Claude va maintenant
                # formuler sa réponse avec les données reçues

            # ── Cas 2 : Claude a une réponse finale ────
            elif response.stop_reason == "end_turn":
                final_response = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        final_response += block.text

                # Ajouter la réponse finale à l'historique
                self.conversation_history.append({
                    "role": "assistant",
                    "content": final_response
                })

                return final_response

            else:
                return f"Stop reason inattendu : {response.stop_reason}"

        return "Nombre maximum d'itérations atteint."

    def reset_conversation(self):
        """Remet la conversation à zéro (nouvelle session)."""
        self.conversation_history = []
        logger.info("Conversation réinitialisée")


# ─────────────────────────────────────────────────────
# INTERFACE LIGNE DE COMMANDE
# ─────────────────────────────────────────────────────

def run_cli():
    """
    Interface conversationnelle en ligne de commande.
    Permet de tester l'agent avant de brancher le dashboard.
    """
    print("\n" + "="*60)
    print("🩸 BloodFlow Agent — Sénégal")
    print("="*60)
    print("Tapez 'quitter' pour terminer")
    print("Tapez 'reset' pour nouvelle conversation")
    print("="*60 + "\n")

    agent = BloodFlowAgent()

    # Message de bienvenue automatique
    print("Agent : Initialisation en cours...\n")
    welcome = agent.chat(
        "Bonjour, donne moi un résumé rapide "
        "de la situation du réseau aujourd'hui."
    )
    print(f"🤖 Agent :\n{welcome}\n")

    # Boucle de conversation
    while True:
        try:
            user_input = input("Vous : ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nAu revoir !")
            break

        if not user_input:
            continue

        if user_input.lower() == "quitter":
            print("Au revoir !")
            break

        if user_input.lower() == "reset":
            agent.reset_conversation()
            print("Conversation réinitialisée.\n")
            continue

        print("\n🤖 Agent : (réflexion en cours...)\n")
        response = agent.chat(user_input)
        print(f"🤖 Agent :\n{response}\n")
        print("-"*60)


if __name__ == "__main__":
    run_cli()