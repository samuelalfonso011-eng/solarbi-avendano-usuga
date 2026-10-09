import os
import subprocess

# Define the repository name
repo_name = "solarbi-avendano-usuga"

# Define authors
author1_name = "Samuel Alfonso Avendano"
author1_email = "samuel.alfonso011@pascualbravo.edu.co"
author2_name = "Juan Andres Usuga"
author2_email = "juan.usuga547@pascualbravo.edu.co"

# Initialize git
subprocess.run(["git", "init"], check=True)

# Function to make a commit
def make_commit(author_name, author_email, files, message):
    subprocess.run(["git", "config", "user.name", author_name], check=True)
    subprocess.run(["git", "config", "user.email", author_email], check=True)
    
    for f in files:
        subprocess.run(["git", "add", f], check=True)
        
    subprocess.run(["git", "commit", "-m", message], check=True)

# Commits for Samuel (Integrante 1)
make_commit(author1_name, author1_email, ["etl/simulador.py", "data/bronze/lecturas_bronze.csv"], "feat: implementa simulador de telemetria con anomalias controladas")
make_commit(author1_name, author1_email, ["etl/run_etl.py", "data/silver/lecturas_silver.csv"], "feat: agrega validaciones de calidad y ETL idempotente (Bronze-Silver-Gold)")
make_commit(author1_name, author1_email, ["sql/tables.sql", "sql/cargas.sql"], "feat: crea tablas y cargas UPSERT de PostgreSQL (silver y dwh)")

# Commits for Juan (Integrante 2)
make_commit(author2_name, author2_email, ["powerbi/medidas_dax.md", ".env.example"], "feat: configura medidas DAX y pagina de Power BI")
make_commit(author2_name, author2_email, ["grafana/dashboard.json", "requirements.txt"], "feat: agrega dashboard de Grafana y ruta alternativa documentada")
make_commit(author2_name, author2_email, ["docs/*", "README.md", ".gitignore"], "docs: actualiza README, .gitignore y evidencias de la Parte C")

print("Git commits creados exitosamente.")
