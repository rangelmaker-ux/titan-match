#!/bin/bash
# Instalador do Titan Match (macOS) — instala no seu usuário.
#   Python embutido + app em ~/Library/Application Support/TitanMatch
#   Atalho em DaVinci Resolve > Workspace > Scripts > Color > Titan Match
# Dois cliques neste arquivo (se o macOS bloquear: botão direito > Abrir).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PAYLOAD="$HERE/Arquivos"
ROOT="$HOME/Library/Application Support/TitanMatch"
SCRIPTS="$HOME/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Color"
LAUNCHER="$SCRIPTS/Titan Match.py"
VERSAO="$(tr -d '[:space:]' < "$PAYLOAD/app/VERSION")"

remover() {
  rm -rf "$ROOT/python" "$ROOT/app"
  rm -f "$LAUNCHER"
  echo "Titan Match removido. Sua licença e configurações foram mantidas."
}

if [[ "${1:-}" == "--remover" ]]; then remover; exit 0; fi

echo "Titan Match $VERSAO — instalando…"
for p in "python/bin/python3" "app/titan_match/__init__.py" "app/templates" "Titan Match.py"; do
  [[ -e "$PAYLOAD/$p" ]] || { echo "Pacote incompleto. Extraia o ZIP inteiro antes de instalar."; exit 1; }
done
if pgrep -f "$ROOT/python/bin/python3 -m titan_match" >/dev/null 2>&1; then
  echo "Feche a janela do Titan Match antes de instalar."; exit 1
fi
mkdir -p "$ROOT"
if [[ -d "$ROOT/app" ]]; then
  BK="$ROOT/backups/instalador-$(date +%Y%m%d-%H%M%S)"; mkdir -p "$BK"; cp -R "$ROOT/app" "$BK/"
fi
rm -rf "$ROOT/python" "$ROOT/app"
cp -R "$PAYLOAD/python" "$ROOT/python"
cp -R "$PAYLOAD/app" "$ROOT/app"
# Arquivos baixados da internet ficam em quarentena; o Python embutido não é assinado pela Apple.
xattr -dr com.apple.quarantine "$ROOT" 2>/dev/null || true
mkdir -p "$SCRIPTS"
sed "s|__TITAN_MATCH_ROOT__|$ROOT|" "$PAYLOAD/Titan Match.py" > "$LAUNCHER"
# Pasta de LUTs: a mestre do Resolve fica em /Library (precisa de senha de administrador).
MASTER_LUT="/Library/Application Support/Blackmagic Design/DaVinci Resolve/LUT/Titan Match"
if [[ ! -d "$MASTER_LUT" ]]; then
  echo "Criando a pasta de LUTs do Titan Match no DaVinci (pode pedir sua senha)…"
  sudo mkdir -p "$MASTER_LUT" && sudo chown "$USER" "$MASTER_LUT" || echo "Aviso: não foi possível criar $MASTER_LUT."
fi
echo
echo "Titan Match $VERSAO instalado!"
echo "No DaVinci Resolve: página Color > Workspace > Scripts > Titan Match."
