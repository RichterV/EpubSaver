# EpubSaver

Corrige EPUBs mal convertidos (principalmente os gerados a partir de PDF/OCR)
em **português** ou **inglês**: erros de ortografia e de OCR, espaçamento,
pontuação, parágrafos partidos, capítulos e sumário. Funciona pela linha de
comando ou como um executável Linux com interface gráfica.

Criado por Vinicius Richter.

## O que é corrigido

**Idioma**
- Detecta o idioma pelo próprio texto (português, inglês ou outro) e corrige o
  `dc:language` se estiver errado ou fora do padrão (`pt_BR` → `pt-BR`).
- Em outros idiomas, aplica só as correções de estrutura e espaçamento.

**Ortografia e OCR** (dicionários hunspell do LibreOffice + vocabulário do próprio livro)
- Letras trocadas: `daro` → `claro`, `rnanhã` → `manhã`, `moming` → `morning`.
- Nomes próprios: `Rachei` → `Rachel` quando "Rachel" aparece centenas de vezes no livro.
- Acentos perdidos: `EPILOGO` → `EPÍLOGO`, `tambem` → `também`.
- Hífen: `parecialhe` → `parecia-lhe`, `guardachuvas` → `guarda-chuvas`.
- Palavras coladas ou partidas: `estábem` → `está bem`, `co m` → `com`.
- Opcional: atualização para o Acordo Ortográfico (`idéia` → `ideia`, `freqüente` → `frequente`).

**Espaçamento e pontuação**
- Espaços duplicados, espaço antes de pontuação, espaço ausente depois dela.
- Reticências quebradas (`. . .` → `...`), aspas retas → curvas, apóstrofos.
- Travessão de diálogo em português (`- Olá` → `— Olá`).

**Estrutura**
- Reúne parágrafos partidos na quebra de página do PDF, inclusive palavras hifenizadas.
- Remove parágrafos vazios; onde marcavam troca de cena, insere `* * *`.
- Une itálicos e negritos fragmentados; remove páginas de propaganda de sites de download.
- Troca `<title>` genéricos ("Microsoft Word - ...") pelo título do livro.

**Capítulos e sumário**
- Reconhece títulos que viraram parágrafos comuns (`PARTE TRÊS`, `EPÍLOGO`, `Chapter 3`) e une os subtítulos.
- Verifica o `toc.ncx` e o `nav.xhtml` (EPUB3): links para arquivos ou âncoras inexistentes, entradas fora de ordem ou sumário incompleto. Corrige o que for possível ou reconstrói a partir dos títulos.
- Refaz a página de sumário do livro com links, ou conserta os links quebrados.
- Completa o `guide` do OPF e o `dcterms:modified` (obrigatório no EPUB3).

Cada execução gera um **relatório** (`<saída>.relatorio.txt`) com:
- tudo o que foi alterado;
- a lista de palavras desconhecidas que *não* foram mexidas, para revisão manual.

## Executável com interface gráfica

```bash
./build.sh              # gera dist/corrigir-epub (~26 MB, arquivo único)
./dist/corrigir-epub
```

1. Escolha o EPUB.
2. Escolha onde salvar a versão corrigida. O original nunca é sobrescrito.
3. Acompanhe a barra de progresso e as etapas na janela.

Ao terminar, é possível abrir o relatório ou a pasta. Os dicionários vão
embutidos no executável, então ele funciona offline.

O build requer apenas o [uv](https://docs.astral.sh/uv/). Ele baixa o Python
(com Tk), o PyInstaller e as dependências num ambiente isolado; nada é
instalado no sistema.

## Linha de comando

```bash
uv run corrigir_epub.py livro.epub                  # gera livro_corrigido.epub
uv run corrigir_epub.py livro.epub -o saida.epub
uv run corrigir_epub.py *.epub                      # vários livros
uv run corrigir_epub.py livro.epub --simular        # só gera o relatório
```

| Opção | Efeito |
|---|---|
| `--idioma {auto,pt,en}` | força o idioma (padrão: detectar pelo texto) |
| `--modernizar` | atualiza para o Acordo Ortográfico de 1990 |
| `--substituicoes ARQ` | correções manuais, uma por linha: `errado=certo` |
| `--dicionario ARQ` | palavras extras consideradas corretas (ex.: nomes do livro) |
| `--refazer-sumario` | reconstrói o sumário mesmo se o atual parecer correto |
| `--sem-ortografia` | só tipografia e estrutura, sem alterar palavras |
| `--manter-anuncios` | não remove páginas de propaganda |
| `--quebra-cena TEXTO` | separador de cena (padrão `* * *`; `""` para só remover) |

Sem o uv: `pip install lxml pyspellchecker` e `python3 corrigir_epub.py ...`.
Os dicionários são baixados na primeira execução e guardados em
`~/.cache/corrigir_epub`.

## Arquivos

- `corrigir_epub.py`: o corretor (biblioteca + linha de comando).
- `corrigir_epub_gui.py`: interface gráfica (Tk) e ponto de entrada do executável.
- `build.sh`: gera o executável de arquivo único com PyInstaller.

## Dicionários e licenças

- Corretores hunspell pt_BR (VERO), en_US e en_GB: [LibreOffice/dictionaries](https://github.com/LibreOffice/dictionaries).
- Frequências do português: [fserb/pt-br](https://github.com/fserb/pt-br) (MIT).
- Frequências do inglês: [pyspellchecker](https://github.com/barrust/pyspellchecker) (MIT).
