#!/usr/bin/env bash
# corrigir-epub — criado por Vinicius Richter.
#
# Gera dist/corrigir-epub: executável Linux de arquivo único, com interface
# gráfica e dicionários (pt-BR, en_US, en_GB) embutidos — funciona offline.
#
# Requisitos: uv (https://docs.astral.sh/uv/) e o Tk do sistema
# (sudo apt install python3-tk). O uv baixa o PyInstaller e as dependências num
# ambiente isolado. O Python do sistema é usado porque o Tk dele tem Xft (fontes
# suavizadas); o Python gerenciado pelo uv tem um Tk sem Xft, com letras
# serrilhadas e sem caracteres como "…".
#
#   ./build.sh            # gera dist/corrigir-epub
#   ./dist/corrigir-epub  # abre o seletor de arquivo
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"

NOME=corrigir-epub
BUILD="$PWD/build"
DIST="$PWD/dist"

if ! command -v uv >/dev/null 2>&1; then
    echo "Erro: o 'uv' não está instalado." >&2
    echo "Instale com: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
fi

UV_RUN=(uv run --no-project --python-preference only-system --python /usr/bin/python3
        --with lxml --with pyspellchecker)

echo "==> Verificando o Python do sistema com Tk"
"${UV_RUN[@]}" python -c "import tkinter, lxml, spellchecker" \
    || { echo "Erro: o Python do sistema não tem tkinter. Instale com: sudo apt install python3-tk" >&2; exit 1; }
TKINTER="$("${UV_RUN[@]}" python -c 'import _tkinter; print(_tkinter.__file__)')"
ldd "$TKINTER" | grep -q libXft \
    || echo "Aviso: o Tk do sistema não usa Xft; as letras da interface ficarão serrilhadas." >&2

echo "==> Preparando dicionários"
"${UV_RUN[@]}" python preparar_dicionarios.py "$BUILD"

echo "==> Gerando o executável (PyInstaller)"
"${UV_RUN[@]}" --with pyinstaller pyinstaller \
    --noconfirm --clean --onefile --windowed \
    --name "$NOME" \
    --distpath "$DIST" \
    --workpath "$BUILD/pyinstaller" \
    --specpath "$BUILD" \
    --add-data "$BUILD/dicionarios:dicionarios" \
    --add-data "$BUILD/spellchecker:spellchecker/resources" \
    --add-data "$PWD/icone:icone" \
    --log-level WARN \
    corrigir_epub_gui.py

echo
echo "Pronto: $DIST/$NOME ($(du -h "$DIST/$NOME" | cut -f1))"
echo "Execute com: $DIST/$NOME"
