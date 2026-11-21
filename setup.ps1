# race-engineer-ai setup
# Run:  powershell -ExecutionPolicy Bypass -File .\setup.ps1
#       powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Models
#       powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Models -SkipModel   (llama.cpp only)
#       powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Models -SkipLlama   (model only)

param(
    [switch]$Models,
    [switch]$SkipPiper,
    [switch]$SkipLlama,
    [switch]$SkipModel
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$ProgressPreference = "SilentlyContinue"

function Get-RemoteFile {
    param([string]$Url, [string]$OutFile)
    if (Test-Path $OutFile) {
        $size = (Get-Item $OutFile).Length
        if ($size -gt 0) {
            Write-Host ("  already present: {0} ({1:N0} MB)" -f (Split-Path -Leaf $OutFile), ($size / 1MB))
            return
        }
    }
    Write-Host "  downloading $Url"
    $partial = "$OutFile.part"
    & curl.exe -L --fail --retry 5 --retry-delay 2 -C - -o $partial $Url
    if ($LASTEXITCODE -ne 0) {
        throw "download failed ($LASTEXITCODE): $Url"
    }
    Move-Item -Force $partial $OutFile
}

function Expand-Flatten {
    param([string]$Zip, [string]$Destination)
    if (-not (Test-Path $Zip)) { return }
    Expand-Archive $Zip -DestinationPath $Destination -Force
    Remove-Item $Zip -Force
}

Write-Host "== Python environment ==" -ForegroundColor Cyan
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

if (-not $SkipPiper) {
    Write-Host "== Piper voice ==" -ForegroundColor Cyan
    New-Item -ItemType Directory -Force "models\piper" | Out-Null
    $piperDir = "models\piper"
    if (-not (Test-Path "$piperDir\piper.exe")) {
        $zip = Join-Path $env:TEMP "piper_windows_amd64.zip"
        & curl.exe -L --fail --retry 5 -o $zip "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip"
        if ($LASTEXITCODE -ne 0) { throw "Piper download failed" }
        Expand-Flatten $zip "models"
    }
    $voiceBase = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium"
    $voice = "models\piper\en_GB-alan-medium.onnx"
    if (-not (Test-Path $voice)) {
        Get-RemoteFile "$voiceBase.onnx" $voice
        Get-RemoteFile "$voiceBase.onnx.json" "$voice.json"
    }
}

if ($Models -and -not $SkipLlama) {
    Write-Host "== llama.cpp (Windows CUDA build) ==" -ForegroundColor Cyan
    New-Item -ItemType Directory -Force "models\llama" | Out-Null

    if (-not (Test-Path "models\llama\llama-server.exe")) {
        # The "latest" release of llama.cpp can point at a tag with no binaries
        # (v1.0.0 only ships nightly-tag.txt), so scan recent releases for the
        # newest one that actually has a Windows CUDA asset.
        $assetPattern = '^llama-b\d+-bin-win-cuda-12\.4-x64\.zip$'
        $cudartPattern = '^cudart-llama-bin-win-cuda-12\.4-x64\.zip$'
        $release = $null
        try {
            $all = Invoke-RestMethod -Uri "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=30" `
                -Headers @{ "User-Agent" = "race-engineer-ai" }
            $release = $all | Where-Object {
                ($_.assets.name -match $assetPattern).Count -gt 0
            } | Select-Object -First 1
        } catch {
            Write-Warning "GitHub API lookup failed: $($_.Exception.Message)"
        }

        if (-not $release) {
            Write-Warning "No CUDA asset found; falling back to the Vulkan build."
            $vulkanPattern = '^llama-b\d+-bin-win-vulkan-x64\.zip$'
            if ($all) {
                $release = $all | Where-Object {
                    ($_.assets.name -match $vulkanPattern).Count -gt 0
                } | Select-Object -First 1
            }
            if (-not $release) { throw "Could not find any Windows llama.cpp build." }
            $asset = $release.assets | Where-Object { $_.name -match $vulkanPattern } | Select-Object -First 1
            $zip = Join-Path $env:TEMP "llama-vulkan.zip"
            Get-RemoteFile $asset.browser_download_url $zip
            Expand-Flatten $zip "models\llama"
        } else {
            $tag = $release.tag_name
            Write-Host "  build: $tag"
            $asset = $release.assets | Where-Object { $_.name -match $assetPattern } | Select-Object -First 1
            $zip = Join-Path $env:TEMP "llama.zip"
            Get-RemoteFile $asset.browser_download_url $zip
            Expand-Flatten $zip "models\llama"

            # CUDA runtime DLLs are shipped separately now.
            $cudart = $release.assets | Where-Object { $_.name -match $cudartPattern } | Select-Object -First 1
            if ($cudart) {
                $czip = Join-Path $env:TEMP "cudart.zip"
                Get-RemoteFile $cudart.browser_download_url $czip
                Expand-Flatten $czip "models\llama"
            } else {
                Write-Warning "CUDA runtime zip not found for $tag; the server may need cuBLAS/cuDNN on PATH."
            }
        }

        # Flatten whatever folder layout the zip used.
        $root = (Resolve-Path "models\llama").Path
        $server = Get-ChildItem "models\llama" -Recurse -Filter "llama-server.exe" -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($server -and $server.DirectoryName -ne $root) {
            Get-ChildItem $server.DirectoryName -Recurse -File |
                Move-Item -Destination $root -Force
        }
        Get-ChildItem "models\llama" -Recurse -Filter "*.dll" -ErrorAction SilentlyContinue |
            Where-Object { $_.DirectoryName -ne $root } |
            Move-Item -Destination $root -Force
    }

    if (-not (Test-Path "models\llama\llama-server.exe")) {
        throw "llama-server.exe not found after extraction."
    }
    Write-Host "  llama-server.exe ready"
}

if ($Models -and -not $SkipModel) {
    Write-Host "== Qwen2.5-7B-Instruct Q4_K_M (about 5 GB) ==" -ForegroundColor Cyan
    New-Item -ItemType Directory -Force "models\llm" | Out-Null
    $base = "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main"
    # The GGUF is published as two split parts; llama.cpp joins them automatically.
    $parts = @(
        "qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf",
        "qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf"
    )
    foreach ($part in $parts) {
        Get-RemoteFile "$base/$part" "models\llm\$part"
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
