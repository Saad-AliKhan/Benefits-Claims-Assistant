# Downloads the free, open AI models into this project's models\ folder (one time, from the official
# Hugging Face pages). Run in PowerShell from the project folder:
#     powershell -ExecutionPolicy Bypass -File tools\fetch_models.ps1
# models\meaning   : paraphrase-multilingual-MiniLM-L12-v2 (ONNX, int8, ~120 MB) - understands Urdu by meaning
# models\whisper-small, models\whisper-turbo : Whisper speech recognition (~0.5 GB and ~1.6 GB)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # the progress bar makes downloads very slow in PowerShell 5
Set-Location (Split-Path -Parent $PSScriptRoot)
$HF = "https://huggingface.co"

function Get-Files($repo, $dest, $files) {
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    foreach ($f in $files) {
        $name = Split-Path $f -Leaf
        $out = Join-Path $dest $name
        if (Test-Path $out) { Write-Host "  have $dest\$name"; continue }
        Write-Host "  downloading $repo/$f ..."
        try { Invoke-WebRequest -Uri "$HF/$repo/resolve/main/$f" -OutFile $out -UseBasicParsing }
        catch { Write-Host "    (not available: $f)"; if (Test-Path $out) { Remove-Item $out } }
    }
}

Write-Host "1/3 meaning model (Urdu by meaning)"
Get-Files "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2" "models\meaning" @(
    "onnx/model_quint8_avx2.onnx", "tokenizer.json", "config.json")
Write-Host "2/3 Whisper small (what the app uses now)"
Get-Files "Systran/faster-whisper-small" "models\whisper-small" @(
    "model.bin", "config.json", "tokenizer.json", "vocabulary.txt", "vocabulary.json", "preprocessor_config.json")
Write-Host "3/3 Whisper large-v3-turbo (better Urdu, slower)"
Get-Files "mobiuslabsgmbh/faster-whisper-large-v3-turbo" "models\whisper-turbo" @(
    "model.bin", "config.json", "tokenizer.json", "vocabulary.json", "vocabulary.txt", "preprocessor_config.json")
Write-Host "Done. Files are in $(Get-Location)\models"
