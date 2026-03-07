#!/bin/bash
# scripts/start.sh
# Script de démarrage en production
# Exécuté par Render avant de lancer uvicorn

echo "🚀 Démarrage BloodFlow API..."

# Créer les tables si elles n'existent pas
echo "📦 Initialisation de la base de données..."
python -m src.api.init_db

# Vérifier si des données existent déjà
python -c "
from src.api.database import SessionLocal
from src.api.models import Hospital
db = SessionLocal()
count = db.query(Hospital).count()
db.close()
print(f'Hôpitaux en base : {count}')
if count == 0:
    print('Génération des données...')
    import subprocess
    subprocess.run(['python', '-m', 'src.data_generation.ode_generator'])
else:
    print('Données déjà présentes, skip génération.')
"

# Lancer l'API
echo "✅ Lancement de l'API..."
uvicorn src.api.main:app --host 0.0.0.0 --port $PORT