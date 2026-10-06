#!/usr/bin/env bash
# ==============================================================================
# Script de Instalación para ollama_local_chat_memory
# Permite usar 'ollama_local_chat_memory' como comando global del sistema
# ==============================================================================

set -e

PROJECT_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
CLI_DIR="$PROJECT_ROOT/CLI"
BIN_DIR="$HOME/.local/bin"
VENV_DIR="$CLI_DIR/.venv"
TARGET_BIN="$BIN_DIR/ollama_local_chat_memory"

echo "🧠 Instalando 'ollama_local_chat_memory'..."

mkdir -p "$BIN_DIR"

# 1. Crear entorno virtual aislado en CLI/.venv
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 Creando entorno virtual aislado en $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi

# 2. Instalar dependencias del CLI
echo "⬇️  Instalando dependencias (httpx, rich)..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -r "$CLI_DIR/requirements.txt"
"$VENV_DIR/bin/pip" install --quiet -e "$CLI_DIR"

# 3. Crear enlace/envoltorio ejecutable en ~/.local/bin
echo "🔗 Registrando ejecutable en $TARGET_BIN..."
cat << 'EOF' > "$TARGET_BIN"
#!/usr/bin/env bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
CLI_VENV="/home/sr-platano/Documentos/Projects/Harness/Memory_Ollama/CLI/.venv"

if [ -f "$CLI_VENV/bin/ollama_local_chat_memory" ]; then
    exec "$CLI_VENV/bin/ollama_local_chat_memory" "$@"
else
    # Fallback buscando el python del sistema
    python3 -m app.main "$@"
fi
EOF

chmod +x "$TARGET_BIN"

echo "✅ ¡Instalación completada con éxito!"
echo ""
echo "Ya puedes ejecutar desde cualquier lugar de tu terminal:"
echo "   ollama_local_chat_memory"
echo ""
echo "O usar los comandos directos:"
echo "   ollama_local_chat_memory list"
echo "   ollama_local_chat_memory create"
echo "   ollama_local_chat_memory chat <id_sesion>"
echo "   ollama_local_chat_memory delete <id_sesion>"
echo "   ollama_local_chat_memory clear <id_sesion>"
