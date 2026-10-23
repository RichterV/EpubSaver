#!/usr/bin/env python3
"""
Interface gráfica do corrigir_epub — criado por Vinicius Richter.

Abre numa tela inicial que explica o que o programa faz; o botão escolhe o
EPUB, pergunta onde salvar a versão corrigida e mostra o progresso e cada
etapa da correção.

No Linux usa os diálogos nativos do sistema (zenity ou kdialog) quando existem
e os do Tk caso contrário; no Windows os do Tk já são os nativos. É o ponto de
entrada do executável gerado pelo build.sh (Linux) e pelo build.ps1 (Windows).

Uso direto (sem diálogos, útil para testes):
    python3 corrigir_epub_gui.py entrada.epub saida.epub [--fechar-ao-terminar]
"""

import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font, messagebox, ttk

import corrigir_epub as ce

TITULO = "EpubSaver"
CREDITO = f"Criado por {ce.AUTOR}"
# no executável os ícones vêm embutidos (sys._MEIPASS); rodando do código, estão em icone/
PASTA_ICONES = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "icone"

# cores do ícone: fundo azul-petróleo, páginas creme, cavalo-marinho laranja
AZUL_CLARO = "#1f8fa8"
AZUL = "#0d4f66"
AZUL_ESCURO = "#0a3a4c"
CREME = "#fdf6e3"
CREME_ESCURO = "#f3e9cf"
LINHA = "#d8cba6"
LARANJA = "#f0643a"
LARANJA_ESCURO = "#d24f28"
TEXTO = AZUL_ESCURO
TEXTO_SUAVE = "#5e7379"

O_QUE_CORRIGE = [
    "Palavras trocadas pelo reconhecimento de texto (OCR) e acentos perdidos",
    "Espaços a mais ou faltando, pontuação, aspas e travessões de diálogo",
    "Parágrafos partidos na quebra de página e palavras coladas ou separadas",
    "Títulos de capítulo, sumário e links quebrados",
    "Livros na grafia de Portugal, convertidos para a do Brasil",
]


# --------------------------------------------------------------------------
# Diálogos de arquivo
# --------------------------------------------------------------------------
def ambiente_do_sistema():
    """O PyInstaller troca o LD_LIBRARY_PATH; programas do sistema precisam do original."""
    env = dict(os.environ)
    if "LD_LIBRARY_PATH_ORIG" in env:
        env["LD_LIBRARY_PATH"] = env["LD_LIBRARY_PATH_ORIG"]
    elif getattr(sys, "frozen", False):
        env.pop("LD_LIBRARY_PATH", None)
    return env


def dialogo_externo(cmd):
    """Roda zenity/kdialog. Devolve o caminho escolhido, "" se cancelado, None se falhou."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, env=ambiente_do_sistema())
    except OSError:
        return None
    if r.returncode == 0:
        return r.stdout.strip()
    return "" if r.returncode == 1 else None


def escolher_entrada(raiz, pasta):
    if shutil.which("zenity"):
        c = dialogo_externo(["zenity", "--file-selection", f"--title={TITULO}: escolha o EPUB",
                             f"--filename={pasta}/", "--file-filter=EPUB | *.epub *.EPUB",
                             "--file-filter=Todos os arquivos | *"])
        if c is not None:
            return c
    if shutil.which("kdialog"):
        c = dialogo_externo(["kdialog", "--title", f"{TITULO}: escolha o EPUB",
                             "--getopenfilename", str(pasta), "EPUB (*.epub *.EPUB)"])
        if c is not None:
            return c
    return filedialog.askopenfilename(parent=raiz, title=f"{TITULO}: escolha o EPUB", initialdir=pasta,
                                      filetypes=[("EPUB", "*.epub *.EPUB"), ("Todos", "*")])


def escolher_saida(raiz, sugestao):
    if shutil.which("zenity"):
        c = dialogo_externo(["zenity", "--file-selection", "--save", "--confirm-overwrite",
                             f"--title={TITULO}: salvar o EPUB corrigido como", f"--filename={sugestao}",
                             "--file-filter=EPUB | *.epub"])
        if c is not None:
            return c
    if shutil.which("kdialog"):
        c = dialogo_externo(["kdialog", "--title", f"{TITULO}: salvar o EPUB corrigido como",
                             "--getsavefilename", str(sugestao), "EPUB (*.epub)"])
        if c is not None:
            return c
    return filedialog.asksaveasfilename(parent=raiz, title=f"{TITULO}: salvar o EPUB corrigido como",
                                        initialdir=sugestao.parent, initialfile=sugestao.name,
                                        defaultextension=".epub", filetypes=[("EPUB", "*.epub")])


def abrir_no_sistema(caminho):
    if sys.platform == "win32":
        os.startfile(caminho)  # noqa: S606 - abre no programa padrão do Windows
        return
    for prog in ("xdg-open", "gio"):
        if shutil.which(prog):
            cmd = [prog, str(caminho)] if prog == "xdg-open" else [prog, "open", str(caminho)]
            subprocess.Popen(cmd, env=ambiente_do_sistema(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return


# --------------------------------------------------------------------------
# Peças visuais
# --------------------------------------------------------------------------
def imagem(nome):
    caminho = PASTA_ICONES / nome
    try:
        return tk.PhotoImage(file=str(caminho)) if caminho.exists() else None
    except tk.TclError:
        return None


def misturar(c1, c2, t):
    """Cor entre c1 e c2 (t de 0 a 1)."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


