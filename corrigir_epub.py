#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["lxml", "pyspellchecker"]
# ///
"""
corrigir_epub — criado por Vinicius Richter.

Corrige inconsistências comuns em EPUBs em português ou inglês (especialmente
os gerados a partir de PDF/OCR, como pdftohtml + calibre).

O idioma é detectado automaticamente pelo texto (e o dc:language é corrigido se
estiver errado); dicionário, regras de pontuação e nomes de capítulos são
aplicados conforme o idioma. Em outros idiomas só as correções estruturais e de
espaçamento são feitas.

Correções estruturais:
  * parágrafos partidos por quebra de página do PDF são reunidos
    (inclusive palavras hifenizadas na quebra);
  * parágrafos vazios/lixo são removidos; sequências deles entre trechos de
    texto viram um separador de cena ("* * *");
  * itálicos/negritos fragmentados (<i>a</i> <i>b</i>) são unidos;
  * páginas de propaganda inseridas por sites de download são removidas;
  * <title> genérico dos capítulos ("Microsoft Word - ...") é trocado pelo
    título do livro; idioma "pt_BR" vira "pt-BR";
  * títulos de capítulo/parte que viraram parágrafos comuns ("EPÍLOGO",
    "PARTE TRÊS" + subtítulo, "Chapter 3") voltam a ser títulos;
  * sumário verificado: toc.ncx e nav.xhtml (EPUB3) com links para arquivos
    ou âncoras inexistentes, fora de ordem ou incompletos são corrigidos ou
    reconstruídos a partir dos títulos; a página de sumário do próprio livro
    ganha links (ou tem os links quebrados consertados); o guide do OPF
    recebe as referências de sumário e início do texto.

Correções de texto:
  * espaços duplicados, espaços antes de pontuação, depois de aspas de
    abertura etc.; espaço ausente após pontuação;
  * reticências quebradas (". . ." / ".. ." -> "...");
  * travessão de diálogo ("- Olá" -> "— Olá", "—‘ mas" -> "—, mas") [pt];
  * aspas retas -> curvas, apóstrofo reto -> ’;
  * erros de OCR (Rachei->Rachel, Eliie->Ellie, simitérío->simitério,
    SUMARIO->SUMÁRIO, parecialhe->parecia-lhe, estábem->está bem,
    tartarugas-domar->tartarugas-do-mar, "co m"->"com"), usando um
    dicionário do idioma (hunspell do LibreOffice) e o vocabulário do
    próprio livro;
  * opcionalmente, atualização para o Acordo Ortográfico (--modernizar) [pt].

Tudo que é alterado vai para um relatório, junto com uma lista de palavras
suspeitas que não puderam ser corrigidas automaticamente. Para corrigi-las,
crie um arquivo com linhas "errado=certo" e passe com --substituicoes.

Uso:
    uv run corrigir_epub.py livro.epub                 # gera livro_corrigido.epub
    uv run corrigir_epub.py livro.epub -o saida.epub --modernizar
    uv run corrigir_epub.py livro.epub --simular       # só gera o relatório
    uv run corrigir_epub.py *.epub                     # vários livros
    uv run corrigir_epub.py book.epub --idioma en      # força o idioma

(Sem o uv: pip install lxml pyspellchecker; python3 corrigir_epub.py ...)
"""

import argparse
import datetime
import math
import os
import posixpath
import re
import sys
import unicodedata
import urllib.request
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from lxml import etree

try:
    from spellchecker import SpellChecker  # frequências do inglês
except ImportError:
    SpellChecker = None

# Dicionários (baixados uma vez e guardados em cache)
#   pt_BR / en_US .aff/.dic: corretores hunspell do LibreOffice (github.com/LibreOffice/dictionaries)
#   icf: ~420 mil palavras pt-BR com frequência em corpus (github.com/fserb/pt-br, licença MIT)
#   frequências do inglês: lista do pyspellchecker
URL_LIBREOFFICE = "https://raw.githubusercontent.com/LibreOffice/dictionaries/master/"
URL_ICF = "https://raw.githubusercontent.com/fserb/pt-br/master/icf"
DIR_CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "corrigir_epub"
# no executável gerado pelo PyInstaller os dicionários vêm embutidos
DIR_EMBUTIDO = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "dicionarios"
ICF_MAXIMO = 25.0   # icf vai de ~3 (muito comum) a ~24 (vista uma vez)
ICF_CONFIAVEL = 16.0  # acima disso a palavra do corpus pode ser ela própria um erro

AUTOR = "Vinicius Richter"

NS = {
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "ncx": "http://www.daisy.org/z3986/2005/ncx/",
    "xhtml": "http://www.w3.org/1999/xhtml",
    "cont": "urn:oasis:names:tc:opendocument:xmlns:container",
}
XHTML = "{%s}" % NS["xhtml"]
NCX = "{%s}" % NS["ncx"]

LETRA = "A-Za-zÀ-ÖØ-öø-ÿ"
BLOCOS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "td", "th", "dd", "dt", "blockquote", "div"}
INLINE_MESCLAVEL = {"i", "b", "em", "strong", "span", "u", "small", "sup", "sub"}
TERMINAIS = ".!?…:;"
FECHAMENTOS = "”’\"')]»*"
MARCAS_ANUNCIO = re.compile(
    r"dlivros|lelivros|le livros|baixe livros|convertepub|converted by|"
    r"epubr\.club|e-?livros\.|livros de forma r[aá]pida|comunidade digital|"
    r"x-?livros|portal brasil|bookess|oceanofpdf|z-?library|zlibrary|libgen|"
    r"downloaded from|free ebooks? (at|from)|ebook-?hunter|epubpub",
    re.I,
)
TITULO_LIXO = re.compile(r"microsoft word|\.docx?\b|untitled|sem t[ií]tulo|^\W*$|^index", re.I)

# Confusões típicas de OCR: (trecho lido errado, trecho correto)
CONFUSOES_OCR = [
    ("i", "l"), ("l", "i"), ("í", "i"), ("í", "l"), ("l", "I"), ("I", "l"),
    ("ii", "ll"), ("ll", "ii"), ("rn", "m"), ("m", "rn"), ("cl", "d"), ("li", "h"),
    ("vv", "w"), ("1", "l"), ("1", "i"), ("0", "o"), ("e", "c"), ("c", "e"),
    ("n", "u"), ("u", "n"), ("ó", "o"), ("ô", "o"), ("é", "e"), ("ê", "e"),
    ("ç", "c"), ("ã", "a"), ("õ", "o"), ("á", "a"), ("ú", "u"),
    ("f", "fi"), ("ff", "fi"), ("ff", "ffi"), ("fl", "fi"), ("d", "cl"), ("hn", "lm"),
    ("ii", "il"), ("ii", "li"), ("j", "i"), ("J", "l"), ("â", "ã"), ("d", "ri"), ("ih", "th"),
]
# restauração de acentos perdidos (só português)
CONFUSOES_ACENTOS_PT = [
    ("i", "í"), ("a", "á"), ("a", "â"), ("a", "ã"), ("a", "à"), ("e", "é"), ("e", "ê"),
    ("o", "ó"), ("o", "ô"), ("o", "õ"), ("u", "ú"), ("c", "ç"), ("I", "Í"),
]

# Ortografia anterior ao Acordo de 1990 (só altera com --modernizar)
ACENTOS_DIFERENCIAIS = {
    "pára": "para", "péla": "pela", "pélas": "pelas", "pêlo": "pelo", "pêlos": "pelos",
    "pólo": "polo", "pólos": "polos", "pêra": "pera", "pêras": "peras",
    "vôo": "voo", "vôos": "voos", "enjôo": "enjoo", "enjôos": "enjoos", "perdôo": "perdoo",
    "abençôo": "abençoo", "magôo": "magoo", "vêem": "veem", "crêem": "creem",
    "lêem": "leem", "dêem": "deem", "relêem": "releem", "prevêem": "preveem",
    "descrêem": "descreem", "revêem": "reveem",
}
RE_DITONGO_ABERTO = re.compile(r"^(.*?)(é|ó)i(a|as|o|os|ca|cas|co|cos|de|des)$")


def remover_acento_ditongo(m):
    return (m.group(1) or "") + {"é": "e", "ó": "o"}[m.group(2)] + "i" + m.group(3)


def ortografia_nova(palavra):
    """Converte uma palavra (minúscula) para a grafia do Acordo Ortográfico."""
    if IDIOMA is not PT:
        return palavra
    p = palavra.replace("ü", "u")
    partes = p.split("-")
    novas = []
    for parte in partes:
        if parte in ACENTOS_DIFERENCIAIS:
            parte = ACENTOS_DIFERENCIAIS[parte]
        else:
            parte = RE_DITONGO_ABERTO.sub(remover_acento_ditongo, parte)
        novas.append(parte)
    return "-".join(novas)


# --------------------------------------------------------------------------
# Idiomas
# --------------------------------------------------------------------------
class Idioma:
    def __init__(self, **kw):
        self.__dict__.update(kw)


NUMEROS_PT = (
    "um|uma|dois|duas|tr[eê]s|quatro|cinco|seis|sete|oito|nove|dez|onze|doze|treze|"
    "quatorze|catorze|quinze|dezesseis|dezessete|dezoito|dezenove|vinte|trinta|"
    "primeir[oa]|segund[oa]|terceir[oa]|quart[oa]|quint[oa]|sext[oa]|s[eé]tim[oa]|oitav[oa]|non[oa]|d[eé]cim[oa]"
)
NUMEROS_EN = (
    "one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
    "fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|"
    "first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth"
)

