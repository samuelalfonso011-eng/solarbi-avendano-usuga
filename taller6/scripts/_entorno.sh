# Carga un archivo KEY=VALUE (formato docker/kubernetes, valores sin comillas) en el entorno.
cargar_env() {
  local k v
  while IFS='=' read -r k v; do
    [[ -z "$k" || "$k" == \#* ]] && continue
    export "$k=${v%$'\r'}"
  done < "$1"
}
