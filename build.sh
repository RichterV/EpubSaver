#!/usr/bin/env bash
# corrigir-epub — criado por Vinicius Richter.
#
# Gera dist/corrigir-epub: executável Linux de arquivo único, com interface
# gráfica e dicionários (pt-BR, en_US, en_GB) embutidos — funciona offline.
#
# Requisito: uv (https://docs.astral.sh/uv/). Ele baixa o Python (com Tk), o
# PyInstaller e as dependências num ambiente isolado; nada é instalado no sistema.
#
#   ./build.sh            # gera dist/corrigir-epub
#   ./dist/corrigir-epub  # abre o seletor de arquivo
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"

PYTHON_VERSAO=3.12
NOME=corrigir-epub
BUILD="$PWD/build"
DIST="$PWD/dist"

if ! command -v uv >/dev/null 2>&1; then
    echo "Erro: o 'uv' não está instalado." >&2
    echo "Instale com: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
fi

# Python gerenciado pelo uv: o do sistema (Ubuntu) costuma vir sem tkinter
UV_RUN=(uv run --no-project --python-preference only-managed --python "$PYTHON_VERSAO"
        --with lxml --with pyspellchecker)

echo "==> Verificando Python $PYTHON_VERSAO com Tk"
"${UV_RUN[@]}" python -c "import tkinter, lxml, spellchecker" \
    || { echo "Erro: o Python do uv não tem tkinter/lxml/pyspellchecker." >&2; exit 1; }

echo "==> Preparando dicionários"
"${UV_RUN[@]}" python preparar_dicionarios.py "$BUILD"

echo "==> Gerando o executável (PyInstaller)"
# as bibliotecas do Tcl/Tk ficam no lib/ do Python do uv; o PyInstaller precisa achá-las
PY_LIB="$("${UV_RUN[@]}" python -c 'import sys; print(sys.base_prefix)')/lib"
LD_LIBRARY_PATH="$PY_LIB${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
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
