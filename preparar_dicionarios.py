"""
Copia os dicionários para <build>/dicionarios e <build>/spellchecker, de onde
o build.sh (Linux) e o build.ps1 (Windows) os embutem no executável.

Uso: python preparar_dicionarios.py <pasta-de-build>
"""

import shutil
import sys
from pathlib import Path

import spellchecker

import corrigir_epub as ce

build = Path(sys.argv[1])
for pasta in ("dicionarios", "spellchecker"):
    shutil.rmtree(build / pasta, ignore_errors=True)
    (build / pasta).mkdir(parents=True)

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
