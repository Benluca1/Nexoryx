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

# Kein StrictMode Stop — viele externe Tools geben nicht-null Exit-Codes
$ErrorActionPreference = 'Continue'

$ADMIN_ENABLE_TOKEN = "bYRQCHmrBRvFcNmWlkvMwMnfgSs1gY81fegkokL_IeI"
$REPO_URL  = if ($env:NEXORYX_REPO) { $env:NEXORYX_REPO } else { "https://github.com/Benluca1/Nexoryx.git" }
$REPO_DIR  = if ($env:NEXORYX_DIR)  { $env:NEXORYX_DIR  } else { "$env:USERPROFILE\.nexoryx\src-repo" }
$VENV_DIR  = "$env:USERPROFILE\.nexoryx\venv"

# ── Farb-Hilfsfunktionen ──────────────────────────────────────────────────────
function Write-Ok   { param($msg) Write-Host "  [OK] $msg" -ForegroundColor Green  }
function Write-Warn { param($msg) Write-Host "  [!]  $msg" -ForegroundColor Yellow }
function Write-Err  { param($msg) Write-Host "  [X]  $msg" -ForegroundColor Red    }
function Write-Step { param($msg) Write-Host "`n>> $msg"   -ForegroundColor Cyan   }

# ── Banner ────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ==============================================================" -ForegroundColor Cyan
Write-Host "    N  E  X  O  R  Y  X   Installer  (Windows / Admin)" -ForegroundColor Cyan
Write-Host "  ==============================================================" -ForegroundColor Cyan
Write-Host ""

# ── Hilfsfunktionen ───────────────────────────────────────────────────────────
function Test-Cmd { param($name) return [bool](Get-Command $name -ErrorAction SilentlyContinue) }

function Install-WingetPkg {
    param([string]$id, [string]$label)
    Write-Host "  Installiere $label ..." -NoNewline
    try {
        winget install --id $id --silent --accept-package-agreements --accept-source-agreements 2>&1 | Out-Null
        $code = $LASTEXITCODE
        # -1978335135 = APPINSTALLER_ERROR_ALREADY_INSTALLED (kein Fehler)
        if ($code -eq 0 -or $code -eq -1978335135) {
            Write-Host " OK" -ForegroundColor Green
            return $true
        } else {
            Write-Host " Fehler (Code $code)" -ForegroundColor Yellow
            return $false
        }
    } catch {
        Write-Host " Ausnahme: $_" -ForegroundColor Yellow
        return $false
    }
}

function Add-ToUserPath {
    param([string]$dir)
    $current = [System.Environment]::GetEnvironmentVariable('PATH', 'User')
    if ($null -eq $current) { $current = '' }
    if ($current -notlike "*$dir*") {
        [System.Environment]::SetEnvironmentVariable('PATH', "$dir;$current", 'User')
        $env:PATH = "$dir;$env:PATH"
        Write-Ok "PATH aktualisiert: $dir"
    }
}

function Find-Python {
    # py-Launcher (Windows-spezifisch, bevorzugt)
    if (Test-Cmd 'py') {
        foreach ($v in @('3.12', '3.11')) {
            try {
                $p = & py "-$v" -c "import sys; print(sys.executable)" 2>$null
                if ($p -and (Test-Path $p.Trim())) { return $p.Trim() }
            } catch {}
        }
    }
    # Standard-Kandidaten
    foreach ($cand in @('python3.12', 'python3.11', 'python3', 'python')) {
        if (Test-Cmd $cand) {
            try {
                $check = & $cand -c "import sys; print(sys.version_info >= (3,11), sys.executable)" 2>$null
                if ($check -and $check.StartsWith('True')) {
                    return ($check -split ' ', 2)[1].Trim()
                }
            } catch {}
        }
    }
    # Bekannte Installationspfade durchsuchen
    foreach ($p in @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:ProgramFiles\Python312\python.exe",
        "$env:ProgramFiles\Python311\python.exe"
    )) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

