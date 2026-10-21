# Downloads, once, the two small models that read pictures and sentences, into models\phone: this
# computer reads its pictures with them (app/embedder.py), and a paired phone takes them from here,
# over the home network, to do the same by itself.
#   - what sentences say, in Italian and many other languages: sentence-transformers/clip-ViT-B-32-multilingual-v1
#     (Hugging Face, licence Apache 2.0), its version made small for phones, about 138 MB
#   - what pictures show: CLIP ViT-B/32 (OpenAI, licence MIT), as Xenova/clip-vit-base-patch32 made it small, about 89 MB
# Each file must be exactly the one this app was measured with: its SHA-256 is written below, and a
# file that does not match it is not kept.
$target = Join-Path (Split-Path $PSScriptRoot -Parent) 'models\phone'
$text = 'https://huggingface.co/sentence-transformers/clip-ViT-B-32-multilingual-v1/resolve/main'
$vision = 'https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main'
$files = @(
    @{ Name = 'text.onnx'; Url = "$text/onnx/model_qint8_arm64.onnx"; Sha = '3bed77e83926519660b5c0833cb3321cfde952331edec4f7d501c7d384b8a8a7' },
    @{ Name = 'dense.safetensors'; Url = "$text/2_Dense/model.safetensors"; Sha = 'd12568dc7300970a4d3dbb49068ad16cd89b99840b74b026f8e48071e9414f74' },
    @{ Name = 'vocab.txt'; Url = "$text/vocab.txt"; Sha = 'fe0fda7c425b48c516fc8f160d594c8022a0808447475c1a7c6d6479763f310c' },
    @{ Name = 'vision.onnx'; Url = "$vision/onnx/vision_model_quantized.onnx"; Sha = '583fd1110a514667812fee7d684952aaf82a99b959760c8d7dca7e0ab9839299' }
)

New-Item -ItemType Directory -Force $target | Out-Null
$ProgressPreference = 'SilentlyContinue'
foreach ($file in $files) {
    $path = Join-Path $target $file.Name
    if ((Test-Path $path) -and (Get-FileHash $path -Algorithm SHA256).Hash -eq $file.Sha) {
        Write-Host "$($file.Name): c'è già"
        continue
    }
    Write-Host "$($file.Name): lo scarico…"
    $partial = "$path.part"
    Invoke-WebRequest -Uri $file.Url -OutFile $partial -UseBasicParsing
    if ((Get-FileHash $partial -Algorithm SHA256).Hash -ne $file.Sha) {
        Remove-Item -LiteralPath $partial -Force
        Write-Host "FAILED: $($file.Name) non è il file atteso: non lo tengo." -ForegroundColor Red
        exit 1
    }
    Move-Item -LiteralPath $partial -Destination $path -Force
}
Write-Host 'I modelli che leggono le foto sono pronti: li usa questo computer, e un telefono collegato li prende da qui.' -ForegroundColor Green