PT = Idioma(
    codigo="pt",
    hunspell=["pt_BR/pt_BR"],
    re_palavra=re.compile(rf"[{LETRA}]+(?:-[{LETRA}]+)*"),
    confusoes=CONFUSOES_OCR + CONFUSOES_ACENTOS_PT,
    encliticos=["lhes", "lhe", "los", "las", "nos", "vos", "se", "me", "te", "lo", "la"],
    sufixos_hifen=["o", "a", "os", "as", "no", "na", "nas", "lo"],
    letras_sozinhas=set("aeoyéàóáôê"),
    palavras_curtas={"a", "o", "e", "é", "à", "de", "da", "do", "em", "no", "na", "um", "se", "me", "te",
                     "ao", "os", "as", "já", "lá", "só", "eu", "tu", "há", "nó", "vó", "pé", "ir", "vi", "ou"},
    re_parte=re.compile(rf"^(parte|livro|volume)\s+([0-9]+|[ivxlc]+|{NUMEROS_PT})\b", re.I),
    re_capitulo=re.compile(
        rf"^(cap[ií]tulo\s+([0-9]+|[ivxlc]+|{NUMEROS_PT})\b.*"
        r"|pr[oó]logo|ep[ií]logo|interl[uú]dio|introdu[cç][aã]o|pref[aá]cio|posf[aá]cio|"
        r"nota d[oa] autor[a]?|nota d[oa] tradutor[a]?|agradecimentos|ap[eê]ndice|dedicat[oó]ria|"
        r"[0-9]{1,3}|[IVXLC]{1,7})\W*$",
        re.I,
    ),
    re_pagina_sumario=re.compile(r"^\W*(sum[aá]rio|[ií]ndice|conte[uú]do)\W*$", re.I),
    minusculas={"a", "o", "as", "os", "e", "de", "do", "da", "dos", "das", "em", "no", "na",
                "nos", "nas", "por", "para", "com", "ao", "à", "aos", "às", "ou"},
    rotulos={"capa": "Capa", "sumario": "Sumário", "inicio": "Início"},
    dialogo_com_travessao=True,
    palavras_frequentes={"de", "que", "não", "uma", "para", "com", "ele", "ela", "você", "mas",
                         "os", "das", "dos", "muito", "ao", "foi", "está", "isso", "são", "também"},
)
EN = Idioma(
    codigo="en",
    hunspell=["en/en_US", "en/en_GB"],
    re_palavra=re.compile(rf"[{LETRA}]+(?:['’-][{LETRA}]+)*"),
    confusoes=CONFUSOES_OCR,
    encliticos=[],
    sufixos_hifen=[],
    letras_sozinhas=set("ai"),
    palavras_curtas={"a", "i", "an", "of", "in", "on", "at", "to", "by", "as", "is", "it", "be", "do", "go",
                     "my", "no", "so", "up", "us", "we", "he", "me", "or", "if", "am"},
    re_parte=re.compile(rf"^(part|book|volume)\s+([0-9]+|[ivxlc]+|{NUMEROS_EN})\b", re.I),
    re_capitulo=re.compile(
        rf"^(chapter\s+([0-9]+|[ivxlc]+|{NUMEROS_EN})\b.*"
        r"|prologue|epilogue|interlude|introduction|preface|foreword|afterword|"
        r"author['’]?s note|a note from the author|acknowledge?ments|appendix|dedication|"
        r"[0-9]{1,3}|[IVXLC]{1,7})\W*$",
        re.I,
    ),
    re_pagina_sumario=re.compile(r"^\W*((table of )?contents|index)\W*$", re.I),
    minusculas={"a", "an", "the", "and", "or", "but", "nor", "of", "in", "on", "at", "to", "for",
                "by", "with", "from", "as"},
    rotulos={"capa": "Cover", "sumario": "Contents", "inicio": "Start"},
    dialogo_com_travessao=False,
    palavras_frequentes={"the", "and", "of", "to", "was", "he", "she", "you", "that", "it", "with",
                         "his", "her", "for", "not", "but", "had", "this", "they", "were"},
)
# Só para não confundir espanhol com português
PALAVRAS_ES = {"el", "y", "los", "del", "pero", "muy", "más", "usted", "también", "hacia", "entonces", "ella"}
# Idioma sem regras próprias: só estrutura e espaçamento
OUTRO = Idioma(
    codigo="outro", hunspell=None, re_palavra=PT.re_palavra, confusoes=[], encliticos=[],
    sufixos_hifen=[], letras_sozinhas=set(), palavras_curtas=set(), re_parte=PT.re_parte, re_capitulo=PT.re_capitulo,
    re_pagina_sumario=re.compile(r"^\W*(sum[aá]rio|[ií]ndice|conte[uú]do|(table of )?contents|table des mati[eè]res)\W*$", re.I),
    minusculas=set(), rotulos={"capa": "Capa", "sumario": "Sumário", "inicio": "Início"},
    dialogo_com_travessao=False, palavras_frequentes=set(),
)
IDIOMAS = {"pt": PT, "en": EN}
IDIOMA = PT  # idioma do livro em processamento (definido em processar())


def detectar_idioma(textos, metadado):
    """Decide o idioma pelas palavras mais comuns do texto; o metadado só desempata."""
    contagem = Counter()
    total = 0
    for t in textos:
        for w in re.findall(rf"[{LETRA}]+", t.lower()):
            total += 1
            if w in PT.palavras_frequentes:
                contagem["pt"] += 1
            if w in EN.palavras_frequentes:
                contagem["en"] += 1
            if w in PALAVRAS_ES:
                contagem["es"] += 1
        if total > 200_000:
            break
    meta = (metadado or "").lower()[:2]
    if total < 200:
        return IDIOMAS.get(meta, OUTRO), contagem
    melhor, n = max(contagem.items(), key=lambda x: x[1], default=(None, 0))
    if n < 0.03 * total:
        return IDIOMAS.get(meta, OUTRO), contagem
    if melhor == "pt" and contagem["es"] > 0.5 * n:
        melhor = "es"
    return IDIOMAS.get(melhor, OUTRO), contagem


def aplicar_caixa(modelo, palavra):
    """Copia o padrão de maiúsculas/minúsculas de `modelo` para `palavra`."""
    if modelo.isupper() and len(modelo) > 1:
        return palavra.upper()
    if modelo[:1].isupper():
        return palavra[:1].upper() + palavra[1:]
    return palavra


