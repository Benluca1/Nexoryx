#Requires -Version 5.1
<#
.SYNOPSIS
    Nexoryx — Windows-Installer (Admin-Modus)
    Ausgeliefert von http://192.168.13.100:3007/install.ps1

.DESCRIPTION
    Installiert automatisch: winget, Python 3.12, git, venv,
    alle Python-Pakete, Ollama, Nexoryx.
    Als Administrator ausfuehren:
        irm http://192.168.13.100:3007/install.ps1 | iex
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ADMIN_ENABLE_TOKEN = "bYRQCHmrBRvFcNmWlkvMwMnfgSs1gY81fegkokL_IeI"
$REPO_URL  = if ($env:NEXORYX_REPO) { $env:NEXORYX_REPO } else { "https://github.com/Benluca1/Nexoryx.git" }
$REPO_DIR  = if ($env:NEXORYX_DIR)  { $env:NEXORYX_DIR  } else { "$env:USERPROFILE\.nexoryx\src-repo" }
$VENV_DIR  = "$env:USERPROFILE\.nexoryx\venv"
$LOG_DIR   = "$env:USERPROFILE\.nexoryx\logs"

# ── Farb-Hilfsfunktionen ─────────────────────────────────────────────────────

function Write-Ok   { param($msg) Write-Host "  [OK] $msg"   -ForegroundColor Green  }
function Write-Warn { param($msg) Write-Host "  [!]  $msg"   -ForegroundColor Yellow }
function Write-Err  { param($msg) Write-Host "  [X]  $msg"   -ForegroundColor Red    }
function Write-Step { param($msg) Write-Host "`n>> $msg"     -ForegroundColor Cyan   }

# ── Banner ────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  ══════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "    N  E  X  O  R  Y  X   Installer  (Windows / Admin)" -ForegroundColor Cyan
Write-Host "  ══════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

function Test-Command { param($name) return [bool](Get-Command $name -ErrorAction SilentlyContinue) }

function Install-WingetPkg {
    param($id, $label)
    Write-Host "  Installiere $label ..." -NoNewline
    try {
        $r = winget install --id $id --silent --accept-package-agreements --accept-source-agreements 2>&1
        if ($LASTEXITCODE -eq 0 -or $LASTEXITCODE -eq -1978335135) {
            # -1978335135 = APPINSTALLER_ERROR_ALREADY_INSTALLED
            Write-Host " OK" -ForegroundColor Green
            return $true
        } else {
            Write-Host " Fehler (Code $LASTEXITCODE)" -ForegroundColor Yellow
            return $false
        }
    } catch {
        Write-Host " Fehler: $_" -ForegroundColor Yellow
        return $false
    }
}

function Add-ToUserPath {
    param($dir)
    $current = [System.Environment]::GetEnvironmentVariable('PATH', 'User') ?? ''
    if ($current -notlike "*$dir*") {
        [System.Environment]::SetEnvironmentVariable('PATH', "$dir;$current", 'User')
        $env:PATH = "$dir;$env:PATH"
        Write-Ok "PATH aktualisiert: $dir"
    }
}

function Invoke-Step {
    param($name, [scriptblock]$block)
    Write-Step $name
    try { & $block }
    catch { Write-Warn "Fehler in '$name': $_" }
}

# ── Schritt 1: Execution Policy ───────────────────────────────────────────────

Write-Step "1/8  Execution Policy"
$policy = Get-ExecutionPolicy -Scope CurrentUser
if ($policy -eq 'Restricted' -or $policy -eq 'Undefined') {
    Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned -Force
    Write-Ok "ExecutionPolicy auf RemoteSigned gesetzt"
} else {
    Write-Ok "ExecutionPolicy: $policy"
}

# ── Schritt 2: winget sicherstellen ───────────────────────────────────────────

Write-Step "2/8  winget (Windows-Paketmanager)"
if (-not (Test-Command 'winget')) {
    Write-Host "  winget nicht gefunden — wird ueber Microsoft Store nachinstalliert ..."
    try {
        # App Installer (enthaelt winget) aus dem Store
        $uri = "https://aka.ms/getwinget"
        $tmp = "$env:TEMP\AppInstaller.msixbundle"
        Write-Host "  Download App Installer ..." -NoNewline
        Invoke-WebRequest -Uri $uri -OutFile $tmp -UseBasicParsing
        Write-Host " OK" -ForegroundColor Green
        Add-AppxPackage -Path $tmp -ForceApplicationShutdown
        Write-Ok "winget installiert — Terminal neu starten falls Fehler auftreten"
    } catch {
        Write-Warn "winget konnte nicht automatisch installiert werden."
        Write-Warn "Bitte manuell: Microsoft Store -> 'App Installer' installieren."
        Write-Warn "Danach dieses Script erneut ausfuehren."
        exit 1
    }
} else {
    Write-Ok "winget $(winget --version)"
}