# ── Schritt 1: Execution Policy ───────────────────────────────────────────────
Write-Step "1/8  Execution Policy"
try {
    $policy = Get-ExecutionPolicy -Scope CurrentUser
    if ($policy -eq 'Restricted' -or $policy -eq 'Undefined') {
        Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned -Force
        Write-Ok "ExecutionPolicy auf RemoteSigned gesetzt"
    } else {
        Write-Ok "ExecutionPolicy: $policy"
    }
} catch {
    Write-Warn "ExecutionPolicy konnte nicht gesetzt werden: $_"
}

# ── Schritt 2: winget ─────────────────────────────────────────────────────────
Write-Step "2/8  winget (Windows-Paketmanager)"
if (-not (Test-Cmd 'winget')) {
    Write-Host "  winget nicht gefunden — Installation ueber Microsoft Store ..."
    try {
        $tmp = "$env:TEMP\AppInstaller.msixbundle"
        Write-Host "  Download App Installer ..." -NoNewline
        Invoke-WebRequest -Uri "https://aka.ms/getwinget" -OutFile $tmp -UseBasicParsing
        Write-Host " OK" -ForegroundColor Green
        Add-AppxPackage -Path $tmp -ForceApplicationShutdown
        # PATH neu laden
        $env:PATH = [System.Environment]::GetEnvironmentVariable('PATH', 'Machine') + ';' +
                    [System.Environment]::GetEnvironmentVariable('PATH', 'User')
        Write-Ok "winget installiert"
    } catch {
        Write-Err "winget konnte nicht installiert werden: $_"
        Write-Warn "Bitte manuell: Microsoft Store → 'App Installer' installieren, dann neu starten."
        exit 1
    }
} else {
    Write-Ok "winget $(winget --version 2>$null)"
}

# ── Schritt 3: Git ────────────────────────────────────────────────────────────
Write-Step "3/8  Git"
if (Test-Cmd 'git') {
    Write-Ok "$(git --version)"
} else {
    $ok = Install-WingetPkg 'Git.Git' 'Git'
    if ($ok) {
        # Git sofort im PATH verfuegbar machen
        foreach ($p in @("$env:ProgramFiles\Git\cmd", "$env:ProgramFiles\Git\bin")) {
            if (Test-Path $p) {
                $env:PATH = "$p;$env:PATH"
                Add-ToUserPath $p
            }
        }
        if (Test-Cmd 'git') { Write-Ok "$(git --version)" }
        else { Write-Warn "git: Terminal neu starten, falls Befehl fehlt" }
    } else {
        Write-Err "git konnte nicht installiert werden — bitte manuell von git-scm.com"
        exit 1
    }
}

# ── Schritt 4: Python 3.12 ────────────────────────────────────────────────────
Write-Step "4/8  Python 3.12"
$PYTHON = Find-Python
if ($PYTHON) {
    $ver = (& $PYTHON --version 2>&1).ToString()
    Write-Ok "Python: $ver"
} else {
    Write-Host "  Python 3.11+ nicht gefunden — installiere Python 3.12 ..."
    $ok = Install-WingetPkg 'Python.Python.3.12' 'Python 3.12'
    if (-not $ok) {
        Write-Warn "Python 3.12 fehlgeschlagen — versuche 3.11 ..."
        $ok = Install-WingetPkg 'Python.Python.3.11' 'Python 3.11'
    }
    if ($ok) {
        # Pfade direkt in diese Session bringen
        foreach ($p in @(
            "$env:LOCALAPPDATA\Programs\Python\Python312",
            "$env:LOCALAPPDATA\Programs\Python\Python311"
        )) {
            if (Test-Path "$p\python.exe") {
                $env:PATH = "$p;$p\Scripts;$env:PATH"
                Add-ToUserPath $p
                Add-ToUserPath "$p\Scripts"
            }
        }
        $PYTHON = Find-Python
        if ($PYTHON) {
            Write-Ok "Python gefunden: $PYTHON"
        } else {
            Write-Err "Python nicht im PATH — Terminal neu starten und Installer erneut ausfuehren."
            exit 1
        }
    } else {
        Write-Err "Python konnte nicht installiert werden — bitte manuell von python.org"
        exit 1
    }
}

