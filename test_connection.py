import psycopg
import traceback

try:
    conn = psycopg.connect(
        host="127.0.0.1",
        port=5432,
        dbname="bloodflow_db",
        user="bloodflow",
        password="bloodflow123"
    )
    print("✅ Connexion réussie !")
    conn.close()
except Exception as e:
    print(f"❌ {e}")
    traceback.print_exc()