# ── Schritt 3: Git ────────────────────────────────────────────────────────────

Write-Step "3/8  Git"
if (Test-Command 'git') {
    Write-Ok "git $(git --version)"
} else {
    $ok = Install-WingetPkg 'Git.Git' 'Git'
    if ($ok) {
        # Git-Pfade sofort in dieser Session verfuegbar machen
        $gitPaths = @(
            "$env:ProgramFiles\Git\cmd",
            "$env:ProgramFiles\Git\bin"
        )
        foreach ($p in $gitPaths) {
            if (Test-Path $p) { $env:PATH = "$p;$env:PATH" }
        }
        if (Test-Command 'git') { Write-Ok "git $(git --version)" }
        else { Write-Warn "git: Terminal neu starten falls Befehle fehlen" }
    } else {
        Write-Err "git konnte nicht installiert werden — bitte manuell von git-scm.com"
        exit 1
    }
}

# ── Schritt 4: Python 3.12 ────────────────────────────────────────────────────

Write-Step "4/8  Python 3.12"

function Get-Python {
    foreach ($candidate in @('python', 'python3', 'py')) {
        if (Test-Command $candidate) {
            try {
                $ver = & $candidate -c "import sys; ok=sys.version_info>=(3,11); print(ok,sys.executable)" 2>$null
                if ($ver -and $ver.StartsWith('True')) {
                    return ($ver -split ' ', 2)[1].Trim()
                }
            } catch {}
        }
    }
    # py launcher mit Version
    if (Test-Command 'py') {
        try {
            $path = & py -3.12 -c "import sys; print(sys.executable)" 2>$null
            if ($path) { return $path.Trim() }
            $path = & py -3.11 -c "import sys; print(sys.executable)" 2>$null
            if ($path) { return $path.Trim() }
        } catch {}
    }
    return $null
}

$PYTHON = Get-Python
if ($PYTHON) {
    $ver = & $PYTHON --version 2>&1
    Write-Ok "Python: $ver ($PYTHON)"
} else {
    Write-Host "  Python 3.11+ nicht gefunden — installiere Python 3.12 ..."
    $ok = Install-WingetPkg 'Python.Python.3.12' 'Python 3.12'
    if (-not $ok) {
        Write-Warn "Versuch mit Python 3.11 ..."
        $ok = Install-WingetPkg 'Python.Python.3.11' 'Python 3.11'
    }
    if ($ok) {
        # Python-Pfad direkt einbinden
        $pyPaths = @(
            "$env:LOCALAPPDATA\Programs\Python\Python312",
            "$env:LOCALAPPDATA\Programs\Python\Python311",
            "$env:ProgramFiles\Python312",
            "$env:ProgramFiles\Python311"
        )
        foreach ($p in $pyPaths) {
            if (Test-Path "$p\python.exe") {
                $env:PATH = "$p;$p\Scripts;$env:PATH"
                break
            }
        }
        $PYTHON = Get-Python
        if ($PYTHON) {
            Write-Ok "Python installiert: $PYTHON"
        } else {
            Write-Err "Python nicht gefunden nach Installation — Terminal neu starten und erneut versuchen"
            exit 1
        }
    } else {
        Write-Err "Python konnte nicht installiert werden. Bitte manuell von python.org"
        exit 1
    }
}

# ── Schritt 5: Repository klonen / aktualisieren ──────────────────────────────

Write-Step "5/8  Nexoryx-Repository"
$repoParent = Split-Path $REPO_DIR -Parent
if (-not (Test-Path $repoParent)) { New-Item -ItemType Directory -Path $repoParent -Force | Out-Null }

if (Test-Path "$REPO_DIR\.git") {
    Write-Host "  Aktualisiere Repository ..."
    try {
        git -C $REPO_DIR pull --ff-only -q
        Write-Ok "Repository aktualisiert: $REPO_DIR"
    } catch {
        Write-Warn "git pull fehlgeschlagen — bestehende Version wird genutzt"
    }
} else {
    Write-Host "  Klone Repository ..."
    git clone --depth 1 -q $REPO_URL $REPO_DIR
    Write-Ok "Repository geklont: $REPO_DIR"
}

# ── Schritt 6: Python-venv + Pakete ───────────────────────────────────────────

Write-Step "6/8  Python-Umgebung (venv) + Pakete"

$VPYTHON = "$VENV_DIR\Scripts\python.exe"
$VPIP    = "$VENV_DIR\Scripts\pip.exe"

if (-not (Test-Path $VPYTHON)) {
    Write-Host "  Erstelle venv ..." -NoNewline
    & $PYTHON -m venv $VENV_DIR
    Write-Host " OK" -ForegroundColor Green
} else {
    Write-Ok "venv vorhanden: $VENV_DIR"
}