# ── Schritt 5: Repository klonen / aktualisieren ─────────────────────────────
Write-Step "5/8  Nexoryx-Repository"
$repoParent = Split-Path $REPO_DIR -Parent
if (-not (Test-Path $repoParent)) {
    New-Item -ItemType Directory -Path $repoParent -Force | Out-Null
}

if (Test-Path "$REPO_DIR\.git") {
    Write-Host "  Aktualisiere Repository ..."
    try {
        & git -C $REPO_DIR pull --ff-only -q 2>&1 | Out-Null
        Write-Ok "Repository aktualisiert: $REPO_DIR"
    } catch {
        Write-Warn "git pull fehlgeschlagen — bestehende Version wird genutzt"
    }
} else {
    Write-Host "  Klone Repository ..."
    & git clone --depth 1 -q $REPO_URL $REPO_DIR
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "Repository geklont: $REPO_DIR"
    } else {
        Write-Err "git clone fehlgeschlagen"
        exit 1
    }
}

# ── Schritt 6: Python-venv + Pakete ──────────────────────────────────────────
Write-Step "6/8  Python-Umgebung (venv) + Pakete"

$VPYTHON = "$VENV_DIR\Scripts\python.exe"
$VPIP    = "$VENV_DIR\Scripts\pip.exe"

if (-not (Test-Path $VPYTHON)) {
    Write-Host "  Erstelle venv ..." -NoNewline
    & $PYTHON -m venv $VENV_DIR
    if ($LASTEXITCODE -eq 0) { Write-Host " OK" -ForegroundColor Green }
    else { Write-Err "venv-Erstellung fehlgeschlagen"; exit 1 }
} else {
    Write-Ok "venv vorhanden: $VENV_DIR"
}

Write-Host "  Aktualisiere pip ..." -NoNewline
& $VPIP install -q --upgrade pip 2>$null | Out-Null
Write-Host " OK" -ForegroundColor Green

# Nexoryx editable install: cd in Repo-Dir, dann ".[extras]"
# (Verhindert PowerShell-Glob-Expansion von [..])
Write-Host "  Installiere Nexoryx + Abhaengigkeiten ..."
Push-Location $REPO_DIR
try {
    & $VPIP install -q -e ".[runtime,cloud,telegram]" 2>&1 | Out-Null
    Write-Ok "Nexoryx installiert"
} catch {
    Write-Warn "Editable-Install fehlgeschlagen: $_ — versuche direkten Install"
    & $VPIP install -q "$REPO_DIR" 2>&1 | Out-Null
}
Pop-Location

# Alle optionalen Extras einzeln sicherstellen
Write-Host "  Stelle alle optionalen Pakete sicher ..." -NoNewline
$extras = @(
    "anthropic>=0.40", "openai>=1.40", "google-genai>=0.3",
    "python-telegram-bot>=21", "fastapi>=0.110", "uvicorn>=0.29",
    "pydantic>=2.6", "httpx>=0.27", "typer>=0.12", "rich>=13", "pytest>=8"
)
& $VPIP install -q @extras 2>&1 | Out-Null
Write-Host " OK" -ForegroundColor Green

Add-ToUserPath "$VENV_DIR\Scripts"

# ── Schritt 7: Ollama ─────────────────────────────────────────────────────────
Write-Step "7/8  Ollama (lokale Inferenz-Engine)"
if (Test-Cmd 'ollama') {
    $ollamaVer = (ollama --version 2>$null) -replace "`n",""
    Write-Ok "Ollama bereits installiert ($ollamaVer)"
} else {
    $ok = Install-WingetPkg 'Ollama.Ollama' 'Ollama'
    if ($ok) {
        foreach ($p in @(
            "$env:LOCALAPPDATA\Programs\Ollama",
            "$env:ProgramFiles\Ollama"
        )) {
            if (Test-Path "$p\ollama.exe") {
                $env:PATH = "$p;$env:PATH"
                Add-ToUserPath $p
            }
        }
        Write-Ok "Ollama installiert"
    } else {
        Write-Warn "Ollama nicht installiert — bitte manuell von ollama.com"
    }
}

