param(
    [ValidateSet('full','demo','count-paced','count-fast')][string]$Preset='full',
    [string]$SevenZipPath,
    [switch]$ValidateOnly,
    [switch]$SetupOnly,
    [switch]$UseCurrentTerminal,
    [switch]$NoPause,
    [string]$LayoutReport
)
$ErrorActionPreference='Stop'
$projectDirectory=Split-Path -Parent $PSScriptRoot
$settings=@{
    'full'=@{Name='badapple-full-384x288-30fps.zip';Width=384;Height=288;Fonts=@(6,5,4)}
    'demo'=@{Name='badapple-3s-24fps.zip';Width=64;Height=48;Fonts=@(24,20,16,12,8,6)}
    'count-paced'=@{Name='count-to-three-paced.zip';Width=24;Height=20;Fonts=@(32,24,20,16)}
    'count-fast'=@{Name='count-to-three-fast.zip';Width=24;Height=20;Fonts=@(32,24,20,16)}
}
$selected=$settings[$Preset]
$archivePath=Join-Path (Join-Path $projectDirectory 'samples') $selected.Name
$exitCode=0
try {
    if (-not (Test-Path -LiteralPath $archivePath)) {throw "Missing archive. Run: powershell -ExecutionPolicy Bypass -File tools\download-assets.ps1 -Preset $Preset"}
    if (-not $SevenZipPath) {$SevenZipPath=$env:SEVENZIP_BINARY}
    if (-not $SevenZipPath) {
        foreach ($candidate in @((Join-Path $env:ProgramFiles '7-Zip\7z.exe'),'7z.exe','7zz.exe')) {
            $found=Get-Command $candidate -ErrorAction SilentlyContinue
            if ($found) {$SevenZipPath=$found.Source;break}
        }
    }
    if (-not $SevenZipPath -or -not (Test-Path -LiteralPath $SevenZipPath)) {throw 'Install stock 7-Zip, or set SEVENZIP_BINARY to 7z.exe.'}
    if ($ValidateOnly) {
        [pscustomobject]@{Archive=$archivePath;Tool=$SevenZipPath;Columns=$selected.Width;Rows=$selected.Height/2;FrameScheduling=$false}|ConvertTo-Json -Compress
        exit 0
    }
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace NativeBadApple {
    [StructLayout(LayoutKind.Sequential)] public struct Coord {public short X;public short Y;}
    [StructLayout(LayoutKind.Sequential,CharSet=CharSet.Unicode)] public struct FontInfo {
        public uint Size;public uint Index;public Coord Cell;public uint Family;public uint Weight;
        [MarshalAs(UnmanagedType.ByValTStr,SizeConst=32)]public string Face;
    }
    public static class ConsoleApi {
        [DllImport("kernel32.dll")]public static extern IntPtr GetStdHandle(int id);
        [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)]public static extern bool SetCurrentConsoleFontEx(IntPtr h,bool maximum,ref FontInfo f);
        [DllImport("kernel32.dll",CharSet=CharSet.Unicode)]public static extern bool GetCurrentConsoleFontEx(IntPtr h,bool maximum,ref FontInfo f);
        [DllImport("kernel32.dll")]public static extern Coord GetLargestConsoleWindowSize(IntPtr h);
        [DllImport("kernel32.dll")]public static extern bool GetConsoleMode(IntPtr h,out uint mode);
        [DllImport("kernel32.dll")]public static extern bool SetConsoleMode(IntPtr h,uint mode);
        [DllImport("kernel32.dll")]public static extern bool SetConsoleOutputCP(uint page);
    }
}
'@
    [Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
    [NativeBadApple.ConsoleApi]::SetConsoleOutputCP(65001)|Out-Null
    $handle=[NativeBadApple.ConsoleApi]::GetStdHandle(-11)
    $columns=$selected.Width+2;$rows=[int]($selected.Height/2)+4
    $fits=$false;$attempts=@()
    if ($UseCurrentTerminal) {
        if ([Console]::WindowWidth -lt $selected.Width -or [Console]::WindowHeight -lt ($selected.Height/2)) {
            throw ('Zoom out this terminal until it has at least '+$selected.Width+' columns and '+($selected.Height/2)+' rows, then run this command again.')
        }
        $fits=$true
    } else {
    foreach ($size in $selected.Fonts) {
        $font=New-Object NativeBadApple.FontInfo
        $font.Size=[Runtime.InteropServices.Marshal]::SizeOf($font)
        $font.Face='Consolas';$font.Family=54;$font.Weight=400;$font.Cell.Y=$size;$font.Cell.X=[Math]::Max(1,[int]($size/2))
        $fontChanged=[NativeBadApple.ConsoleApi]::SetCurrentConsoleFontEx($handle,$false,[ref]$font)
        if ($fontChanged) {
            $largest=[NativeBadApple.ConsoleApi]::GetLargestConsoleWindowSize($handle)
            $actualFont=New-Object NativeBadApple.FontInfo;$actualFont.Size=[Runtime.InteropServices.Marshal]::SizeOf($actualFont)
            [NativeBadApple.ConsoleApi]::GetCurrentConsoleFontEx($handle,$false,[ref]$actualFont)|Out-Null
            $attempts+=,@{Requested=$size;CellWidth=$actualFont.Cell.X;CellHeight=$actualFont.Cell.Y;MaxColumns=$largest.X;MaxRows=$largest.Y}
            if ($largest.X -ge $columns -and $largest.Y -ge $rows) {$fits=$true;break}
        } else {$attempts+=,@{Requested=$size;Error=[Runtime.InteropServices.Marshal]::GetLastWin32Error()}}
    }
    if (-not $fits) {throw ('The current console cannot fit this archive. In Windows Terminal, zoom out to '+$selected.Width+' columns / '+($selected.Height/2)+' rows, then run: powershell -ExecutionPolicy Bypass -File tools\play.ps1 -Preset '+$Preset+' -UseCurrentTerminal')}
    [Console]::SetWindowSize(40,15)
    [Console]::SetBufferSize($columns,$rows)
    [Console]::SetWindowSize($columns,$rows)
    }
    [uint32]$mode=0
    if (-not [NativeBadApple.ConsoleApi]::GetConsoleMode($handle,[ref]$mode)) {throw 'A native console is required. Use a play-*.cmd launcher.'}
    if (-not [NativeBadApple.ConsoleApi]::SetConsoleMode($handle,$mode -bor 4)) {throw 'Could not enable VT terminal output.'}
    [Console]::Title='Bad Apple / stock 7-Zip'
    if ($LayoutReport) {
        $actual=New-Object NativeBadApple.FontInfo;$actual.Size=[Runtime.InteropServices.Marshal]::SizeOf($actual)
        [NativeBadApple.ConsoleApi]::GetCurrentConsoleFontEx($handle,$false,[ref]$actual)|Out-Null
        [pscustomobject]@{Columns=[Console]::WindowWidth;Rows=[Console]::WindowHeight;CellWidth=$actual.Cell.X;CellHeight=$actual.Cell.Y;Archive=$selected.Name}|ConvertTo-Json|Set-Content -LiteralPath $LayoutReport -Encoding UTF8
    }
    if ($SetupOnly) {exit 0}
    [Console]::Clear()
    Write-Host ('"'+$SevenZipPath+'" x -so -bd -bsp0 "'+$archivePath+'"')
    # Only one native process is started. It inherits the real console handles.
    # There is no stdout pipe, frame reader, timer, sleep, or playback loop here.
    $startInfo=New-Object Diagnostics.ProcessStartInfo
    $startInfo.FileName=$SevenZipPath
    $startInfo.Arguments='x -so -bd -bsp0 "'+$archivePath+'"'
    $startInfo.UseShellExecute=$false
    $startInfo.RedirectStandardOutput=$false
    $startInfo.RedirectStandardError=$false
    $nativeProcess=[Diagnostics.Process]::Start($startInfo)
    $nativeProcess.WaitForExit()
    $exitCode=$nativeProcess.ExitCode
    [Console]::Write(([string][char]27)+"[0m"+([string][char]27)+"[?25h")
    Write-Host "`n7-Zip exit code: $exitCode"
} catch {
    Write-Host $_.Exception.Message;$exitCode=1
    if ($LayoutReport) {@{Error=$_.Exception.Message;FontAttempts=$attempts}|ConvertTo-Json -Depth 5|Set-Content -LiteralPath $LayoutReport -Encoding UTF8}
}
if (-not $NoPause) {Read-Host 'Press Enter to close'|Out-Null}
exit $exitCode