def sem_acentos(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def normalizar_espacos(s):
    return re.sub(r"[ \t\r\n\f\v]+", " ", s)


# --------------------------------------------------------------------------
# Relatório
# --------------------------------------------------------------------------
class Relatorio:
    def __init__(self):
        self.contagem = Counter()
        self.palavras = Counter()  # (categoria, antes, depois) -> n
        self.exemplos = defaultdict(list)
        self.suspeitas = Counter()
        self.estrutura = []

    def registrar(self, categoria, antes=None, depois=None, n=1):
        self.contagem[categoria] += n
        if antes is not None:
            self.palavras[(categoria, antes, depois)] += n

    def exemplo(self, categoria, texto):
        if len(self.exemplos[categoria]) < 8:
            self.exemplos[categoria].append(texto)

    def texto(self, epub_entrada, epub_saida):
        linhas = [f"Relatório de correções: {epub_entrada}", f"Saída: {epub_saida}",
                  f"Gerado por corrigir_epub — criado por {AUTOR}", ""]
        if self.estrutura:
            linhas.append("== Estrutura do EPUB ==")
            linhas += [f"  - {e}" for e in self.estrutura]
            linhas.append("")
        linhas.append("== Totais por tipo de correção ==")
        for cat, n in self.contagem.most_common():
            linhas.append(f"  {n:6d}  {cat}")
        for cat, exs in self.exemplos.items():
            linhas.append(f"\n-- Exemplos: {cat} --")
            linhas += [f"    {e}" for e in exs]
        linhas.append("\n== Substituições de palavras (revise!) ==")
        for (cat, antes, depois), n in sorted(self.palavras.items(), key=lambda x: (x[0][0], -x[1], x[0][1])):
            linhas.append(f"  [{cat}] {antes!r} -> {depois!r}  ({n}x)")
        linhas.append(
            "\n== Palavras desconhecidas NÃO corrigidas (possíveis erros) ==\n"
            "   Para corrigi-las, crie um arquivo com linhas 'errado=certo' e use --substituicoes."
        )
        for w, n in sorted(self.suspeitas.items(), key=lambda x: (-x[1], x[0].lower())):
            linhas.append(f"  {w} ({n}x)")
        return "\n".join(linhas) + "\n"


# --------------------------------------------------------------------------
# Dicionário pt-BR
# --------------------------------------------------------------------------
def baixar(url, destino):
    embutido = DIR_EMBUTIDO / destino.name
    if embutido.exists():
        return embutido
    if destino.exists() and destino.stat().st_size > 0:
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    print(f"  baixando {url} ...", file=sys.stderr)
    tmp = destino.with_suffix(".tmp")
    with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
        f.write(r.read())
    tmp.replace(destino)
    return destino


class Hunspell:
    """Consulta mínima a um dicionário hunspell (afixos simples, FLAG UTF-8, como o pt_BR)."""

    def __init__(self, aff, dic):
        self.sufixos = defaultdict(list)   # trecho acrescentado -> [(flag, retirado, condição, cruza)]
        self.prefixos = defaultdict(list)
        self.proibida = None
        linhas = aff.splitlines()
        i = 0
        while i < len(linhas):
            p = linhas[i].split()
            if len(p) == 2 and p[0] == "FORBIDDENWORD":
                self.proibida = p[1]
            if len(p) == 4 and p[0] in ("SFX", "PFX") and p[2] in ("Y", "N") and p[3].isdigit():
                tipo, flag, cruza, n = p[0], p[1], p[2] == "Y", int(p[3])
                for regra in linhas[i + 1:i + 1 + n]:
                    r = regra.split()
                    retirado = "" if r[2] == "0" else r[2]
                    acrescido = r[3].split("/")[0]
                    acrescido = "" if acrescido == "0" else acrescido
                    cond = r[4] if len(r) > 4 else "."
                    if tipo == "SFX":
                        self.sufixos[acrescido].append((flag, retirado, re.compile(cond + "$"), cruza))
                    else:
                        self.prefixos[acrescido].append((flag, retirado, re.compile("^" + cond), cruza))
                i += n
            i += 1
        self.radicais = {}
        for linha in dic.splitlines()[1:]:
            w, _, flags = linha.strip().partition("/")
            if w:
                self.radicais[w] = self.radicais.get(w, "") + flags
        self.cache = {}

    def _radical(self, w, flag=None):
        flags = self.radicais.get(w)
        if flags is None or (self.proibida and self.proibida in flags):
            return False
        return flag is None or flag in flags

    def _sem_sufixo(self, w, pfx_flag=None):
        if pfx_flag is None and self._radical(w):
            return True
        for n in range(1, len(w) + 1):
            for flag, retirado, cond, cruza in self.sufixos.get(w[n:], ()):
                if pfx_flag is not None and not cruza:
                    continue
                radical = w[:n] + retirado
                if cond.search(radical) and self._radical(radical, flag) and \
                        (pfx_flag is None or self._radical(radical, pfx_flag)):
                    return True
        return False

    def __contains__(self, w):
        if w in self.cache:
            return self.cache[w]
        ok = self._sem_sufixo(w)
        if not ok:
            for n in range(1, len(w)):
                for flag, retirado, cond, cruza in self.prefixos.get(w[:n], ()):
                    radical = retirado + w[n:]
                    if not cond.search(radical):
                        continue
                    if self._radical(radical, flag) or (cruza and self._sem_sufixo(radical, flag)):
                        ok = True
                        break
                if ok:
                    break
        self.cache[w] = ok
        return ok


class Dicionario:
    """Frequência das palavras do idioma: 0 = desconhecida; quanto maior, mais comum."""

    def __init__(self, idioma, extra=None):
        self.idioma = idioma
        self.freq = {}        # palavra -> (frequência 0..22, confiável)
        self.extras = set()
        self.estrangeiro = {}  # palavras de outro idioma que não devem ser "corrigidas"
        if extra:
            self.extras = {w.lower() for w in Path(extra).read_text(encoding="utf-8").split()}
        self.hunspells = []
        if idioma.hunspell is None:
            return
        for caminho in idioma.hunspell:
            try:
                base = URL_LIBREOFFICE + caminho
                nome_arq = caminho.split("/")[-1]
                aff = baixar(base + ".aff", DIR_CACHE / f"{nome_arq}.aff").read_text(encoding="utf-8", errors="replace")
                dic = baixar(base + ".dic", DIR_CACHE / f"{nome_arq}.dic").read_text(encoding="utf-8-sig", errors="replace")
                self.hunspells.append(Hunspell(aff, dic))
            except OSError as e:
                print(f"  aviso: não foi possível obter o dicionário {caminho} ({e}); "
                      "usando só o vocabulário do livro e --dicionario.", file=sys.stderr)
        ingles = SpellChecker(language="en").word_frequency.dictionary if SpellChecker else {}
        if idioma is PT:
            try:
                for linha in baixar(URL_ICF, DIR_CACHE / "icf").read_text(encoding="utf-8").splitlines():
                    w, _, icf = linha.rpartition(",")
                    if w:
                        self.freq[w] = (max(ICF_MAXIMO - float(icf), 0.5), float(icf) <= ICF_CONFIAVEL)
            except OSError as e:
                print(f"  aviso: lista de frequências pt-BR indisponível ({e})", file=sys.stderr)
            self.estrangeiro = ingles
        elif idioma is EN and ingles:
            # converte contagens para a mesma escala do icf
            maximo = max(ingles.values())
            for w, n in ingles.items():
                icf = math.log(maximo / n) + 3
                self.freq[w] = (max(ICF_MAXIMO - icf, 0.5), icf <= ICF_CONFIAVEL)

    def _valida(self, w):
        if w in self.extras:
            return True
        w = w.replace("’", "'")
        return any(w in h or w[:1].upper() + w[1:] in h for h in self.hunspells)

    def __call__(self, wl):
        """Frequência aproximada (0 se a palavra não existe)."""
        for w in (wl, ortografia_nova(wl)):
            f = self.freq.get(w.replace("’", "'"))
            if f:
                return f[0]
            if self._valida(w):
                return 3.0
        return 0

    def confiavel(self, wl):
        """Palavra que pode ser usada como correção."""
        for w in (wl, ortografia_nova(wl)):
            if self._valida(w) or self.freq.get(w.replace("’", "'"), (0, False))[1]:
                return True
        return False

    def eh_estrangeira(self, wl):
        return self.estrangeiro.get(wl, 0) >= 100 and not self.confiavel(wl)


# --------------------------------------------------------------------------
# Corretor ortográfico focado em erros de OCR
# --------------------------------------------------------------------------
class Corretor:
    def __init__(self, textos, substituicoes, modernizar, relatorio, dicionario):
        self.rel = relatorio
        self.modernizar = modernizar
        self.subs = substituicoes
        self.dic = dicionario

        self.cont = Counter()       # forma exata
        self.cont_min = Counter()   # minúsculas
        self.bigramas = Counter()
        self.sem_hifen = defaultdict(Counter)
        for t in textos:
            anterior = None
            for m in IDIOMA.re_palavra.finditer(t):
                w = m.group()
                wl = w.lower()
                self.cont[w] += 1
                self.cont_min[wl] += 1
                if "-" in w:
                    self.sem_hifen[wl.replace("-", "")][wl] += 1
                if anterior:
                    self.bigramas[(anterior, wl)] += 1
                anterior = wl
        self.cache = {}

    # -- consultas -------------------------------------------------------
    def freq_dic(self, wl):
        return self.dic(wl)

    def conhecida(self, wl, minimo_livro=3):
        if self.freq_dic(wl) or self.dic.eh_estrangeira(wl):
            return True
        if self.cont_min[wl] >= minimo_livro:
            return True
        if "-" in wl:
            partes = wl.split("-")
            return all(self.parte_conhecida(p, i) for i, p in enumerate(partes))
        return False

    def parte_conhecida(self, p, indice):
        if indice > 0 and p in IDIOMA.encliticos + IDIOMA.sufixos_hifen:
            return True
        if self.freq_dic(p) or self.cont_min[p] >= 3:
            return True
        return indice == 0 and IDIOMA is PT and self.verbo_com_enclise(p)

    def verbo_com_enclise(self, p):
        """'chamá' (de chamá-lo) -> chamar; 'fazê' -> fazer; 'pô' -> pôr."""
        if len(p) < 2 or p[-1] not in "áâéêíóô":
            return False
        base = p[:-1] + {"á": "ar", "â": "ar", "é": "er", "ê": "er", "í": "ir", "ó": "or", "ô": "or"}[p[-1]]
        return bool(self.freq_dic(base)) or p == "pô"

    def aceitavel(self, wl):
        """Pode ser usada como correção: palavra confiável do dicionário ou presente no livro."""
        return self.dic.confiavel(wl) or self.cont_min[wl] >= 2

    def pontuacao(self, wl):
        return self.cont_min[wl] * 100 + self.freq_dic(wl)

    # -- geração de candidatos ------------------------------------------
    def variantes_ocr(self, w, profundidade=2):
        resultado = set()
        fronteira = {w}
        for _ in range(profundidade):
            nova = set()
            for x in fronteira:
                for errado, certo in IDIOMA.confusoes:
                    inicio = x.find(errado)
                    while inicio != -1:
                        v = x[:inicio] + certo + x[inicio + len(errado):]
                        if v != w:
                            nova.add(v)
                        inicio = x.find(errado, inicio + 1)
            resultado |= nova
            fronteira = nova
        return resultado

    def candidato(self, w):
        """Retorna (correção, categoria) para a palavra w, ou (None, None)."""
        if w in self.cache:
            return self.cache[w]
        r = self._candidato(w)
        self.cache[w] = r
        return r

    def _candidato(self, w):
        wl = w.lower()
        if any(ch.isdigit() for ch in w) or len(w) < 2:
            return None, None
        # Maiúsculas no meio da palavra (siglas, McCartney...) -> não mexe
        if not w.isupper() and any(c.isupper() for c in w[1:]) and "-" not in w:
            return None, None
        maiuscula = w[:1].isupper() and not w.isupper()

        # 1) Nome próprio lido errado: "Rachei" quando "Rachel" aparece 300x
        if maiuscula and len(w) >= 4:
            n = self.cont[w]
            melhor = None
            for v in self.variantes_ocr(w, 1):
                nv = self.cont[v]
                if nv >= 15 and nv >= 10 * n and v[:1].isupper():
                    if self.cont_min[wl] - n <= max(1, 0.2 * n):  # quase nunca aparece em minúsculas
                        if melhor is None or nv > self.cont[melhor]:
                            melhor = v
            if melhor:
                return melhor, "OCR (nome próprio)"

        # Em MAIÚSCULAS o acento costuma se perder: EPILOGO -> EPÍLOGO
        if w.isupper() and len(w) >= 4 and IDIOMA is PT:
            base = sem_acentos(wl)
            f = self.freq_dic(wl)
            cands = [v for v in self.variantes_ocr(wl, 2) if sem_acentos(v) == base
                     and self.dic.confiavel(v) and self.freq_dic(v) >= f + 4]
            if cands:
                return aplicar_caixa(w, max(cands, key=self.pontuacao)), "OCR/acentuação"

        if self.conhecida(wl):
            return None, None

        # Palavras curtas são ambíguas demais: só corrige para palavra muito comum
        # no livro (ja -> já, nã -> na, Ihe -> The)
        if len(wl) <= 3:
            cands = [v for v in self.variantes_ocr(wl, 1)
                     if self.cont_min[v] >= 20 and self.cont_min[v] >= 10 * self.cont_min[wl] and self.dic.confiavel(v)]
            if cands:
                v = max(cands, key=self.pontuacao)
                return aplicar_caixa(w, v), "OCR/acentuação"
            return None, None

        cands = []
        # 2) hífen no lugar errado: tartarugas-domar -> tartarugas-do-mar
        chave = wl.replace("-", "")
        for forma, n in self.sem_hifen.get(chave, {}).items():
            if forma != wl:
                cands.append((n * 100, forma, "hífen"))
        if cands:
            return self._escolher(w, cands)

        # 3) confusões de OCR / acento perdido
        acentos_w = sum(1 for c in wl if c in "áéóúâêôãõàç")
        variantes = self.variantes_ocr(wl)
        if IDIOMA is PT and len(wl) <= 5 and any(self.dic.estrangeiro.get(v, 0) >= 1000 for v in variantes):
            return None, None  # provavelmente inglês lido errado (roil -> roll)
        for v in variantes:
            if not self.aceitavel(v):
                continue
            # tirar um acento legítimo (não o "í" típico de ruído) só se a forma sem acento existir no livro
            if sum(1 for c in v if c in "áéóúâêôãõàç") < acentos_w and sem_acentos(v) == sem_acentos(wl) \
                    and not self.cont_min[v]:
                continue
            # palavra com maiúscula (nome, estrangeira, início de frase): só
            # aceita correção que também apareça no próprio livro
            if maiuscula and self.cont_min[v] < 2:
                continue
            cands.append((self.pontuacao(v), v, "OCR/acentuação"))
        # variante com maiúscula vinda do livro (nomes)
        if maiuscula:
            for v in self.variantes_ocr(w):
                if self.cont[v] >= 3:
                    cands.append((self.cont[v] * 100, v, "OCR (nome próprio)"))

        # 4) palavras coladas: estábem -> está bem, atélá -> até lá. Só se não houver
        #    correção de OCR, ou se a palavra tiver dois acentos (impossível numa palavra só)
        acentos = sum(1 for c in wl if c in "áéíóúâêôãõà")
        if "-" not in wl and len(wl) >= 5 and not maiuscula and (not cands or acentos >= 2):
            for i in range(1, len(wl)):
                a, b = wl[:i], wl[i:]
                if len(a) == 1 and a not in IDIOMA.letras_sozinhas:
                    continue
                if len(b) == 1 and b not in IDIOMA.letras_sozinhas:
                    continue
                if self.dic.confiavel(a + "-" + b):
                    cands.append((200 + self.freq_dic(a + "-" + b), a + "-" + b, "hífen"))
                    continue
                if not (self.dic.confiavel(a) and self.dic.confiavel(b)):
                    continue
                if any(len(x) <= 2 and x not in IDIOMA.palavras_curtas for x in (a, b)):
                    continue
                bi = self.bigramas[(a, b)]
                forte = min(self.freq_dic(a), self.freq_dic(b)) >= 15 and len(a) >= 2 and len(b) >= 2
                if bi >= 1 or forte:
                    cands.append((bi * 100 + min(self.freq_dic(a), self.freq_dic(b)), a + " " + b, "palavras coladas"))
        if cands:
            return self._escolher(w, cands)

        # 5) palavra hifenizada: corrige parte a parte
        if "-" in wl:
            partes = w.split("-")
            novas, mudou = [], False
            for i, p in enumerate(partes):
                gagueira = i + 1 < len(partes) and partes[i + 1].lower().startswith(p.lower())
                if gagueira or self.parte_conhecida(p.lower(), i):
                    novas.append(p)
                    continue
                c, _ = self.candidato(p)
                if c and "-" not in c and " " not in c:
                    novas.append(c)
                    mudou = True
                else:
                    novas.append(p)
            if mudou:
                return "-".join(novas), "OCR/acentuação"

        # 6) hífen de ênclise perdido: parecialhe -> parecia-lhe
        for suf in IDIOMA.encliticos:
            if wl.endswith(suf) and len(wl) - len(suf) >= 3 and "-" not in wl:
                pre = wl[: -len(suf)]
                if self.dic.confiavel(pre + "-" + suf):
                    return aplicar_caixa(w, pre + "-" + suf), "hífen (ênclise)"

        return None, None

    def _escolher(self, w, cands):
        cands.sort(key=lambda c: -c[0])
        _, forma, cat = cands[0]
        if forma[:1].isupper() and w[:1].isupper() and not w.isupper():
            return forma, cat
        partes_w, partes_f = w.split("-"), forma.split("-")
        if len(partes_w) == len(partes_f) > 1:
            return "-".join(aplicar_caixa(a, b) for a, b in zip(partes_w, partes_f)), cat
        return aplicar_caixa(w, forma), cat

    # -- aplicação -------------------------------------------------------
    def corrigir_palavra(self, m):
        w = m.group()
        if w in self.subs:
            novo = self.subs[w]
            self.rel.registrar("substituição do usuário", w, novo)
            return novo
        novo, cat = self.candidato(w)
        if novo and novo != w:
            self.rel.registrar(cat, w, novo)
            w = novo
        elif not novo and not self.conhecida(w.lower()) and len(w) >= 3 \
                and not any(c.isdigit() for c in w):
            self.rel.suspeitas[w] += 1
        if self.modernizar and IDIOMA is PT:
            moderna = ortografia_nova(w.lower())
            if moderna != w.lower() and not (w[:1].isupper() and "ü" in w and self.cont_min[w.lower()] == self.cont[w]):
                nova = aplicar_caixa(w, moderna)
                self.rel.registrar("ortografia (Acordo de 1990)", w, nova)
                w = nova
        return w

    def corrigir_texto(self, s):
        # fragmentos de palavra separados por espaço: "co m" -> "com"
        def juntar_letra(m, sozinha_no_fim):
            a, b = m.group(1), m.group(2)
            sozinha = b if sozinha_no_fim else a
            if sozinha in IDIOMA.letras_sozinhas or not IDIOMA.letras_sozinhas or not (a + b).islower():
                return m.group()
            junto = a + b
            if self.dic.confiavel(junto.lower()):
                self.rel.registrar("fragmento de palavra", m.group(), junto)
                return junto
            return m.group()

        s = re.sub(rf"(?<![{LETRA}'’-])([{LETRA}]+) ([a-zà-ÿ])(?![{LETRA}'’-])", lambda m: juntar_letra(m, True), s)
        s = re.sub(rf"(?<![{LETRA}'’-])([a-zà-ÿ]) ([{LETRA}]+)(?![{LETRA}'’-])", lambda m: juntar_letra(m, False), s)

        # palavra partida em dois pedaços que não existem: "reali dade" -> "realidade"
        def juntar_pedacos(m):
            a, b = m.group(1), m.group(2)
            junto = a + b
            if len(junto) >= 5 and junto[1:].islower() and self.dic.confiavel(junto.lower()) \
                    and not (self.dic.confiavel(a.lower()) and self.dic.confiavel(b.lower())) \
                    and self.cont_min[a.lower()] < 3 and self.cont_min[b.lower()] < 3:
                self.rel.registrar("fragmento de palavra", m.group(), junto)
                return junto
            return m.group()

        s = re.sub(rf"(?<![{LETRA}'’-])([{LETRA}]{{2,}}) ([a-zà-ÿ]{{2,}})(?![{LETRA}'’-])", juntar_pedacos, s)
        return IDIOMA.re_palavra.sub(self.corrigir_palavra, s)


# --------------------------------------------------------------------------
# Tipografia (por trecho de texto)
# --------------------------------------------------------------------------
def regras_tipograficas(dialogo_com_travessao):
    r = []

    def add(cat, padrao, subst, so_travessao=False):
        if dialogo_com_travessao or not so_travessao:
            r.append((cat, re.compile(padrao), subst))

    add("caracteres invisíveis", "[­​‌‍﻿]", "")
    add("espaços duplicados", r"[ \t\r\n\f\v]{2,}", " ")
    add("reticências", r"\s*(?<!\.)\.(?: \.)+(?!\.)", "...")
    add("reticências", r"(?<!\.)\.\.+", "...")
    add("reticências", r"…", "...")
    add("travessão de diálogo", r"—\s?[‘’'`´]\s", "—, ", so_travessao=True)
    add("travessão de diálogo", r"(?<=\s)[-–](?=\s)", "—")
    add("travessão de diálogo", r"(?<=\s)--(?=\s)", "—")
    add("ponto solto", rf"(?<=[{LETRA},]) \.(?=[a-zà-ÿ])", " ")
    add("espaço antes de pontuação", r"(?<=[^\s—]) +(?=[,;:!?)\]]|\.(?!\.\.))", "")
    add("espaço antes de pontuação", r"(?<=\.\.\.) +(?=[,;:!?])", "")
    add("espaço após abertura", r"([(\[“‘]) +", r"\1")
    add("espaço antes de fechamento", r" +([”])", r"\1")
    add("espaço após pontuação", rf"(?<=[{LETRA}])([,;!?])(?=[{LETRA}“—])", r"\1 ")
    add("espaço após pontuação", r"(?<=[a-zà-ÿ]{3})\.(?=[A-ZÀ-Ý][a-zà-ÿ])", ". ")
    add("espaço após travessão", rf"(?<=\s)—(?=[{LETRA}“])", "— ", so_travessao=True)
    add("espaço antes de travessão", rf"(?<=[{LETRA}.,!?…])—(?=\s)", " —", so_travessao=True)
    add("aspas retas", r'(^|(?<=[\s(\[—]))"', "“")
    add("aspas retas", r'"', "”")
    add("apóstrofo", rf"(?<=[{LETRA}])'(?=[{LETRA}])", "’")
    return r


REGRAS = {True: regras_tipograficas(True), False: regras_tipograficas(False)}


def corrigir_tipografia(s, rel):
    for cat, padrao, subst in REGRAS[IDIOMA.dialogo_com_travessao]:
        novo, n = padrao.subn(subst, s)
        if n and novo != s:
            rel.registrar(cat, n=n)
            if cat not in ("espaços duplicados", "caracteres invisíveis"):
                rel.exemplo(cat, f"{s.strip()[:90]!r}")
            s = novo
    return s


# --------------------------------------------------------------------------
# Utilidades de árvore XHTML
# --------------------------------------------------------------------------
def nome(el):
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def slots(el):
    """Trechos de texto de el, em ordem de leitura, como (nó, 'text'|'tail')."""
    yield el, "text"
    for filho in el:
        if isinstance(filho.tag, str):
            yield from slots(filho)
        yield filho, "tail"


def ler(no, attr):
    return getattr(no, attr) or ""


def gravar(no, attr, valor):
    setattr(no, attr, valor if valor else None)


def texto_de(el):
    return "".join(el.itertext())


def tem_midia(el):
    return any(nome(d) in ("img", "image", "svg", "object", "video", "audio") for d in el.iter())


def eh_lixo(p):
    """Parágrafo vazio ou só com traço solto (resto de quebra de página)."""
    if nome(p) != "p" or tem_midia(p) or p.get("id"):
        return False
    t = texto_de(p).replace("\xa0", " ").strip()
    return t in ("", "-", "–", "—", "_", ".")


def mesclar_inlines(raiz, rel):
    """<i>trinta e</i> <i>sete</i> -> <i>trinta e sete</i>"""
    mudou = True
    while mudou:
        mudou = False
        for el in raiz.iter():
            filhos = [c for c in el if isinstance(c.tag, str)]
            for a, b in zip(filhos, filhos[1:]):
                if nome(a) not in INLINE_MESCLAVEL or a.tag != b.tag or dict(a.attrib) != dict(b.attrib):
                    continue
                if a.getnext() is not b or (a.tail or "").strip():
                    continue
                sep = " " if (a.tail or "") else ""
                if len(a):
                    a[-1].tail = ler(a[-1], "tail") + sep + ler(b, "text")
                else:
                    a.text = ler(a, "text") + sep + ler(b, "text")
                for c in list(b):
                    a.append(c)
                a.tail = b.tail
                el.remove(b)
                rel.registrar("itálico/negrito fragmentado unido")
                mudou = True
                break
            if mudou:
                break


def termina_frase(t):
    t = t.rstrip()
    while t and t[-1] in FECHAMENTOS:
        t = t[:-1].rstrip()
    return bool(t) and t[-1] in TERMINAIS


def juntar_paragrafos(corpo, corretor, rel):
    """Reúne parágrafos partidos pela quebra de página do PDF."""
    paragrafos = [p for p in corpo.iter(XHTML + "p", "p")]
    removidos = set()
    for p in paragrafos:
        if p in removidos or eh_lixo(p) or tem_midia(p):
            continue
        segmento = len(normalizar_espacos(texto_de(p)).strip())  # tamanho do último pedaço juntado
        while True:
            prox = p.getnext()
            if prox is None or nome(prox) != "p" or (p.tail or "").strip():
                break
            if eh_lixo(prox) or tem_midia(prox) or prox.get("class") != p.get("class"):
                break
            a = normalizar_espacos(texto_de(p)).strip()
            b = normalizar_espacos(texto_de(prox)).strip()
            if not a or not b or b[0] in "—–-":
                break
            hifen = re.search(rf"([{LETRA}]+)-$", a) and b[0].islower()
            if termina_frase(a):
                break
            # começa com minúscula: certamente continuação. Com maiúscula, só se o
            # pedaço anterior for longo (linha cheia da página) e não acabar em palavra solta de título
            continua_maiuscula = segmento >= 150 and (b[0].isalnum() or b[0] in "“‘(\"«")
            if not (b[0].islower() or hifen or continua_maiuscula):
                break
            segmento = len(b)
            # junta
            sep = " "
            if hifen:
                inicio = re.match(rf"[{LETRA}]+", b).group()
                fim = re.search(rf"([{LETRA}]+)-$", a).group(1)
                sep = ""
                if corretor.conhecida((fim + inicio).lower(), 2):
                    for no, attr in reversed(list(slots(p))):
                        v = ler(no, attr)
                        if v.strip():
                            gravar(no, attr, re.sub(r"-\s*$", "", v))
                            break
                    rel.registrar("palavra hifenizada na quebra de página")
            for no, attr in reversed(list(slots(p))):
                v = ler(no, attr)
                if v.strip():
                    gravar(no, attr, v.rstrip())
                    break
            texto_b = ler(prox, "text").lstrip()
            if len(p):
                p[-1].tail = ler(p[-1], "tail") + sep + texto_b
            else:
                p.text = ler(p, "text") + sep + texto_b
            if not texto_b and len(prox):
                # o parágrafo seguinte começa com uma tag (<i>...): separador vai antes dela
                if len(p):
                    p[-1].tail = ler(p[-1], "tail") + sep
            for c in list(prox):
                p.append(c)
            p.tail = prox.tail
            prox.getparent().remove(prox)
            removidos.add(prox)
            rel.registrar("parágrafo partido reunido")
            rel.exemplo("parágrafo partido reunido", f"...{a[-40:]!r} + {b[:40]!r}...")


def tratar_vazios(corpo, quebra_cena, rel):
    """Remove parágrafos vazios; sequências entre textos viram separador de cena."""
    filhos = [c for c in corpo if isinstance(c.tag, str)]
    i = 0
    while i < len(filhos):
        if not eh_lixo(filhos[i]):
            i += 1
            continue
        j = i
        while j < len(filhos) and eh_lixo(filhos[j]):
            j += 1
        antes = filhos[i - 1] if i > 0 else None
        depois = filhos[j] if j < len(filhos) else None
        entre_textos = (
            antes is not None and depois is not None
            and nome(antes) == "p" and nome(depois) == "p"
            and texto_de(antes).strip() and texto_de(depois).strip()
            # entre linhas curtas (versos, listas, epígrafes) não é troca de cena
            and max(len(texto_de(antes).strip()), len(texto_de(depois).strip())) >= 80
        )
        for k in range(i, j):
            corpo.remove(filhos[k])
        rel.registrar("parágrafo vazio removido", n=j - i)
        if entre_textos and quebra_cena:
            sep = etree.Element(filhos[i].tag, {"class": filhos[i].get("class") or "", "style": "text-align: center"})
            if not sep.get("class"):
                del sep.attrib["class"]
            sep.text = quebra_cena
            sep.tail = "\n\n  "
            antes.addnext(sep)
            rel.registrar("separador de cena inserido")
        i = j


def corrigir_bloco(bloco, corretor, rel, ortografia):
    lista = list(slots(bloco))
    for no, attr in lista:
        v = ler(no, attr)
        if not v:
            continue
        # tail de um bloco filho pertence ao pai; text/tail de inline ao bloco
        novo = corrigir_tipografia(v, rel)
        if ortografia:
            novo = corretor.corrigir_texto(novo)
        if novo != v:
            gravar(no, attr, novo)

    # espaços nas fronteiras entre trechos e nas pontas do parágrafo
    vivos = [(n, a) for n, a in lista if ler(n, a)]
    for (n1, a1), (n2, a2) in zip(vivos, vivos[1:]):
        if ler(n1, a1).endswith(" ") and ler(n2, a2).startswith(" "):
            gravar(n2, a2, ler(n2, a2).lstrip(" "))
    if nome(bloco) in BLOCOS - {"div", "blockquote"}:
        vivos = [(n, a) for n, a in lista if (n, a) != (bloco, "tail") and ler(n, a)]
        if vivos:
            n, a = vivos[0]
            v = ler(n, a)
            novo = v.lstrip()
            # travessão de diálogo no início do parágrafo
            novo2 = re.sub(r"^(?:[-–—]|--)\s*(?=[^\s.,;:!?)])", "— ", novo) if IDIOMA.dialogo_com_travessao else novo
            if novo2 != novo:
                rel.registrar("travessão de diálogo")
                novo = novo2
            gravar(n, a, novo)
            n, a = vivos[-1]
            gravar(n, a, ler(n, a).rstrip())


# --------------------------------------------------------------------------
# EPUB
# --------------------------------------------------------------------------
class Epub:
    def __init__(self, caminho):
        self.zip = zipfile.ZipFile(caminho)
        self.arquivos = {i.filename: self.zip.read(i.filename) for i in self.zip.infolist() if not i.is_dir()}
        self.ordem = [i.filename for i in self.zip.infolist() if not i.is_dir()]
        cont = etree.fromstring(self.arquivos["META-INF/container.xml"])
        self.opf_caminho = cont.find(".//cont:rootfile", NS).get("full-path")
        self.base = posixpath.dirname(self.opf_caminho)
        self.opf = etree.fromstring(self.arquivos[self.opf_caminho])

    def caminho(self, href):
        return posixpath.normpath(posixpath.join(self.base, href.split("#")[0]))

    def itens(self):
        return self.opf.findall("opf:manifest/opf:item", NS)

    def spine(self):
        por_id = {i.get("id"): i for i in self.itens()}
        return [por_id[r.get("idref")] for r in self.opf.findall("opf:spine/opf:itemref", NS) if r.get("idref") in por_id]

    def titulo(self):
        t = self.opf.find("opf:metadata/dc:title", NS)
        return (t.text or "").strip() if t is not None else ""

    def remover_item(self, item):
        id_ = item.get("id")
        href = self.caminho(item.get("href"))
        for r in self.opf.findall("opf:spine/opf:itemref", NS):
            if r.get("idref") == id_:
                r.getparent().remove(r)
        for r in self.opf.findall("opf:guide/opf:reference", NS):
            if self.caminho(r.get("href")) == href:
                r.getparent().remove(r)
        item.getparent().remove(item)
        self.arquivos.pop(href, None)
        return href

    def salvar(self, destino, extras):
        self.arquivos[self.opf_caminho] = etree.tostring(
            self.opf, xml_declaration=True, encoding="utf-8", pretty_print=True)
        self.arquivos.update(extras)
        with zipfile.ZipFile(destino, "w") as z:
            z.writestr(zipfile.ZipInfo("mimetype"), b"application/epub+zip", compress_type=zipfile.ZIP_STORED)
            for nome_arq in self.ordem + [n for n in self.arquivos if n not in self.ordem]:
                if nome_arq == "mimetype" or nome_arq not in self.arquivos:
                    continue
                z.writestr(nome_arq, self.arquivos[nome_arq], compress_type=zipfile.ZIP_DEFLATED)


def parse_xhtml(dados):
    parser = etree.XMLParser(recover=True, resolve_entities=False, remove_blank_text=False)
    raiz = etree.fromstring(dados, parser)
    if raiz is None:
        raise ValueError("XHTML ilegível")
    return raiz.getroottree()


def serializar_xhtml(arvore):
    doctype = arvore.docinfo.doctype or None
    return etree.tostring(arvore, xml_declaration=True, encoding="utf-8", doctype=doctype)


def eh_anuncio(texto):
    t = normalizar_espacos(texto).strip()
    return len(t) < 1500 and bool(MARCAS_ANUNCIO.search(t))


# --------------------------------------------------------------------------
# Capítulos e sumário
# --------------------------------------------------------------------------
def titulo_bonito(t):
    """'O “SIMITÉRIO” DE BICHOS' -> 'O “Simitério” de Bichos' (só se estiver todo em maiúsculas)."""
    if not t.isupper():
        return t
    palavras = t.lower().split(" ")
    saida = []
    for i, p in enumerate(palavras):
        nucleo = p.strip("“”\"'‘’(),:;.—-")
        if i > 0 and nucleo in IDIOMA.minusculas:
            saida.append(p)
        else:
            j = next((k for k, c in enumerate(p) if c.isalpha()), None)
            saida.append(p if j is None else p[:j] + p[j].upper() + p[j + 1:])
    return " ".join(saida)


def rotulo_titulo(h):
    """Texto do título para o sumário; <br/> separa título e subtítulo."""
    partes, atual = [], ""
    for no, attr in slots(h):
        if attr == "tail" and nome(no) == "br":
            partes.append(atual)
            atual = ""
        atual += ler(no, attr) if not (attr == "tail" and no is h) else ""
    partes.append(atual)
    partes = [normalizar_espacos(p).strip() for p in partes if p.strip()]
    if not partes:
        return ""
    rotulo = titulo_bonito(partes[0])
    if len(partes) > 1:
        rotulo += ": " + titulo_bonito(" ".join(partes[1:]))
    return rotulo


def eh_titulo(el):
    return nome(el) in ("h1", "h2", "h3", "h4", "h5", "h6")


def promover_titulos(corpo, rel):
    """Parágrafos que são títulos de capítulo/parte ('1', 'EPÍLOGO', 'PARTE TRÊS') viram <h1>/<h2>."""
    filhos = [c for c in corpo if isinstance(c.tag, str)]
    primeiro = next((normalizar_espacos(texto_de(c)).strip() for c in filhos if texto_de(c).strip()), "")
    if IDIOMA.re_pagina_sumario.match(primeiro):
        return
    for i, el in enumerate(filhos):
        if nome(el) != "p" or eh_lixo(el) or tem_midia(el) or any(nome(a) == "a" for a in el.iter()):
            continue
        t = normalizar_espacos(texto_de(el)).strip()
        if not t or len(t) > 60:
            continue
        anterior = filhos[i - 1] if i > 0 else None
        depois_de_quebra = anterior is None or eh_lixo(anterior) or eh_titulo(anterior) or nome(anterior) == "hr"
        if not depois_de_quebra:
            continue
        if IDIOMA.re_parte.match(t):
            nivel = "h1"
        elif IDIOMA.re_capitulo.match(t):
            nivel = "h2"
        else:
            continue
        ns = el.tag[: -len(nome(el))]
        el.tag = ns + nivel
        el.attrib.pop("class", None)
        el.set("style", "text-align: center; page-break-before: always")
        rel.registrar("título de capítulo/parte identificado")
        rel.exemplo("título de capítulo/parte identificado", t)
    # subtítulos: "PARTE UM" + "O" + "“SIMITÉRIO” DE BICHOS"
    for h in [c for c in corpo if isinstance(c.tag, str) and eh_titulo(c)]:
        t = normalizar_espacos(texto_de(h)).strip()
        if not (IDIOMA.re_parte.match(t) or IDIOMA.re_capitulo.match(t)):
            continue
        prox = h.getnext()
        vazios = []
        while prox is not None and nome(prox) == "p":
            if eh_lixo(prox):
                vazios.append(prox)
                prox = prox.getnext()
                continue
            st = normalizar_espacos(texto_de(prox)).strip()
            if len(st) > 60 or not st.isupper() or IDIOMA.re_parte.match(st) or IDIOMA.re_capitulo.match(st):
                break
            br = etree.SubElement(h, h.tag[: -len(nome(h))] + "br")
            br.tail = " " + st
            seguinte = prox.getnext()
            for v in vazios + [prox]:
                corpo.remove(v)
            vazios = []
            prox = seguinte
            rel.registrar("subtítulo unido ao título")


class Sumario:
    """Verifica e corrige o sumário (toc.ncx, nav.xhtml do EPUB3 e a página de sumário do livro)."""

    def __init__(self, epub, docs, rel, refazer):
        self.epub = epub
        self.docs = docs  # lista [(item, árvore)], modificada no lugar
        self.rel = rel
        self.refazer = refazer

    # -- utilidades ------------------------------------------------------
    def caminho_doc(self, item):
        return self.epub.caminho(item.get("href"))

    def corpo(self, arvore):
        r = arvore.getroot()
        c = r.find(XHTML + "body")
        return c if c is not None else r.find("body")

    def ids(self):
        return {self.caminho_doc(i): {e.get("id") for e in a.iter() if isinstance(e.tag, str) and e.get("id")}
                for i, a in self.docs}

    def href(self, de, para):
        return posixpath.relpath(para, posixpath.dirname(de))

    def alvo(self, base, src):
        arq, _, frag = src.partition("#")
        return posixpath.normpath(posixpath.join(posixpath.dirname(base), arq)), frag

    # -- página de sumário dentro do livro --------------------------------
    def achar_pagina_sumario(self):
        for idx, (item, arvore) in enumerate(self.docs):
            corpo = self.corpo(arvore)
            for h in corpo.iter():
                if isinstance(h.tag, str) and (eh_titulo(h) or nome(h) == "p"):
                    t = normalizar_espacos(texto_de(h)).strip()
                    if t:
                        if IDIOMA.re_pagina_sumario.match(t):
                            return idx
                        break
        return None

    def remover_listas_sem_link(self, idx):
        """Páginas logo após um sumário sem links que só repetem títulos (resto do sumário do PDF).
        Remove os títulos repetidos do início delas; se a página ficar vazia, remove a página."""
        while idx + 1 < len(self.docs):
            item, arvore = self.docs[idx + 1]
            corpo = self.corpo(arvore)
            removidos = 0
            for el in [c for c in corpo if isinstance(c.tag, str)]:
                t = normalizar_espacos(texto_de(el)).strip()
                if tem_midia(el):
                    break
                if eh_lixo(el) or (not t and eh_titulo(el)):
                    continue
                if (eh_titulo(el) or (nome(el) == "p" and len(t) <= 60 and t.isupper())) and \
                        (IDIOMA.re_parte.match(t) or IDIOMA.re_capitulo.match(t) or (removidos and t.isupper())):
                    corpo.remove(el)
                    removidos += 1
                    continue
                break
            if not removidos:
                break
            restante = normalizar_espacos(texto_de(corpo)).strip()
            caminho = self.caminho_doc(item)
            if restante or tem_midia(corpo):
                self.rel.estrutura.append(f"{removidos} título(s) que repetiam o sumário removidos de {caminho}")
                break
            self.epub.remover_item(item)
            self.docs.pop(idx + 1)
            self.rel.estrutura.append(f"página que repetia o sumário (sem links) removida: {caminho}")

    # -- títulos do livro -------------------------------------------------
    def titulos(self, ignorar=None):
        entradas = []
        n = 0
        for item, arvore in self.docs:
            if ignorar is not None and item is ignorar:
                continue
            for h in self.corpo(arvore).iter():
                if not (isinstance(h.tag, str) and nome(h) in ("h1", "h2", "h3")):
                    continue
                rotulo = rotulo_titulo(h)
                if not rotulo or IDIOMA.re_pagina_sumario.match(rotulo):
                    continue
                if entradas and entradas[-1]["rotulo"] == rotulo and entradas[-1]["arquivo"] == self.caminho_doc(item):
                    continue
                n += 1
                if not h.get("id"):
                    h.set("id", f"cap{n:03d}")
                entradas.append({"rotulo": rotulo, "nivel": int(nome(h)[1]),
                                 "arquivo": self.caminho_doc(item), "id": h.get("id")})
        # normaliza níveis: o menor nível usado vira 1
        if entradas:
            menor = min(e["nivel"] for e in entradas)
            for e in entradas:
                e["nivel"] = min(e["nivel"] - menor + 1, 2)
        return entradas

    # -- toc.ncx ----------------------------------------------------------
    def verificar_ncx(self, ncx, caminho_ncx, ids, entradas):
        """Corrige o que dá; devolve True se o NCX existente é bom o bastante para manter."""
        nav_map = ncx.find("ncx:navMap", NS)
        ordem_spine = {self.caminho_doc(i): k for k, (i, _) in enumerate(self.docs)}
        validos, problemas, ultima = 0, 0, -1
        for np_ in list(nav_map.iter(NCX + "navPoint")):
            c = np_.find("ncx:content", NS)
            lbl = np_.find("ncx:navLabel/ncx:text", NS)
            if c is None or not c.get("src"):
                np_.getparent().remove(np_)
                problemas += 1
                continue
            arq, frag = self.alvo(caminho_ncx, c.get("src"))
            if arq not in ids:
                self.rel.estrutura.append(f"sumário: entrada para arquivo inexistente removida ({c.get('src')})")
                for filho in np_.findall("ncx:navPoint", NS):  # preserva subentradas
                    np_.addprevious(filho)
                np_.getparent().remove(np_)
                problemas += 1
                continue
            if frag and frag not in ids[arq]:
                self.rel.estrutura.append(f"sumário: âncora inexistente '#{frag}' corrigida para o início do arquivo")
                c.set("src", c.get("src").split("#")[0])
                problemas += 1
            if lbl is None or not (lbl.text or "").strip():
                problemas += 1
            else:
                lbl.text = normalizar_espacos(lbl.text).strip()
            if ordem_spine[arq] < ultima:
                problemas += 1
                self.rel.estrutura.append(f"sumário: entrada fora de ordem ({lbl.text if lbl is not None else '?'})")
            ultima = max(ultima, ordem_spine[arq])
            validos += 1
        suficiente = validos >= max(3, 0.7 * len(entradas))
        return suficiente and problemas == 0

    def escrever_ncx(self, ncx, caminho_ncx, entradas):
        nav_map = ncx.find("ncx:navMap", NS)
        for filho in list(nav_map):
            nav_map.remove(filho)
        pais = [nav_map]
        for n, e in enumerate(entradas, 1):
            while len(pais) > e["nivel"]:
                pais.pop()
            np_ = etree.SubElement(pais[-1], NCX + "navPoint", id=f"navpoint_{n}", playOrder=str(n))
            np_.text = "\n"
            lbl = etree.SubElement(np_, NCX + "navLabel")
            etree.SubElement(lbl, NCX + "text").text = e["rotulo"]
            src = self.href(caminho_ncx, e["arquivo"]) + (f"#{e['id']}" if e["id"] else "")
            etree.SubElement(np_, NCX + "content", src=src)
            pais.append(np_)
        profundidade = ncx.find("ncx:head/ncx:meta[@name='dtb:depth']", NS)
        if profundidade is not None:
            profundidade.set("content", str(max((e["nivel"] for e in entradas), default=1)))

    def ncx(self, entradas, ids):
        item = next((i for i in self.epub.itens() if i.get("media-type") == "application/x-dtbncx+xml"), None)
        if item is None:
            return
        caminho = self.epub.caminho(item.get("href"))
        if caminho not in self.epub.arquivos:
            return
        ncx = etree.fromstring(self.epub.arquivos[caminho])
        lang_attr = "{http://www.w3.org/XML/1998/namespace}lang"
        if ncx.get(lang_attr) and "_" in ncx.get(lang_attr):
            ncx.set(lang_attr, ncx.get(lang_attr).replace("_", "-"))
        titulo = ncx.find("ncx:docTitle/ncx:text", NS)
        if titulo is not None and self.epub.titulo() and not (titulo.text or "").strip():
            titulo.text = self.epub.titulo()
        if ncx.find("ncx:navMap", NS) is None:
            etree.SubElement(ncx, NCX + "navMap")
        bom = self.verificar_ncx(ncx, caminho, ids, entradas)
        if (self.refazer or not bom) and len(entradas) >= 2:
            self.escrever_ncx(ncx, caminho, entradas)
            self.rel.estrutura.append(f"toc.ncx reconstruído com {len(entradas)} entradas a partir dos títulos")
        else:
            for n, np_ in enumerate(ncx.iter(NCX + "navPoint"), 1):
                np_.set("playOrder", str(n))
            self.rel.estrutura.append("toc.ncx verificado e mantido")
        self.epub.arquivos[caminho] = etree.tostring(ncx, xml_declaration=True, encoding="utf-8", pretty_print=True)

    # -- nav.xhtml (EPUB3) ------------------------------------------------
    def nav(self, entradas, ids):
        item = next((i for i in self.epub.itens() if "nav" in (i.get("properties") or "").split()), None)
        if item is None:
            return
        caminho = self.epub.caminho(item.get("href"))
        doc = next((a for i, a in self.docs if self.caminho_doc(i) == caminho), None)
        arvore = doc if doc is not None else parse_xhtml(self.epub.arquivos[caminho])
        toc = next((n for n in arvore.getroot().iter(XHTML + "nav")
                    if n.get("{http://www.idpf.org/2007/ops}type") == "toc"), None)
        if toc is None:
            return
        quebrados = 0
        for a in toc.iter(XHTML + "a"):
            arq, frag = self.alvo(caminho, a.get("href", ""))
            if arq not in ids or (frag and frag not in ids[arq]):
                quebrados += 1
        links = len(list(toc.iter(XHTML + "a")))
        if (self.refazer or quebrados or links < max(3, 0.7 * len(entradas))) and len(entradas) >= 2:
            for filho in list(toc):
                if nome(filho) == "ol":
                    toc.remove(filho)
            listas = [etree.SubElement(toc, XHTML + "ol")]
            ultimo_li = None
            for e in entradas:
                while len(listas) > e["nivel"]:
                    listas.pop()
                if len(listas) < e["nivel"] and ultimo_li is not None:
                    listas.append(etree.SubElement(ultimo_li, XHTML + "ol"))
                li = etree.SubElement(listas[-1], XHTML + "li")
                a = etree.SubElement(li, XHTML + "a", href=self.href(caminho, e["arquivo"]) + (f"#{e['id']}" if e["id"] else ""))
                a.text = e["rotulo"]
                ultimo_li = li
            self.rel.estrutura.append(f"nav.xhtml (EPUB3) reconstruído ({quebrados} links quebrados)")
        if doc is None:
            self.epub.arquivos[caminho] = serializar_xhtml(arvore)

    # -- página de sumário ------------------------------------------------
    def pagina(self, idx, entradas, ids):
        item, arvore = self.docs[idx]
        caminho = self.caminho_doc(item)
        corpo = self.corpo(arvore)
        ns = corpo.tag[: -len(nome(corpo))]
        links = [a for a in corpo.iter(ns + "a") if a.get("href")]
        if links and not self.refazer:
            # mantém a página, consertando links quebrados pelo texto
            por_rotulo = {sem_acentos(e["rotulo"]).lower(): e for e in entradas}
            for a in links:
                arq, frag = self.alvo(caminho, a.get("href"))
                if arq in ids and (not frag or frag in ids[arq]):
                    continue
                e = por_rotulo.get(sem_acentos(normalizar_espacos(texto_de(a)).strip()).lower())
                if e:
                    a.set("href", self.href(caminho, e["arquivo"]) + (f"#{e['id']}" if e["id"] else ""))
                    self.rel.estrutura.append(f"sumário interno: link corrigido ({texto_de(a).strip()})")
                else:
                    a.attrib.pop("href")
                    self.rel.estrutura.append(f"sumário interno: link quebrado removido ({texto_de(a).strip()})")
            return
        # sem links: refaz a página
        titulo = next((h for h in corpo.iter() if isinstance(h.tag, str) and eh_titulo(h)), None)
        for filho in list(corpo):
            if filho is not titulo:
                corpo.remove(filho)
        if titulo is None:
            titulo = etree.SubElement(corpo, ns + "h1")
        for filho in list(titulo):
            titulo.remove(filho)
        titulo.text = IDIOMA.rotulos["sumario"]
        titulo.tail = "\n"
        for e in entradas:
            p = etree.SubElement(corpo, ns + "p")
            if e["nivel"] > 1:
                p.set("style", "margin-left: 2em")
            a = etree.SubElement(p, ns + "a", href=self.href(caminho, e["arquivo"]) + (f"#{e['id']}" if e["id"] else ""))
            a.text = e["rotulo"]
            p.tail = "\n"
        self.rel.estrutura.append(f"página de sumário refeita com {len(entradas)} links: {caminho}")

    def guia(self, idx_sumario, entradas):
        guide = self.epub.opf.find("opf:guide", NS)
        if guide is None:
            guide = etree.SubElement(self.epub.opf, "{%s}guide" % NS["opf"])
        tipos = {r.get("type"): r for r in guide.findall("opf:reference", NS)}
        base = self.epub.opf_caminho
        if idx_sumario is not None and "toc" not in tipos:
            item = self.docs[idx_sumario][0]
            etree.SubElement(guide, "{%s}reference" % NS["opf"], type="toc", title=IDIOMA.rotulos["sumario"],
                             href=self.href(base, self.caminho_doc(item)))
            self.rel.estrutura.append("guide: referência ao sumário adicionada")
        if entradas and "text" not in tipos:
            e = entradas[0]
            etree.SubElement(guide, "{%s}reference" % NS["opf"], type="text", title=IDIOMA.rotulos["inicio"],
                             href=self.href(base, e["arquivo"]) + (f"#{e['id']}" if e["id"] else ""))
            self.rel.estrutura.append("guide: referência ao início do texto adicionada")

    def processar(self):
        idx = self.achar_pagina_sumario()
        pagina_item = None
        if idx is not None:
            pagina_item = self.docs[idx][0]
            corpo = self.corpo(self.docs[idx][1])
            if not any(a.get("href") for a in corpo.iter(XHTML + "a", "a")):
                self.remover_listas_sem_link(idx)
        entradas = self.titulos(ignorar=pagina_item)
        if not entradas:
            self.rel.estrutura.append("nenhum título de capítulo encontrado; sumário não alterado")
        ids = self.ids()
        if idx is not None and entradas:
            self.pagina(idx, entradas, ids)
        # entrada inicial para a primeira página (capa), se ela não tiver título
        if entradas and self.docs and self.caminho_doc(self.docs[0][0]) != entradas[0]["arquivo"] \
                and self.docs[0][0] is not pagina_item:
            entradas.insert(0, {"rotulo": IDIOMA.rotulos["capa"], "nivel": 1, "arquivo": self.caminho_doc(self.docs[0][0]), "id": None})
        if idx is not None and entradas:
            pos = next((k for k, e in enumerate(entradas) if e["arquivo"] == self.caminho_doc(pagina_item)), None)
            if pos is None:
                depois = 1 if entradas and entradas[0]["rotulo"] == IDIOMA.rotulos["capa"] else 0
                ordem = [self.caminho_doc(i) for i, _ in self.docs]
                pos_doc = ordem.index(self.caminho_doc(pagina_item))
                while depois < len(entradas) and ordem.index(entradas[depois]["arquivo"]) < pos_doc:
                    depois += 1
                entradas.insert(depois, {"rotulo": IDIOMA.rotulos["sumario"], "nivel": 1,
                                         "arquivo": self.caminho_doc(pagina_item), "id": None})
        for e in entradas:
            e["id"] = e["id"] or ""
        self.ncx(entradas, ids)
        self.nav(entradas, ids)
        self.guia(idx, [e for e in entradas if e["id"]])


def carregar_substituicoes(caminho):
    subs = {}
    if not caminho:
        return subs
    for linha in Path(caminho).read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        errado, certo = (x.strip() for x in linha.split("=", 1))
        subs[errado] = certo
    return subs


CODIGOS_IDIOMA = {"pt": "pt-BR", "en": "en"}


def atualizar_data_modificacao(epub, rel):
    """EPUB3 exige exatamente um <meta property="dcterms:modified">."""
    if not (epub.opf.get("version") or "").startswith("3"):
        return
    metadata = epub.opf.find("opf:metadata", NS)
    metas = [m for m in metadata.findall("opf:meta", NS) if m.get("property") == "dcterms:modified"]
    agora = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not metas:
        metas = [etree.SubElement(metadata, "{%s}meta" % NS["opf"], property="dcterms:modified")]
        rel.estrutura.append("dcterms:modified (obrigatório no EPUB3) adicionado")
    for extra in metas[1:]:
        metadata.remove(extra)
    metas[0].text = agora


def corrigir_idioma(epub, args, textos, rel):
    """Detecta o idioma do texto, ajusta o dc:language e devolve a configuração do idioma."""
    global IDIOMA
    metadata = epub.opf.find("opf:metadata", NS)
    langs = epub.opf.findall("opf:metadata/dc:language", NS)
    meta = next((l.text.strip() for l in langs if l.text and l.text.strip()), "")
    if args.idioma != "auto":
        IDIOMA = IDIOMAS[args.idioma]
        origem = "forçado por --idioma"
    else:
        IDIOMA, contagem = detectar_idioma(textos, meta)
        origem = "detectado pelo texto (" + ", ".join(f"{k}: {v}" for k, v in contagem.most_common()) + ")"
    rel.estrutura.append(f"idioma do livro: {IDIOMA.codigo} — {origem}; metadado: {meta or '(ausente)'}")

    novo = meta.replace("_", "-")
    if IDIOMA in (PT, EN) and novo.lower()[:2] != IDIOMA.codigo:
        novo = CODIGOS_IDIOMA[IDIOMA.codigo]
    if novo and novo != meta:
        if langs:
            langs[0].text = novo
        else:
            etree.SubElement(metadata, "{%s}language" % NS["dc"]).text = novo
        rel.estrutura.append(f"dc:language: {meta or '(ausente)'} -> {novo}")
    return novo or meta


def processar(entrada, saida, args, dicionarios, progresso=None):
    """Corrige um EPUB. `progresso(fração 0..1, mensagem)` é chamado a cada etapa.
    Devolve um resumo com idioma, total de correções, suspeitas e caminho do relatório."""
    def etapa(fracao, msg):
        if progresso:
            progresso(fracao, msg)

    rel = Relatorio()
    etapa(0.0, f"Abrindo {Path(entrada).name}")
    epub = Epub(entrada)
    titulo = epub.titulo()

    docs = []
    for item in epub.spine():
        if "html" not in (item.get("media-type") or ""):
            continue
        caminho = epub.caminho(item.get("href"))
        if caminho not in epub.arquivos:
            continue
        try:
            arvore = parse_xhtml(epub.arquivos[caminho])
        except Exception as e:  # noqa: BLE001
            rel.estrutura.append(f"não foi possível ler {caminho}: {e}")
            continue
        corpo = arvore.getroot().find(XHTML + "body")
        if corpo is None:
            corpo = arvore.getroot().find("body")
        if corpo is None:
            continue
        if not args.manter_anuncios and eh_anuncio(texto_de(corpo)):
            epub.remover_item(item)
            rel.estrutura.append(f"página de propaganda removida: {caminho}")
            continue
        docs.append((item, arvore))

    textos = [texto_de(a.getroot()) for _, a in docs]
    etapa(0.04, "Detectando o idioma")
    lang_doc = corrigir_idioma(epub, args, textos, rel)
    if IDIOMA.codigo not in dicionarios:
        etapa(0.06, f"Carregando dicionário ({IDIOMA.codigo})")
        dicionarios[IDIOMA.codigo] = Dicionario(IDIOMA, args.dicionario)
    etapa(0.12, "Analisando o vocabulário do livro")
    corretor = Corretor(textos, carregar_substituicoes(args.substituicoes), args.modernizar, rel,
                        dicionarios[IDIOMA.codigo])
    ortografia = not args.sem_ortografia and IDIOMA is not OUTRO

    pesos = [len(t) + 1 for t in textos]
    feito = 0
    for n, (item, arvore) in enumerate(docs):
        etapa(0.15 + 0.75 * feito / sum(pesos),
              f"Corrigindo {n + 1}/{len(docs)}: {posixpath.basename(item.get('href'))}")
        feito += pesos[n]
        raiz = arvore.getroot()
        corpo = raiz.find(XHTML + "body")
        if corpo is None:
            corpo = raiz.find("body")
        for attr in ("{http://www.w3.org/XML/1998/namespace}lang", "lang"):
            atual = raiz.get(attr)
            if lang_doc and (attr.endswith("}lang") or atual) and atual != lang_doc:
                raiz.set(attr, lang_doc)
        t = raiz.find(f"{XHTML}head/{XHTML}title")
        if t is not None and titulo and TITULO_LIXO.search(t.text or ""):
            rel.registrar("<title> genérico substituído")
            t.text = titulo

        mesclar_inlines(corpo, rel)
        promover_titulos(corpo, rel)
        juntar_paragrafos(corpo, corretor, rel)
        tratar_vazios(corpo, args.quebra_cena, rel)
        for el in list(corpo.iter()):
            if nome(el) in BLOCOS and not any(nome(c) in BLOCOS for c in el):
                corrigir_bloco(el, corretor, rel, ortografia)
        mesclar_inlines(corpo, rel)

    etapa(0.90, "Verificando capítulos e sumário")
    Sumario(epub, docs, rel, args.refazer_sumario).processar()
    atualizar_data_modificacao(epub, rel)
    for item, arvore in docs:
        epub.arquivos[epub.caminho(item.get("href"))] = serializar_xhtml(arvore)

    etapa(0.96, "Gravando o EPUB e o relatório")
    relatorio_txt = rel.texto(entrada, saida if not args.simular else "(simulação)")
    caminho_rel = Path(str(saida)).with_suffix(".relatorio.txt")
    caminho_rel.write_text(relatorio_txt, encoding="utf-8")
    if not args.simular:
        epub.salvar(saida, {})
    resumo = {
        "idioma": IDIOMA.codigo,
        "total": sum(rel.contagem.values()),
        "suspeitas": len(rel.suspeitas),
        "relatorio": caminho_rel,
        "estrutura": list(rel.estrutura),
        "contagem": rel.contagem.most_common(),
    }
    etapa(1.0, "Concluído")
    return resumo


def criar_parser():
    ap = argparse.ArgumentParser(description="Corrige erros de ortografia/OCR, espaçamento, capítulos e sumário "
                                             "em EPUBs em português ou inglês.",
                                 epilog=f"Criado por {AUTOR}.")
    ap.add_argument("epubs", nargs="+", type=Path, help="arquivo(s) .epub de entrada")
    ap.add_argument("-o", "--saida", type=Path, help="arquivo de saída (só com um epub de entrada)")
    ap.add_argument("--simular", action="store_true", help="não grava o epub, só o relatório")
    ap.add_argument("--idioma", choices=["auto", "pt", "en"], default="auto",
                    help="idioma do livro (padrão: detectar pelo texto)")
    ap.add_argument("--modernizar", action="store_true",
                    help="atualiza para o Acordo Ortográfico (freqüente->frequente, idéia->ideia, pára->para)")
    ap.add_argument("--substituicoes", type=Path, help="arquivo com linhas 'errado=certo' (palavra inteira)")
    ap.add_argument("--dicionario", type=Path,
                    help="lista extra de palavras válidas (uma por linha), ex.: nomes próprios do livro")
    ap.add_argument("--sem-ortografia", action="store_true", help="não corrige palavras, só tipografia e estrutura")
    ap.add_argument("--refazer-sumario", action="store_true",
                    help="reconstrói o sumário a partir dos títulos mesmo se o atual parecer correto")
    ap.add_argument("--manter-anuncios", action="store_true", help="não remove páginas de propaganda")
    ap.add_argument("--quebra-cena", default="* * *",
                    help='texto do separador de cena no lugar de parágrafos vazios (padrão "* * *"; "" para só remover)')
    return ap


def opcoes_padrao():
    """Opções padrão (as mesmas da linha de comando sem flags), para uso como biblioteca."""
    return criar_parser().parse_args(["-"])


def main():
    ap = criar_parser()
    args = ap.parse_args()
    if args.saida and len(args.epubs) > 1:
        ap.error("-o/--saida só pode ser usado com um único epub")

    dicionarios = {}
    for entrada in args.epubs:
        saida = args.saida or entrada.with_name(entrada.stem + "_corrigido.epub")
        if saida.resolve() == entrada.resolve():
            ap.error("a saída não pode sobrescrever a entrada")
        r = processar(entrada, saida, args, dicionarios)
        print(f"{entrada}: idioma {r['idioma']}, {r['total']} correções, "
              f"{r['suspeitas']} palavras suspeitas para revisar")
        if not args.simular:
            print(f"  EPUB corrigido: {saida}")
        print(f"  Relatório:      {r['relatorio']}")


if __name__ == "__main__":
    main()
