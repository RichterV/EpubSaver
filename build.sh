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
rm -rf "$BUILD/dicionarios" "$BUILD/spellchecker"
mkdir -p "$BUILD/dicionarios" "$BUILD/spellchecker"
"${UV_RUN[@]}" python - "$BUILD" <<'EOF'
import shutil
import sys
from pathlib import Path

import spellchecker

import corrigir_epub as ce

build = Path(sys.argv[1])
ce.DIR_EMBUTIDO = build / "inexistente"  # força usar cache/download, não uma cópia antiga
arquivos = [(ce.URL_LIBREOFFICE + h + ext, ce.DIR_CACHE / (h.split("/")[-1] + ext))
            for idioma in (ce.PT, ce.EN) for h in idioma.hunspell for ext in (".aff", ".dic")]
arquivos.append((ce.URL_ICF, ce.DIR_CACHE / "icf"))
for url, cache in arquivos:
    origem = ce.baixar(url, cache)
    shutil.copy(origem, build / "dicionarios" / cache.name)
    print(f"    {cache.name:12s} {origem.stat().st_size / 1e6:6.1f} MB")
# do pyspellchecker só o inglês é usado (frequências do inglês)
en = Path(spellchecker.__file__).parent / "resources" / "en.json.gz"
shutil.copy(en, build / "spellchecker" / en.name)
print(f"    {en.name:12s} {en.stat().st_size / 1e6:6.1f} MB")
EOF

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
    --add-data "$BUILD/spellchecker/en.json.gz:spellchecker/resources" \
    --log-level WARN \
    corrigir_epub_gui.py

echo
echo "Pronto: $DIST/$NOME ($(du -h "$DIST/$NOME" | cut -f1))"
echo "Execute com: $DIST/$NOME"
