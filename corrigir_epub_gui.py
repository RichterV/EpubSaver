#!/usr/bin/env python3
"""
Interface gráfica do corrigir_epub — criado por Vinicius Richter.

Escolhe um EPUB, pergunta onde salvar a
versão corrigida e mostra o progresso e cada etapa da correção.

Usa os diálogos nativos do sistema (zenity ou kdialog) quando existem e os do
Tk caso contrário. É o ponto de entrada do executável gerado pelo build.sh.

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
from tkinter import filedialog, font, messagebox, scrolledtext, ttk

import corrigir_epub as ce

TITULO = "Corrigir EPUB"
CREDITO = f"Criado por {ce.AUTOR}"


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
    for prog in ("xdg-open", "gio"):
        if shutil.which(prog):
            cmd = [prog, str(caminho)] if prog == "xdg-open" else [prog, "open", str(caminho)]
            subprocess.Popen(cmd, env=ambiente_do_sistema(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return


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
        raiz.minsize(620, 420)
        raiz.protocol("WM_DELETE_WINDOW", self.fechar)
        estilo = ttk.Style(raiz)
        if "clam" in estilo.theme_names():
            estilo.theme_use("clam")
        fonte_etapa = font.nametofont("TkDefaultFont").copy()
        fonte_etapa.configure(weight="bold", size=fonte_etapa.cget("size") + 1)
        estilo.configure("Etapa.TLabel", font=fonte_etapa)
        estilo.configure("TProgressbar", background="#3b82c4", troughcolor="#e4e4e4", thickness=16)

        quadro = ttk.Frame(raiz, padding=14)
        quadro.pack(fill="both", expand=True)
        self.lbl_arquivos = ttk.Label(quadro, text="", justify="left", wraplength=580)
        self.lbl_arquivos.pack(anchor="w")
        self.lbl_etapa = ttk.Label(quadro, text="", style="Etapa.TLabel")
        self.lbl_etapa.pack(anchor="w", pady=(12, 4))
        linha = ttk.Frame(quadro)
        linha.pack(fill="x")
        self.barra = ttk.Progressbar(linha, maximum=100, mode="determinate")
        self.barra.pack(side="left", fill="x", expand=True)
        self.lbl_pct = ttk.Label(linha, text="0%", width=5, anchor="e")
        self.lbl_pct.pack(side="left", padx=(8, 0))
        self.log = scrolledtext.ScrolledText(quadro, height=14, wrap="word", state="disabled",
                                             font=("TkFixedFont", 9))
        self.log.pack(fill="both", expand=True, pady=(12, 8))
        rodape = ttk.Label(quadro, text=CREDITO, foreground="#777777")
        rodape.pack(side="bottom", anchor="e", pady=(8, 0))
        botoes = ttk.Frame(quadro)
        botoes.pack(fill="x")
        self.btn_fechar = ttk.Button(botoes, text="Fechar", command=self.fechar)
        self.btn_fechar.pack(side="right")
        self.btn_outro = ttk.Button(botoes, text="Corrigir outro...", command=self.novo)
        self.btn_outro.pack(side="right", padx=6)
        self.btn_pasta = ttk.Button(botoes, text="Abrir pasta", command=lambda: abrir_no_sistema(self.saida.parent))
        self.btn_pasta.pack(side="left")
        self.btn_relatorio = ttk.Button(botoes, text="Abrir relatório", command=lambda: abrir_no_sistema(self.relatorio))
        self.btn_relatorio.pack(side="left", padx=6)
        self.botoes_fim(False)

        raiz.after(50, self.consumir_fila)
        if entrada and saida:
            raiz.after(100, lambda: self.iniciar(Path(entrada), Path(saida)))
        else:
            raiz.withdraw()
            raiz.after(100, self.novo)

    # -- fluxo ------------------------------------------------------------
    def novo(self):
        entrada = escolher_entrada(self.raiz, self.ultima_pasta)
        if not entrada:
            if not self.raiz.winfo_viewable():
                self.raiz.destroy()
            return
        entrada = Path(entrada)
        self.ultima_pasta = entrada.parent
        sugestao = entrada.with_name(entrada.stem + "_corrigido.epub")
        while True:
            saida = escolher_saida(self.raiz, sugestao)
            if not saida:
                if not self.raiz.winfo_viewable():
                    self.raiz.destroy()
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
        self.raiz.deiconify()
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
        if r["suspeitas"]:
            self.escrever("")
            self.escrever(f"{r['suspeitas']} palavras desconhecidas não foram alteradas; "
                          "veja a lista no relatório.")
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
        self.btn_outro.state(["!disabled"])
        self.btn_fechar.state(["!disabled"])
        messagebox.showerror(TITULO, erro.strip().splitlines()[-1], parent=self.raiz)
        if self.fechar_ao_terminar:
            self.raiz.after(500, self.raiz.destroy)

    def botoes_fim(self, ativo):
        for b in (self.btn_relatorio, self.btn_pasta, self.btn_outro):
            b.state(["!disabled"] if ativo else ["disabled"])

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
    raiz = tk.Tk()
    Aplicativo(raiz, *(args[:2] if len(args) >= 2 else (None, None)),
               fechar_ao_terminar="--fechar-ao-terminar" in sys.argv)
    raiz.mainloop()


if __name__ == "__main__":
    main()
