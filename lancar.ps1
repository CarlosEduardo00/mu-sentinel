<#
  Lança uma versão nova do MU Sentinel no GitHub (quem usa o app recebe o aviso de atualização).

  Antes de rodar:
    1. Mude o número em src\musentinel\_version.py (ex.: "0.2.4").
    2. Escreva a seção "## [0.2.4] - AAAA-MM-DD" no topo do CHANGELOG.md.
    3. Faça o commit dessas mudanças (o script exige a pasta sem alterações pendentes).

  Uso (PowerShell, na pasta do projeto):
      .\lancar.ps1               # gera o zip (com testes), cria a tag e publica a release
      .\lancar.ps1 -Rascunho     # publica como rascunho (só você vê; o app não avisa ninguém)

  O que ele faz: build.ps1 completo -> soma SHA-256 do zip -> tag vX.Y.Z -> git push ->
  gh release create com o zip, o .sha256 e as novidades do CHANGELOG.
#>
param([switch]$Rascunho)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what falhou (código $LASTEXITCODE)" } }

$version = [regex]::Match((Get-Content "src\musentinel\_version.py" -Raw -Encoding UTF8), '__version__ = "([^"]+)"').Groups[1].Value
if (-not $version) { throw "não achei __version__ em src\musentinel\_version.py" }
$tag = "v$version"
$zip = "MUSentinel-v$version-win64.zip"
Write-Host "Lançando MU Sentinel $version ($tag)"

Step "Conferindo"
# (cmd /c: no PowerShell 5.1, redirecionar o stderr de um programa com ErrorActionPreference=Stop vira erro)
cmd /c "gh auth status >nul 2>&1"
if ($LASTEXITCODE -ne 0) { throw "o gh não está logado: rode 'gh auth login' uma vez" }
$dirty = git status --porcelain
if ($dirty) { throw "há alterações sem commit:`n$dirty`nFaça o commit antes de lançar." }
$branch = git rev-parse --abbrev-ref HEAD
if ($branch -ne "main") { throw "lance a partir da branch main (está em $branch)" }
cmd /c "git rev-parse -q --verify refs/tags/$tag >nul 2>&1"
if ($LASTEXITCODE -eq 0) { throw "a tag $tag já existe: mude o número em _version.py" }

$changelog = Get-Content "CHANGELOG.md" -Raw -Encoding UTF8
$m = [regex]::Match($changelog, "(?ms)^## \[$([regex]::Escape($version))\][^\n]*\n(.*?)(?=^## \[|\z)")
if (-not $m.Success -or -not $m.Groups[1].Value.Trim()) {
    throw "o CHANGELOG.md não tem a seção '## [$version]' com as novidades"
}
$notes = $m.Groups[1].Value.Trim()
$notes += "`n`n---`nComo instalar pela primeira vez: baixe o $zip abaixo, clique com o botão direito -> Extrair tudo, " +
          "e abra o MUSentinel.exe. Quem já usa o app recebe esta versão pelo aviso de atualização."
$notesFile = Join-Path $env:TEMP "musentinel-notas-$version.md"
[IO.File]::WriteAllText($notesFile, $notes)

Step "Build completo (testes + exe + smoke test)"
& .\build.ps1
if (-not (Test-Path $zip)) { throw "o build não gerou $zip" }

Step "Soma de conferência (SHA-256)"
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
[IO.File]::WriteAllText((Join-Path $PSScriptRoot "$zip.sha256"), "$hash  $zip`n")
Write-Host "$hash  $zip"

Step "Tag $tag e envio para o GitHub"
git tag -a $tag -m "MU Sentinel $version"; Check "git tag"
git push origin main; Check "git push"
git push origin $tag; Check "git push da tag"

Step "Release no GitHub"
$ghArgs = @("release", "create", $tag, $zip, "$zip.sha256", "--title", "MU Sentinel $version",
            "--notes-file", $notesFile, "--verify-tag")
if ($Rascunho) { $ghArgs += "--draft" }
gh @ghArgs; Check "gh release create"
Remove-Item $notesFile -ErrorAction SilentlyContinue

$url = gh release view $tag --json url --jq .url
Write-Host "`nPronto: $url" -ForegroundColor Green
if ($Rascunho) { Write-Host "É um rascunho: publique pela página quando quiser (aí o app passa a avisar)." }
else { Write-Host "Quem abrir o MU Sentinel nas próximas horas recebe o aviso da versão $version." }
