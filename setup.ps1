# race-engineer-ai setup
# Run:  powershell -ExecutionPolicy Bypass -File .\setup.ps1
#       powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Models   (also download the 7B model + llama.cpp)

param(
    [switch]$Models,
    [switch]$SkipPiper
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "== Python environment ==" -ForegroundColor Cyan
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

if (-not $SkipPiper) {
    Write-Host "== Piper voice ==" -ForegroundColor Cyan
    New-Item -ItemType Directory -Force "models\piper" | Out-Null
    $zip = Join-Path $env:TEMP "piper_windows_amd64.zip"
    Invoke-WebRequest "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip" -OutFile $zip
    Expand-Archive $zip -DestinationPath "models" -Force
    Remove-Item $zip

    $voiceBase = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium"
    $voice = "models\piper\en_GB-alan-medium.onnx"
    if (-not (Test-Path $voice)) {
        Invoke-WebRequest "$voiceBase.onnx" -OutFile $voice
        Invoke-WebRequest "$voiceBase.onnx.json" -OutFile "$voice.json"
    }
}

if ($Models) {
    Write-Host "== LLM runtime and model (about 5 GB) ==" -ForegroundColor Cyan
    New-Item -ItemType Directory -Force "models\llama", "models\llm" | Out-Null

    if (-not (Test-Path "models\llama\llama-server.exe")) {
        $release = Invoke-RestMethod "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
        $asset = $release.assets |
            Where-Object { $_.name -match "win-cuda.*x64\.zip$" } |
            Select-Object -First 1
        if (-not $asset) {
            $asset = $release.assets |
                Where-Object { $_.name -match "win.*x64\.zip$" } |
                Select-Object -First 1
        }
        if (-not $asset) { throw "No Windows llama.cpp build found in the latest release." }
        Write-Host "Downloading $($asset.name)"
        $zip = Join-Path $env:TEMP "llama.zip"
        Invoke-WebRequest $asset.browser_download_url -OutFile $zip
        Expand-Archive $zip -DestinationPath "models\llama" -Force
        Remove-Item $zip
        $server = Get-ChildItem "models\llama" -Recurse -Filter "llama-server.exe" |
            Select-Object -First 1
        if ($server -and $server.DirectoryName -ne (Resolve-Path "models\llama").Path) {
            Get-ChildItem $server.DirectoryName -Recurse | Move-Item -Destination "models\llama" -Force
        }
    }

    $gguf = "models\llm\qwen2.5-7b-instruct-q4_k_m.gguf"
    if (-not (Test-Path $gguf)) {
        Write-Host "Downloading Qwen2.5-7B-Instruct Q4_K_M (4.7 GB)"
        Invoke-WebRequest "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main/qwen2.5-7b-instruct-q4_k_m.gguf" -OutFile $gguf
    }
}

Write-Host ""
Write-Host "== Next steps ==" -ForegroundColor Cyan
if (-not $env:DEEPSEEK_API_KEY) {
    Write-Host "1. Set your DeepSeek key for the smart brain:"
    Write-Host '   setx DEEPSEEK_API_KEY "sk-..."'
}
Write-Host "2. In F1 24: Settings > Telemetry Settings"
Write-Host "   UDP Telemetry: On | UDP Format: 2024 | IP: 127.0.0.1 | Port: 20777 | Rate: 60Hz"
Write-Host "3. Check everything:  .\run.cmd --check"
Write-Host "4. Start the local model:  .\start-llm.cmd"
Write-Host "5. Run the engineer:  .\run.cmd"
