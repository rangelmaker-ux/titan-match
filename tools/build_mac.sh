#!/bin/bash
# Monta o instalador macOS do Titan Match com Python embutido. RODAR NUM MAC:
#   bash tools/build_mac.sh            (gera para a arquitetura do Mac atual)
#   ARCH=x86_64 bash tools/build_mac.sh (Intel)    ARCH=aarch64 bash tools/build_mac.sh (Apple Silicon)
# Saída: dist/Titan-Match-macOS-<arch>-<versão>.zip
#
# Python portátil: python-build-standalone (projeto da Astral, usado pelo uv), variante
# "install_only", que inclui Tkinter. Versão/data fixadas abaixo — atualize conscientemente.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY_VERSION="3.12.8"
PBS_DATE="20241219"
ARCH="${ARCH:-$(uname -m | sed 's/arm64/aarch64/')}"
URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_DATE}/cpython-${PY_VERSION}+${PBS_DATE}-${ARCH}-apple-darwin-install_only.tar.gz"
VER="$(PYTHONPATH="$REPO/src" python3 -c 'import titan_match; print(titan_match.__version__)')"
OUT="$REPO/build/Titan-Match-macOS"
ARQ="$OUT/Arquivos"
echo "Titan Match $VER | $ARCH"
rm -rf "$OUT"; mkdir -p "$ARQ"

# 1) Python portátil
curl -fL --retry 3 -o "$OUT/python.tar.gz" "$URL"
tar -xzf "$OUT/python.tar.gz" -C "$ARQ"   # cria Arquivos/python/
rm "$OUT/python.tar.gz"
PY="$ARQ/python/bin/python3"
"$PY" -m pip install --disable-pip-version-check -q -r "$REPO/requirements.txt"
"$PY" -m pip uninstall -y -q pip || true
find "$ARQ/python" -name __pycache__ -type d -prune -exec rm -rf {} +
rm -rf "$ARQ/python/lib/python3.12/test"

# 2) App
mkdir -p "$ARQ/app/templates" "$ARQ/app/assets"
rsync -a --exclude __pycache__ "$REPO/src/titan_match" "$ARQ/app/"
cp "$REPO"/templates/*.drx "$REPO"/templates/*.json "$ARQ/app/templates/" 2>/dev/null || cp "$REPO"/templates/*.drx "$ARQ/app/templates/"
find "$REPO/assets" -maxdepth 1 -type f ! -name '_*' -exec cp {} "$ARQ/app/assets/" \;
echo "$VER" > "$ARQ/app/VERSION"; echo "$VER" > "$ARQ/app/INSTALLER_VERSION"

# 3) Instalador
cp "$REPO/installer/mac/Titan Match.py" "$ARQ/"
cp "$REPO/installer/mac/Instalar_Titan_Match.command" "$OUT/"
chmod +x "$OUT/Instalar_Titan_Match.command"
cp "$REPO/installer/mac/LEIA-ME.txt" "$OUT/"

# 4) Teste rápido
"$PY" -c "import tkinter, numpy, PIL, cv2; print('deps ok', numpy.__version__, cv2.__version__)"

# 5) ZIP (ditto preserva permissões de execução)
mkdir -p "$REPO/dist"
ZIP="$REPO/dist/Titan-Match-macOS-${ARCH}-${VER}.zip"
rm -f "$ZIP"
(cd "$REPO/build" && ditto -c -k --sequesterRsrc --keepParent "Titan-Match-macOS" "$ZIP")
echo "OK: $ZIP ($(du -h "$ZIP" | cut -f1))"
