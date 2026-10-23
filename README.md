# EpubSaver

Corrige EPUBs mal convertidos (principalmente os gerados a partir de PDF/OCR)
em **português** ou **inglês**: erros de ortografia e de OCR, espaçamento,
pontuação, parágrafos partidos, capítulos e sumário. Funciona como um
programa com interface gráfica, para Linux e Windows, ou pela linha de comando.

Criado por Vinicius Richter.

<p align="center"><img src="icone/icone.png" width="128" alt="Ícone do EpubSaver"></p>

## Instalação

O programa é um arquivo único: não precisa instalar Python nem nada mais. Os
dicionários vão embutidos, então ele funciona offline.

Baixe a versão mais recente na página de
[Releases](https://github.com/RichterV/EpubSaver/releases/latest).

### Windows

1. Baixe `corrigir-epub-windows-x64.exe`.
2. Dê dois cliques no arquivo. Se quiser, mova-o antes para uma pasta fixa (ex.:
   `Documentos`) e crie um atalho na Área de Trabalho (botão direito →
   *Mostrar mais opções* → *Enviar para* → *Área de trabalho*).
3. Na primeira vez, o Windows pode mostrar "O Windows protegeu o computador",
   porque o executável não é assinado digitalmente. Clique em
   **Mais informações** → **Executar assim mesmo**.

Requer Windows 10 ou 11 (64 bits).

### Linux

1. Baixe `corrigir-epub-linux-x86_64`.
2. Dê permissão de execução e abra:

   ```bash
   chmod +x corrigir-epub-linux-x86_64
   ./corrigir-epub-linux-x86_64
   ```

   Ou, no gerenciador de arquivos: botão direito → *Propriedades* → marque
   *Permitir executar como programa* e dê dois cliques.

Para colocar o programa no menu de aplicativos, com ícone:

```bash
mkdir -p ~/.local/bin ~/.local/share/icons ~/.local/share/applications
mv corrigir-epub-linux-x86_64 ~/.local/bin/corrigir-epub
curl -L -o ~/.local/share/icons/epubsaver.png \
    https://raw.githubusercontent.com/RichterV/EpubSaver/main/icone/icone.png
cat > ~/.local/share/applications/epubsaver.desktop <<FIM
[Desktop Entry]
Type=Application
Name=EpubSaver
Comment=Corrige EPUBs mal convertidos
Exec=$HOME/.local/bin/corrigir-epub
Icon=$HOME/.local/share/icons/epubsaver.png
Categories=Office;
FIM
```

Requer Linux de 64 bits (x86_64) com interface gráfica. O executável é gerado
no Ubuntu 22.04 e roda nas distribuições daquela época em diante.

## Uso

O programa abre numa tela que explica o que ele faz. Depois:

1. Clique em **Escolher o EPUB…**.
2. Escolha onde salvar a versão corrigida. O original nunca é sobrescrito.
3. Acompanhe a barra de progresso e as etapas na janela.

Ao terminar, é possível abrir o relatório ou a pasta.

## O que é corrigido

O corretor só aplica o que é seguro. O que é provável mas incerto vai para o
relatório como sugestão, e o texto fica como estava.

**Idioma**
- Detecta o idioma pelo próprio texto (português, inglês ou outro) e corrige o
  `dc:language` se estiver errado ou fora do padrão (`pt_BR` → `pt-BR`).
- Livros na grafia de Portugal são convertidos para a do Brasil: `acção` → `ação`,
  `económico` → `econômico`, `chegámos` → `chegamos`, `há-de` → `há de`. Só a
  grafia muda; vocabulário e construções ("rapariga", "estava a fazer") ficam.
- Em outros idiomas, aplica só as correções de estrutura e espaçamento.

**Ortografia e OCR** (dicionários hunspell do LibreOffice + vocabulário do próprio livro)
- Letras trocadas: `daro` → `claro`, `rnanhã` → `manhã`, `carruagein` → `carruagem`, `moming` → `morning`.
- Dígito no lugar de letra: `Pav1ovna` → `Pavlovna`, `funç5es` → `funções`.
- Nomes próprios: `Rachei` → `Rachel` quando "Rachel" aparece centenas de vezes no livro;
  `Krituzov` → `Kutuzov`, `Benngsen` → `Bennigsen`.
- Acentos perdidos: `EPILOGO` → `EPÍLOGO`, `tambem` → `também`.
- Hífen: `parecialhe` → `parecia-lhe`, `guardachuvas` → `guarda-chuvas`, `orga-nização` → `organização`, `ca- paz` → `capaz`.
- Palavras coladas ou partidas: `estábem` → `está bem`, `aparênciade` → `aparência de`, `co m` → `com`.
- Opcional: atualização para o Acordo Ortográfico (`idéia` → `ideia`, `freqüente` → `frequente`).

Não são alterados: algarismos romanos, siglas, abreviações (`Jr.`), endereços e
e-mails, palavras com prefixo (`autorrelação`, `antissono`), diminutivos e
superlativos (`condezinho`, `comovidíssima`), trechos em francês, italiano, alemão
ou latim, fala gaguejada (`Pa-ra-béns`) e páginas de créditos e ficha catalográfica.

**Espaçamento e pontuação**
- Espaços duplicados, espaço antes de pontuação, espaço ausente depois dela.
- Pontuação duplicada (`,,` → `,`), reticências quebradas (`. . .` → `...`), aspas retas → curvas, apóstrofos.
- Travessão de diálogo em português (`- Olá` → `— Olá`, `disse ele.—Morreu` → `disse ele. — Morreu`).
- Entidades HTML (`&mdash;`, `&nbsp;`) viram os caracteres correspondentes.

**Estrutura**
- Reúne parágrafos partidos na quebra de página do PDF, inclusive palavras hifenizadas
  (sem juntar versos, listas, notas de rodapé nem falas interrompidas).
- Remove parágrafos vazios; se o livro os usa para marcar troca de cena, insere `* * *`.
- Une itálicos e negritos fragmentados; remove páginas de propaganda de sites de download.
- Troca `<title>` genéricos ("Microsoft Word - ...") pelo título do livro.
- Lê arquivos internos corrompidos (com bytes inválidos) em vez de pulá-los.

**Capítulos e sumário**
- Reconhece títulos que viraram parágrafos comuns (`PARTE TRÊS`, `EPÍLOGO`, `Chapter 3`) e une os subtítulos.
- Verifica o `toc.ncx` e o `nav.xhtml` (EPUB3): links para arquivos ou âncoras inexistentes ou entradas fora de ordem.
  Um sumário sem erros é mantido; um quebrado é corrigido ou reconstruído a partir dos títulos.
- Refaz a página de sumário do livro com links, ou conserta os links quebrados.
- Completa o `guide` do OPF e o `dcterms:modified` (obrigatório no EPUB3).

Cada execução gera um **relatório** (`<saída>.relatorio.txt`) com:
- tudo o que foi alterado;
- as sugestões não aplicadas, no formato `errado=certo` (copie as certas para um
  arquivo e use `--substituicoes`);
- trechos suspeitos sem correção automática (pontuação solta, ponto no meio da frase, texto corrompido);
- a lista de palavras desconhecidas que *não* foram mexidas, para revisão manual.

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
| `--manter-portugues-europeu` | não converte livros na grafia de Portugal para a do Brasil |
| `--quebra-cena TEXTO` | separador de cena (padrão `* * *`; `""` para só remover) |

Sem o uv: `pip install lxml pyspellchecker` e `python3 corrigir_epub.py ...`.
Os dicionários são baixados na primeira execução e guardados em
`~/.cache/corrigir_epub` (Linux) ou `%LOCALAPPDATA%\corrigir_epub` (Windows).

## Gerar o executável

Os dois scripts requerem apenas o [uv](https://docs.astral.sh/uv/). Ele baixa o
Python (com Tk), o PyInstaller e as dependências num ambiente isolado; nada é
instalado no sistema. Cada executável precisa ser gerado no próprio sistema:
o PyInstaller não gera um `.exe` a partir do Linux.

```bash
./build.sh              # Linux: gera dist/corrigir-epub (~26 MB)
```

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1   # Windows: gera dist\corrigir-epub.exe
```

### Publicar uma versão

O workflow [`.github/workflows/build.yml`](.github/workflows/build.yml) gera os
dois executáveis no GitHub Actions. Ao enviar uma tag `v*`, ele cria a Release
com os dois arquivos anexados:

```bash
git tag v1.0.0
git push origin v1.0.0
```

Também dá para rodá-lo manualmente (*Actions* → *build* → *Run workflow*); aí os
executáveis ficam só como artefatos da execução.

## Arquivos

- `corrigir_epub.py`: o corretor (biblioteca + linha de comando).
- `corrigir_epub_gui.py`: interface gráfica (Tk) e ponto de entrada do executável.
- `build.sh` / `build.ps1`: geram o executável de arquivo único com PyInstaller (Linux / Windows).
- `preparar_dicionarios.py`: junta os dicionários que os builds embutem.
- `icone/`: ícone do programa (`icone.svg` é a fonte; `icone.png`, `icone.ico` e as versões menores usadas na janela são gerados dele).
- `.github/workflows/build.yml`: builds e Releases no GitHub Actions.

## Dicionários e licenças

- Corretores hunspell pt_BR (VERO), en_US e en_GB: [LibreOffice/dictionaries](https://github.com/LibreOffice/dictionaries).
- Frequências do português: [fserb/pt-br](https://github.com/fserb/pt-br) (MIT).
- Frequências do inglês e palavras em francês, italiano e alemão (para não "corrigir" trechos nesses idiomas): [pyspellchecker](https://github.com/barrust/pyspellchecker) (MIT).
