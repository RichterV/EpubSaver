# corrigir-epub — criado por Vinicius Richter.
#
# Gera dist\corrigir-epub.exe: executável Windows de arquivo único, com interface
# gráfica e dicionários (pt-BR, en_US, en_GB) embutidos — funciona offline.
#
# Requisito: uv (https://docs.astral.sh/uv/). Ele baixa o Python (com Tk), o
# PyInstaller e as dependências num ambiente isolado; nada é instalado no sistema.
#
#   powershell -ExecutionPolicy Bypass -File build.ps1   # gera dist\corrigir-epub.exe
#   .\dist\corrigir-epub.exe                             # abre o seletor de arquivo
$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$PythonVersao = "3.12"
$Nome = "corrigir-epub"
$Build = Join-Path $PWD "build"
$Dist = Join-Path $PWD "dist"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error ("O 'uv' não está instalado. Instale com:`n" +
                 "  powershell -ExecutionPolicy Bypass -c `"irm https://astral.sh/uv/install.ps1 | iex`"")
}

$UvRun = @("run", "--no-project", "--python-preference", "only-managed", "--python", $PythonVersao,
           "--with", "lxml", "--with", "pyspellchecker")

# o nome não pode ser "uv": o PowerShell não diferencia maiúsculas e a função chamaria a si mesma
function Invoke-Uv {
    & uv.exe @args
    if ($LASTEXITCODE -ne 0) { throw "falhou: uv $args" }
}

Write-Host "==> Verificando Python $PythonVersao com Tk"
Invoke-Uv @UvRun python -c "import tkinter, lxml, spellchecker"

Write-Host "==> Preparando dicionários"
Invoke-Uv @UvRun python preparar_dicionarios.py $Build

Write-Host "==> Gerando o executável (PyInstaller)"
# no Windows o separador de --add-data é ";"
Invoke-Uv @UvRun --with pyinstaller pyinstaller `
    --noconfirm --clean --onefile --windowed `
    --name $Nome `
    --icon (Join-Path $PWD "icone\icone.ico") `
    --distpath $Dist `
    --workpath (Join-Path $Build "pyinstaller") `
    --specpath $Build `
    --add-data "$(Join-Path $Build 'dicionarios');dicionarios" `
    --add-data "$(Join-Path $Build 'spellchecker');spellchecker\resources" `
    --add-data "$(Join-Path $PWD 'icone');icone" `
    --log-level WARN `
    corrigir_epub_gui.py

$Exe = Join-Path $Dist "$Nome.exe"
Write-Host ""
Write-Host ("Pronto: $Exe ({0:N1} MB)" -f ((Get-Item $Exe).Length / 1MB))
Write-Host "Execute com: $Exe"
