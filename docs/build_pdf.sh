#!/usr/bin/env bash
# Reconstruye el PDF final (docs/PDF_final.pdf) a partir de las piezas en docs/.
# Requiere: pandoc, wkhtmltopdf.
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'EOF'
import re
with open("PDF_final.md", encoding="utf-8") as f:
    content = f.read()
def include_file(match):
    with open(match.group(1), encoding="utf-8") as f:
        return f.read()
merged = re.sub(r"INCLUDE:(\S+)", include_file, content)
with open("PDF_final_merged.md", "w", encoding="utf-8") as f:
    f.write(merged)
EOF

pandoc PDF_final_merged.md -o PDF_final.html --standalone --metadata title="SolarBI Pascual" -c style.css
wkhtmltopdf --enable-local-file-access \
  --margin-top 15mm --margin-bottom 15mm --margin-left 15mm --margin-right 15mm \
  PDF_final.html PDF_final.pdf

echo "Generado: docs/PDF_final.pdf"
