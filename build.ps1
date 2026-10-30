<#
  Gera o MU Sentinel para distribuir: venv limpo -> testes -> dist\MUSentinel\ -> MUSentinel-vX.Y.Z-win64.zip

  Uso (PowerShell, na pasta do projeto):
      .\build.ps1                # completo
      .\build.ps1 -SemTestes     # pula o pytest (mais rápido; não use para release)

  Assinatura de código (opcional): defina MUSENTINEL_SIGN_CMD com o comando que assina um arquivo,
  ex.: $env:MUSENTINEL_SIGN_CMD = 'signtool sign /a /fd SHA256 /tr http://timestamp.digicert.com /td SHA256'
  O caminho do .exe é acrescentado no final do comando.
#>
param([switch]$SemTestes)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what falhou (código $LASTEXITCODE)" } }

# Python 3.12
$py = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
if (-not (Test-Path $py)) { $py = (Get-Command py -ErrorAction Stop).Source; $pyArgs = @("-3.12") } else { $pyArgs = @() }

$version = & $py @pyArgs -c "import tomllib;print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
Check "ler versão"
$zip = "MUSentinel-v$version-win64.zip"
Write-Host "MU Sentinel $version"

Step "Ambiente limpo (.build-venv)"
foreach ($d in ".build-venv", "build", "dist") { if (Test-Path $d) { Remove-Item -Recurse -Force $d } }
& $py @pyArgs -m venv .build-venv; Check "criar venv"
$vpy = ".build-venv\Scripts\python.exe"
& $vpy -m pip install --upgrade pip --quiet; Check "pip"
& $vpy -m pip install ".[dev]" pyinstaller --quiet; Check "instalar dependências"

# O RapidOCR puxa o opencv-python completo; o app usa só o headless (sem GUI do OpenCV).
# Os dois instalam o mesmo módulo cv2, então fica só um.
& $vpy -m pip uninstall -y opencv-python opencv-python-headless --quiet; Check "remover opencv"
& $vpy -m pip install opencv-python-headless --quiet; Check "instalar opencv-headless"

if (-not $SemTestes) {
    Step "Testes"
    & $vpy -m pytest -q; Check "testes"
}

Step "PyInstaller (onedir, sem UPX)"
& $vpy -m PyInstaller --noconfirm --clean musentinel.spec; Check "PyInstaller"
$out = "dist\MUSentinel"
Copy-Item LEIA-ME.md $out
# Aparece em primeiro ao lado do exe para quem abre o zip sem extrair
Copy-Item packaging\EXTRAIA-ANTES.txt "$out\!! EXTRAIA O ZIP ANTES DE ABRIR !!.txt"

if ($env:MUSENTINEL_SIGN_CMD) {
    Step "Assinando o executável"
    cmd /c "$env:MUSENTINEL_SIGN_CMD `"$out\MUSentinel.exe`""; Check "assinatura"
}

Step "Smoke test do executável (abre, carrega config, roda 1 ciclo, fecha)"
$tmp = Join-Path $env:TEMP ("musentinel-smoke-" + [guid]::NewGuid())
New-Item -ItemType Directory $tmp | Out-Null
$oldAppData = $env:APPDATA
try {
    $env:APPDATA = $tmp  # dados zerados, como na máquina de um colega
    $p = Start-Process "$out\MUSentinel.exe" -ArgumentList "--smoke-test" -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw "smoke test falhou (código $($p.ExitCode)); veja $tmp\MUSentinel\logs" }
    Write-Host (Get-Content "$tmp\MUSentinel\smoke_test.txt")
} finally {
    $env:APPDATA = $oldAppData
}

Step "Compactando $zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $out -DestinationPath $zip -CompressionLevel Optimal
$mb = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host "`nPronto: $zip ($mb MB)" -ForegroundColor Green
Write-Host "Antes de distribuir: teste numa máquina/VM sem Python (descompacte e rode MUSentinel.exe)."
