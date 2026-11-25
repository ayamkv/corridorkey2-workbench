# Streaming SHA-256 works in Windows PowerShell 5.1 even when an inherited
# PowerShell 7 PSModulePath hides the Get-FileHash cmdlet.
function Get-WorkbenchSha256([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace('-', '').ToLowerInvariant()
    } finally {
        $algorithm.Dispose()
        $stream.Dispose()
    }
}
