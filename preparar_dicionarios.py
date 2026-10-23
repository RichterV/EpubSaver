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
# do pyspellchecker: frequências do inglês e as palavras de outros idiomas que não são "corrigidas"
for idioma in sorted({"en"} | {i for v in ce.ESTRANGEIROS.values() for i in v}):
    arq = Path(spellchecker.__file__).parent / "resources" / f"{idioma}.json.gz"
    shutil.copy(arq, build / "spellchecker" / arq.name)
    print(f"    {arq.name:12s} {arq.stat().st_size / 1e6:6.1f} MB")