class Cabecalho(tk.Canvas):
    """Faixa em degradê azul, como o fundo do ícone, com o ícone, o nome e um subtítulo."""

    def __init__(self, pai, icone, titulo, subtitulo, fontes, altura):
        super().__init__(pai, height=altura, highlightthickness=0, bd=0, bg=AZUL)
        self.icone, self.titulo, self.subtitulo, self.fontes, self.altura = icone, titulo, subtitulo, fontes, altura
        self.bind("<Configure>", lambda e: self.desenhar())

    def desenhar(self):
        self.delete("all")
        largura = max(self.winfo_width(), 1)
        for y in range(0, self.altura, 2):
            self.create_rectangle(0, y, largura, y + 2, outline="", fill=misturar(AZUL_CLARO, AZUL, y / self.altura))
        self.create_rectangle(0, self.altura - 4, largura, self.altura, outline="", fill=LARANJA)
        x = 28
        if self.icone is not None:
            self.create_image(x, (self.altura - 4) // 2, image=self.icone, anchor="w")
            x += self.icone.width() + 20
        meio = (self.altura - 4) // 2
        self.create_text(x, meio - 4, text=self.titulo, anchor="sw", fill=CREME, font=self.fontes["titulo"])
        self.create_text(x, meio + 4, text=self.subtitulo, anchor="nw", fill="#cfe8ee", font=self.fontes["subtitulo"])


def botao(pai, texto, comando, primario=True, fonte=None):
    """Botão chato nas cores do ícone (o tk.Button aceita cores em todos os sistemas)."""
    cor, hover, frente = (LARANJA, LARANJA_ESCURO, "#ffffff") if primario else (CREME_ESCURO, LINHA, TEXTO)
    b = tk.Button(pai, text=texto, command=comando, bg=cor, fg=frente, activebackground=hover,
                  activeforeground=frente, relief="flat", bd=0, cursor="hand2", font=fonte,
                  padx=22 if primario else 14, pady=10 if primario else 6, highlightthickness=0,
                  disabledforeground="#b9a98a")
    b.bind("<Enter>", lambda e: b["state"] != "disabled" and b.config(bg=hover))
    b.bind("<Leave>", lambda e: b.config(bg=cor))
    return b


# --------------------------------------------------------------------------
# Janela
# --------------------------------------------------------------------------
class SaidaParaFila:
    """Redireciona prints (avisos, downloads) do corretor para o log da janela."""

    def __init__(self, fila):
        self.fila = fila

    def write(self, texto):
        if texto.strip():
            self.fila.put(("log", texto.strip()))

    def flush(self):
        pass


class Aplicativo:
    def __init__(self, raiz, entrada=None, saida=None, fechar_ao_terminar=False):
        self.raiz = raiz
        self.fila = queue.Queue()
        self.dicionarios = {}  # reaproveitados entre livros
        self.fechar_ao_terminar = fechar_ao_terminar
        self.trabalhando = False
        self.ultima_pasta = Path.home()
        self.relatorio = None
        self.saida = None
        self.inicio = 0.0

        raiz.title(f"{TITULO} — {CREDITO}")
        raiz.configure(bg=CREME)
        raiz.geometry("720x640")
        raiz.minsize(620, 560)
        raiz.protocol("WM_DELETE_WINDOW", self.fechar)
        self.icone_janela = imagem("icone.png")
        if self.icone_janela is not None:
            raiz.iconphoto(True, self.icone_janela)
        self.icone_grande = imagem("icone-112.png")

        base = font.nametofont("TkDefaultFont")
        familia, tamanho = base.cget("family"), abs(base.cget("size")) or 10
        self.fontes = {
            "titulo": font.Font(family=familia, size=tamanho + 16, weight="bold"),
            "subtitulo": font.Font(family=familia, size=tamanho + 2),
            "texto": font.Font(family=familia, size=tamanho + 1),
            "destaque": font.Font(family=familia, size=tamanho + 2, weight="bold"),
            "botao": font.Font(family=familia, size=tamanho + 2, weight="bold"),
            "pequena": font.Font(family=familia, size=tamanho),
        }
        estilo = ttk.Style(raiz)
        estilo.theme_use("clam")  # o único tema que deixa trocar as cores da barra de progresso
        estilo.configure("Laranja.Horizontal.TProgressbar", background=LARANJA, troughcolor=CREME_ESCURO,
                         bordercolor=CREME_ESCURO, lightcolor=LARANJA, darkcolor=LARANJA, thickness=14)

        Cabecalho(raiz, self.icone_grande, TITULO, "Corretor de EPUBs em português e inglês",
                  self.fontes, altura=150).pack(fill="x")
        tk.Label(raiz, text=CREDITO, bg=CREME, fg=TEXTO_SUAVE, font=self.fontes["pequena"]) \
            .pack(side="bottom", anchor="e", padx=16, pady=(0, 10))
        self.tela_inicial = self.montar_inicio()
        self.tela_progresso = self.montar_progresso()

        raiz.after(50, self.consumir_fila)
        if entrada and saida:
            raiz.after(100, lambda: self.iniciar(Path(entrada), Path(saida)))
        else:
            self.mostrar(self.tela_inicial)

    # -- telas ------------------------------------------------------------
    def montar_inicio(self):
        tela = tk.Frame(self.raiz, bg=CREME, padx=32, pady=20)
        tk.Label(tela, text="Livros convertidos de PDF ou escaneados costumam vir cheios de erros. "
                            "O EpubSaver lê o EPUB inteiro e corrige:",
                 bg=CREME, fg=TEXTO, font=self.fontes["texto"], justify="left", anchor="w", wraplength=620) \
            .pack(fill="x")
        lista = tk.Frame(tela, bg=CREME, pady=8)
        lista.pack(fill="x")
        for item in O_QUE_CORRIGE:
            linha = tk.Frame(lista, bg=CREME)
            linha.pack(fill="x", pady=3)
            ponto = tk.Canvas(linha, width=14, height=14, bg=CREME, highlightthickness=0)
            ponto.create_oval(3, 3, 11, 11, fill=LARANJA, outline="")
            ponto.pack(side="left", padx=(4, 10))
            tk.Label(linha, text=item, bg=CREME, fg=TEXTO, font=self.fontes["texto"], anchor="w",
                     justify="left", wraplength=580).pack(side="left", fill="x")
        nota = tk.Frame(tela, bg=CREME_ESCURO, padx=14, pady=10)
        nota.pack(fill="x", pady=(10, 0))
        tk.Label(nota, text="O arquivo original nunca é alterado: você escolhe onde salvar a versão corrigida. "
                            "Correções incertas não são aplicadas — ficam no relatório para você revisar.",
                 bg=CREME_ESCURO, fg=TEXTO, font=self.fontes["pequena"], justify="left", anchor="w",
                 wraplength=600).pack(fill="x")
        botao(tela, "Escolher o EPUB…", self.novo, fonte=self.fontes["botao"]).pack(pady=(22, 0))
        tk.Label(tela, text="Funciona offline. Os dicionários já vêm no programa.", bg=CREME, fg=TEXTO_SUAVE,
                 font=self.fontes["pequena"]).pack(pady=(8, 0))
        return tela

    def montar_progresso(self):
        tela = tk.Frame(self.raiz, bg=CREME, padx=20, pady=14)
        self.lbl_arquivos = tk.Label(tela, text="", bg=CREME, fg=TEXTO_SUAVE, justify="left", anchor="w",
                                     wraplength=660, font=self.fontes["pequena"])
        self.lbl_arquivos.pack(fill="x")
        self.lbl_etapa = tk.Label(tela, text="", bg=CREME, fg=TEXTO, anchor="w", font=self.fontes["destaque"])
        self.lbl_etapa.pack(fill="x", pady=(12, 6))
        linha = tk.Frame(tela, bg=CREME)
        linha.pack(fill="x")
        self.barra = ttk.Progressbar(linha, maximum=100, mode="determinate", style="Laranja.Horizontal.TProgressbar")
        self.barra.pack(side="left", fill="x", expand=True)
        self.lbl_pct = tk.Label(linha, text="0%", width=5, anchor="e", bg=CREME, fg=TEXTO, font=self.fontes["pequena"])
        self.lbl_pct.pack(side="left", padx=(8, 0))
        moldura = tk.Frame(tela, bg=LINHA, padx=1, pady=1)
        moldura.pack(fill="both", expand=True, pady=(12, 10))
        rolagem = ttk.Scrollbar(moldura, orient="vertical")
        rolagem.pack(side="right", fill="y")
        self.log = tk.Text(moldura, height=12, wrap="word", state="disabled", font=("TkFixedFont", 9),
                           bg="#fffdf7", fg=TEXTO, relief="flat", bd=0, padx=8, pady=6,
                           yscrollcommand=rolagem.set)
        self.log.pack(fill="both", expand=True)
        rolagem.config(command=self.log.yview)
        botoes = tk.Frame(tela, bg=CREME)
        botoes.pack(fill="x")
        self.btn_fechar = botao(botoes, "Fechar", self.fechar, primario=False, fonte=self.fontes["pequena"])
        self.btn_fechar.pack(side="right")
        self.btn_outro = botao(botoes, "Corrigir outro…", self.novo, fonte=self.fontes["pequena"])
        self.btn_outro.config(padx=14, pady=6)
        self.btn_outro.pack(side="right", padx=8)
        self.btn_pasta = botao(botoes, "Abrir pasta", lambda: abrir_no_sistema(self.saida.parent), primario=False,
                               fonte=self.fontes["pequena"])
        self.btn_pasta.pack(side="left")
        self.btn_relatorio = botao(botoes, "Abrir relatório", lambda: abrir_no_sistema(self.relatorio),
                                   primario=False, fonte=self.fontes["pequena"])
        self.btn_relatorio.pack(side="left", padx=8)
        self.botoes_fim(False)
        return tela

    def mostrar(self, tela):
        for t in (self.tela_inicial, self.tela_progresso):
            if t is not tela:
                t.pack_forget()
        tela.pack(fill="both", expand=True)

    # -- fluxo ------------------------------------------------------------
    def novo(self):
        entrada = escolher_entrada(self.raiz, self.ultima_pasta)
        if not entrada:
            return
        entrada = Path(entrada)
        self.ultima_pasta = entrada.parent
        sugestao = entrada.with_name(entrada.stem + "_corrigido.epub")
        while True:
            saida = escolher_saida(self.raiz, sugestao)
            if not saida:
                return
            saida = Path(saida)
            if saida.suffix.lower() != ".epub":
                saida = saida.with_name(saida.name + ".epub")
            if saida.resolve() == entrada.resolve():
                messagebox.showwarning(TITULO, "Escolha um nome diferente do arquivo original — "
                                               "o original não é sobrescrito.", parent=self.raiz)
                continue
            break
        self.iniciar(entrada, saida)

    def iniciar(self, entrada, saida):
        self.saida = saida
        self.relatorio = None
        self.trabalhando = True
        self.botoes_fim(False)
        self.btn_outro.config(state="disabled")
        self.mostrar(self.tela_progresso)
        self.lbl_arquivos.config(text=f"Original:  {entrada}\nCorrigido: {saida}")
        self.limpar_log()
        self.inicio = time.monotonic()
        self.atualizar(0, "Iniciando...")
        threading.Thread(target=self.trabalhar, args=(entrada, saida), daemon=True).start()

    def trabalhar(self, entrada, saida):
        stdout, stderr = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = SaidaParaFila(self.fila)
        try:
            resumo = ce.processar(entrada, saida, ce.opcoes_padrao(), self.dicionarios,
                                  progresso=lambda f, m: self.fila.put(("progresso", f, m)))
            self.fila.put(("fim", resumo))
        except Exception:  # noqa: BLE001 - qualquer falha vai para a janela
            self.fila.put(("erro", traceback.format_exc()))
        finally:
            sys.stdout, sys.stderr = stdout, stderr

    # -- atualização da janela (thread principal) --------------------------
    def consumir_fila(self):
        try:
            while True:
                msg = self.fila.get_nowait()
                tipo = msg[0]
                if tipo == "progresso":
                    self.atualizar(msg[1] * 100, msg[2])
                elif tipo == "log":
                    self.escrever(msg[1])
                elif tipo == "fim":
                    self.terminar(msg[1])
                elif tipo == "erro":
                    self.falhar(msg[1])
        except queue.Empty:
            pass
        self.raiz.after(50, self.consumir_fila)

    def atualizar(self, pct, etapa):
        self.barra["value"] = pct
        self.lbl_pct.config(text=f"{pct:.0f}%")
        self.lbl_etapa.config(text=etapa)
        self.escrever(f"[{time.monotonic() - self.inicio:5.1f}s] {etapa}")

    def terminar(self, r):
        self.trabalhando = False
        self.relatorio = r["relatorio"]
        nomes_idioma = {"pt": "português", "en": "inglês"}
        self.lbl_etapa.config(text=f"Pronto: {r['total']} correções "
                                   f"({nomes_idioma.get(r['idioma'], 'outro idioma')})")
        self.escrever("")
        self.escrever("Estrutura do EPUB:")
        for e in r["estrutura"]:
            self.escrever(f"  • {e}")
        self.escrever("")
        self.escrever("Correções por tipo:")
        for cat, n in r["contagem"]:
            self.escrever(f"  {n:6d}  {cat}")
        if r.get("sugestoes"):
            self.escrever("")
            self.escrever("1 correção incerta não foi aplicada" if r["sugestoes"] == 1 else
                          f"{r['sugestoes']} correções incertas não foram aplicadas")
            self.escrever("  (veja as sugestões no relatório)")
        if r["suspeitas"]:
            self.escrever("")
            self.escrever("1 palavra desconhecida não foi alterada" if r["suspeitas"] == 1 else
                          f"{r['suspeitas']} palavras desconhecidas não foram alteradas")
            self.escrever("  (veja a lista no relatório)")
        self.escrever("")
        self.escrever(f"EPUB corrigido: {self.saida}")
        self.escrever(f"Relatório:      {self.relatorio}")
        self.botoes_fim(True)
        if self.fechar_ao_terminar:
            self.raiz.after(1500, self.raiz.destroy)

    def falhar(self, erro):
        self.trabalhando = False
        self.lbl_etapa.config(text="Erro: não foi possível corrigir este EPUB")
        self.escrever("")
        self.escrever(erro)
        self.botoes_fim(False)
        self.btn_outro.config(state="normal")
        messagebox.showerror(TITULO, erro.strip().splitlines()[-1], parent=self.raiz)
        if self.fechar_ao_terminar:
            self.raiz.after(500, self.raiz.destroy)

    def botoes_fim(self, ativo):
        for b in (self.btn_relatorio, self.btn_pasta, self.btn_outro):
            b.config(state="normal" if ativo else "disabled")

    def escrever(self, texto):
        self.log.config(state="normal")
        self.log.insert("end", texto + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def limpar_log(self):
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

    def fechar(self):
        if self.trabalhando and not messagebox.askyesno(
                TITULO, "A correção ainda está em andamento. Fechar mesmo assim?", parent=self.raiz):
            return
        self.raiz.destroy()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if sys.platform == "win32":
        try:  # sem isso o Windows amplia a janela e o texto fica borrado em telas com escala
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    raiz = tk.Tk()
    Aplicativo(raiz, *(args[:2] if len(args) >= 2 else (None, None)),
               fechar_ao_terminar="--fechar-ao-terminar" in sys.argv)
    raiz.mainloop()


if __name__ == "__main__":
    main()