# pip aktualisieren
Write-Host "  Aktualisiere pip ..." -NoNewline
& $VPIP install -q --upgrade pip 2>$null
Write-Host " OK" -ForegroundColor Green

# Nexoryx + alle Extras installieren
Write-Host "  Installiere Nexoryx + Abhaengigkeiten ..."
$pkgSpec = "$REPO_DIR[runtime,cloud,telegram]"
try {
    & $VPIP install -q -e $pkgSpec
    Write-Ok "Nexoryx-Paket installiert"
} catch {
    Write-Warn "Paket-Installation teilweise fehlgeschlagen: $_"
}

# Einzelne Extras separat installieren falls noetig
$extras = @(
    "anthropic>=0.40",
    "openai>=1.40",
    "google-genai>=0.3",
    "python-telegram-bot>=21",
    "fastapi>=0.110",
    "uvicorn>=0.29",
    "pydantic>=2.6",
    "httpx>=0.27",
    "typer>=0.12",
    "rich>=13",
    "pytest>=8"
)
Write-Host "  Stelle sicher dass alle Pakete vorhanden sind ..." -NoNewline
& $VPIP install -q @extras 2>$null
Write-Host " OK" -ForegroundColor Green

# PATH: venv\Scripts registrieren
Add-ToUserPath "$VENV_DIR\Scripts"

# ── Schritt 7: Ollama ────────────────────────────────────────────────────────

Write-Step "7/8  Ollama (lokale Inferenz-Engine)"
if (Test-Command 'ollama') {
    Write-Ok "Ollama bereits installiert"
} else {
    $ok = Install-WingetPkg 'Ollama.Ollama' 'Ollama'
    if ($ok) {
        # Ollama-Pfad einbinden
        $ollamaPaths = @(
            "$env:LOCALAPPDATA\Programs\Ollama",
            "$env:ProgramFiles\Ollama"
        )
        foreach ($p in $ollamaPaths) {
            if (Test-Path "$p\ollama.exe") {
                $env:PATH = "$p;$env:PATH"
                Add-ToUserPath $p
                break
            }
        }
        Write-Ok "Ollama installiert"
    } else {
        Write-Warn "Ollama konnte nicht installiert werden — bitte manuell von ollama.com"
    }
}

# Passendes Start-Modell ziehen (hardware-basiert, im Hintergrund)
if (Test-Command 'ollama') {
    Write-Host "  Starte Ollama-Dienst ..." -NoNewline
    try {
        $proc = Get-Process 'ollama' -ErrorAction SilentlyContinue
        if (-not $proc) {
            Start-Process 'ollama' -ArgumentList 'serve' -WindowStyle Hidden
            Start-Sleep -Seconds 2
        }
        Write-Host " OK" -ForegroundColor Green
    } catch { Write-Host "" }

    # RAM ermitteln und passendes Modell waehlen
    $ramGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 0)
    $model = if ($ramGB -ge 8) { "qwen2.5:7b" } else { "qwen2.5:0.5b" }
    Write-Host "  Lade Modell $model (RAM: ${ramGB} GB) im Hintergrund ..."
    Start-Process 'ollama' -ArgumentList "pull $model" -WindowStyle Hidden
    Write-Ok "Modell $model wird heruntergeladen (laeuft im Hintergrund)"
}

# ── Schritt 8: Nexoryx konfigurieren ─────────────────────────────────────────

Write-Step "8/8  Nexoryx konfigurieren (API-Keys, Telegram, ...)"

New-Item -ItemType Directory -Path $LOG_DIR -Force | Out-Null

try {
    & $VPYTHON "$REPO_DIR\bootstrap.py" `
        --role=admin `
        "--admin-enable=$ADMIN_ENABLE_TOKEN" `
        --source=server
} catch {
    Write-Warn "bootstrap.py Fehler: $_ — Konfiguration kann spaeter nachgeholt werden mit: nexoryx admin"
}

# ── Windows Defender Hinweis ─────────────────────────────────────────────────

Write-Host ""
Write-Host "  INFO: Windows Defender ist aktiv und wird von Nexoryx" -ForegroundColor DarkCyan
Write-Host "  beim Start automatisch fuer den Hintergrund-Scan genutzt." -ForegroundColor DarkCyan

# ── Fertig ────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  ══════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host "    Nexoryx erfolgreich installiert!" -ForegroundColor Green
Write-Host "  ══════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
Write-Host "  Loslegen:" -ForegroundColor White
Write-Host "    nexoryx doctor          Hardware + Profil pruefen" -ForegroundColor Cyan
Write-Host "    nexoryx ask `"Hallo`"      Erste Frage stellen" -ForegroundColor Cyan
Write-Host "    nex                     TUI starten" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Terminal neu starten (oder 'refreshenv') damit PATH-Aenderungen greifen." -ForegroundColor DarkYellow
Write-Host ""
