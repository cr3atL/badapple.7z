param(
    [ValidateSet('full','demo','comparison','count-paced','count-fast','all')][string]$Preset='full',
    [switch]$Offline,
    [switch]$VerifyOnly
)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol=[Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$projectDirectory=Split-Path -Parent $PSScriptRoot
$manifest=Get-Content -LiteralPath (Join-Path $projectDirectory 'asset-manifest.json') -Raw -Encoding UTF8|ConvertFrom-Json
$samples=Join-Path $projectDirectory 'samples'
$downloads=Join-Path $projectDirectory 'downloads'
New-Item -ItemType Directory -Force -Path $samples,$downloads|Out-Null
function Confirm-File($Path,$Hash,$Bytes) {
    if (-not (Test-Path -LiteralPath $Path) -or (Get-Item -LiteralPath $Path).Length -ne $Bytes) {return $false}
    $algorithm=[Security.Cryptography.SHA256]::Create()
    $stream=[IO.File]::OpenRead($Path)
    try {$actual=[BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}
    finally {$stream.Dispose();$algorithm.Dispose()}
    return $actual -eq $Hash
}
$wanted=@($Preset)
if ($Preset -eq 'comparison') {$wanted=@('count-paced','count-fast')}
if ($Preset -eq 'all') {$wanted=@('full','demo','count-paced','count-fast')}
foreach ($key in $wanted) {
    $archive=$manifest.archives.$key
    $target=Join-Path $samples $archive.filename
    if (Confirm-File $target $archive.sha256 $archive.bytes) {Write-Host "Verified: $($archive.filename)";continue}
    if ($VerifyOnly) {throw "Missing or invalid archive: $target"}
    $partPaths=@()
    foreach ($part in $archive.assets) {
        $partPath=Join-Path $downloads $part.filename
        if (-not (Confirm-File $partPath $part.sha256 $part.bytes)) {
            if ($Offline) {throw "Missing or invalid offline release file: $partPath"}
            $temporary=$partPath+'.downloading'
            Write-Host "Downloading $($part.filename) ..."
            Invoke-WebRequest -UseBasicParsing -Uri ($manifest.release_base_url+'/'+$part.filename) -OutFile $temporary
            if (-not (Confirm-File $temporary $part.sha256 $part.bytes)) {throw "Download checksum failed: $($part.filename)"}
            Move-Item -LiteralPath $temporary -Destination $partPath -Force
        }
        $partPaths+=,$partPath
    }
    $partial=$target+'.partial'
    Write-Host "Assembling $($archive.filename) ..."
    $output=[IO.File]::Open($partial,[IO.FileMode]::Create,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try {
        foreach ($partPath in $partPaths) {
            $inputStream=[IO.File]::OpenRead($partPath)
            try {$inputStream.CopyTo($output,1048576)} finally {$inputStream.Dispose()}
        }
    } finally {$output.Dispose()}
    if (-not (Confirm-File $partial $archive.sha256 $archive.bytes)) {throw "Assembled archive checksum failed: $($archive.filename)"}
    Move-Item -LiteralPath $partial -Destination $target -Force
    Write-Host "Ready: $target"
}