# Ollama starten und Startmodell ziehen
if (Test-Cmd 'ollama') {
    # Dienst starten falls nicht laufend
    $running = $false
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:11434/api/version" -UseBasicParsing -ErrorAction Stop
        $running = ($resp.StatusCode -eq 200)
    } catch {}

    if (-not $running) {
        Write-Host "  Starte Ollama-Dienst ..." -NoNewline
        Start-Process 'ollama' -ArgumentList 'serve' -WindowStyle Hidden
        Start-Sleep -Seconds 3
        # Nochmal pruefen
        try {
            $resp = Invoke-WebRequest -Uri "http://localhost:11434/api/version" -UseBasicParsing -ErrorAction Stop
            $running = ($resp.StatusCode -eq 200)
        } catch {}
        if ($running) { Write-Host " OK" -ForegroundColor Green }
        else { Write-Host " nicht erreichbar" -ForegroundColor Yellow }
    } else {
        Write-Ok "Ollama laeuft bereits"
    }

    # Hardware-passendes Modell
    try {
        $ramGB = [math]::Round((Get-CimInstance -ClassName Win32_ComputerSystem -ErrorAction Stop).TotalPhysicalMemory / 1GB, 0)
    } catch {
        $ramGB = 4
    }
    $model = if ($ramGB -ge 8) { "qwen2.5:7b" } else { "qwen2.5:0.5b" }

    if ($running) {
        Write-Host "  Lade Modell $model (RAM: ${ramGB} GB) im Hintergrund ..."
        # ArgumentList als Array uebergeben (korrekt fuer PS 5.1+)
        Start-Process 'ollama' -ArgumentList @('pull', $model) -WindowStyle Hidden
        Write-Ok "Modell $model wird heruntergeladen"
    } else {
        Write-Warn "Ollama nicht erreichbar — Modell manuell laden: ollama pull $model"
    }
}

# ── Schritt 8: Nexoryx konfigurieren ─────────────────────────────────────────
Write-Step "8/8  Nexoryx konfigurieren (API-Keys, Telegram, ...)"

New-Item -ItemType Directory -Path "$env:USERPROFILE\.nexoryx\logs" -Force | Out-Null

try {
    & $VPYTHON "$REPO_DIR\bootstrap.py" `
        --role=admin `
        "--admin-enable=$ADMIN_ENABLE_TOKEN" `
        --source=server
} catch {
    Write-Warn "bootstrap.py Fehler: $_ — Konfiguration spaeter nachholen: nexoryx admin"
}

# ── Windows Defender Info ─────────────────────────────────────────────────────
Write-Host ""
Write-Host "  [INFO] Windows Defender ist aktiv. Nexoryx nutzt ihn beim Start" -ForegroundColor DarkCyan
Write-Host "  automatisch fuer den Hintergrund-Virenscan (kein ClamAV noetig)." -ForegroundColor DarkCyan

# ── Fertig ────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ==============================================================" -ForegroundColor Green
Write-Host "    Nexoryx erfolgreich installiert!" -ForegroundColor Green
Write-Host "  ==============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Loslegen (nach Terminal-Neustart):" -ForegroundColor White
Write-Host "    nexoryx doctor            Hardware + Profil pruefen" -ForegroundColor Cyan
Write-Host "    nexoryx ask `"Hallo`"        Erste Frage stellen" -ForegroundColor Cyan
Write-Host "    nex                       TUI starten" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Terminal neu starten damit PATH-Aenderungen greifen!" -ForegroundColor Yellow
Write-Host ""
