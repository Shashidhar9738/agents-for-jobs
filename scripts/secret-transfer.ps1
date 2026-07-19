<#
.SYNOPSIS
  Encrypts / decrypts .env so it can travel through a public git repo.

.DESCRIPTION
  .env holds live credentials (AI provider key, credential-vault key, n8n MCP
  token) and must never be committed in plaintext. This wraps it in AES-256
  so only the ciphertext is committed; the passphrase travels separately.

  Format: base64( salt[16] || iv[16] || AES-256-CBC ciphertext )
  Key derivation: PBKDF2-SHA256, 200k iterations.

.EXAMPLE
  # On the source machine
  .\scripts\secret-transfer.ps1 -Encrypt

.EXAMPLE
  # On the target machine, after git pull
  .\scripts\secret-transfer.ps1 -Decrypt
#>
[CmdletBinding(DefaultParameterSetName = 'Encrypt')]
param(
    [Parameter(ParameterSetName = 'Encrypt')][switch]$Encrypt,
    [Parameter(ParameterSetName = 'Decrypt')][switch]$Decrypt,
    [string]$Plain = '.env',
    [string]$Cipher = '.env.enc'
)

$ErrorActionPreference = 'Stop'
$iterations = 200000

# Resolve paths relative to the repo root, not the caller's cwd.
$repoRoot = Split-Path -Parent $PSScriptRoot
$plainPath  = Join-Path $repoRoot $Plain
$cipherPath = Join-Path $repoRoot $Cipher

function Get-Key([securestring]$Secure, [byte[]]$Salt) {
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try   { $pass = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }

    $kdf = New-Object System.Security.Cryptography.Rfc2898DeriveBytes(
        $pass, $Salt, $iterations, [System.Security.Cryptography.HashAlgorithmName]::SHA256)
    try   { return $kdf.GetBytes(32) }
    finally { $kdf.Dispose() }
}

if ($Decrypt) {
    if (-not (Test-Path -LiteralPath $cipherPath)) { throw "Not found: $cipherPath" }
    if (Test-Path -LiteralPath $plainPath) {
        $backup = "$plainPath.bak"
        Copy-Item -LiteralPath $plainPath -Destination $backup -Force
        Write-Host "[INFO] Existing .env backed up to $(Split-Path -Leaf $backup)"
    }

    $blob = [Convert]::FromBase64String((Get-Content -LiteralPath $cipherPath -Raw).Trim())
    $salt = $blob[0..15]; $iv = $blob[16..31]; $body = $blob[32..($blob.Length - 1)]

    $secure = Read-Host -AsSecureString "Passphrase"
    $aes = [System.Security.Cryptography.Aes]::Create()
    try {
        $aes.Key = Get-Key $secure $salt; $aes.IV = $iv
        $dec = $aes.CreateDecryptor()
        try   { $bytes = $dec.TransformFinalBlock($body, 0, $body.Length) }
        catch { throw "Decryption failed - wrong passphrase, or the file is corrupt." }
        finally { $dec.Dispose() }
    } finally { $aes.Dispose() }

    [System.IO.File]::WriteAllBytes($plainPath, $bytes)
    Write-Host "[OK] Wrote $Plain ($($bytes.Length) bytes)." -ForegroundColor Green
    Write-Host "[INFO] .env is gitignored - it stays on this machine."
    return
}

# --- Encrypt (default) ---
if (-not (Test-Path -LiteralPath $plainPath)) { throw "Not found: $plainPath" }

$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$salt = New-Object byte[] 16; $iv = New-Object byte[] 16
$rng.GetBytes($salt); $rng.GetBytes($iv)

$secure  = Read-Host -AsSecureString "Passphrase"
$confirm = Read-Host -AsSecureString "Confirm passphrase"
if ((Get-Key $secure $salt) -join ',' -ne (Get-Key $confirm $salt) -join ',') {
    throw "Passphrases do not match."
}

$plainBytes = [System.IO.File]::ReadAllBytes($plainPath)
$aes = [System.Security.Cryptography.Aes]::Create()
try {
    $aes.Key = Get-Key $secure $salt; $aes.IV = $iv
    $enc = $aes.CreateEncryptor()
    try   { $body = $enc.TransformFinalBlock($plainBytes, 0, $plainBytes.Length) }
    finally { $enc.Dispose() }
} finally { $aes.Dispose() }

$out = New-Object byte[] (32 + $body.Length)
[Array]::Copy($salt, 0, $out, 0,  16)
[Array]::Copy($iv,   0, $out, 16, 16)
[Array]::Copy($body, 0, $out, 32, $body.Length)

[System.IO.File]::WriteAllText($cipherPath, [Convert]::ToBase64String($out))
Write-Host "[OK] Wrote $Cipher - safe to commit." -ForegroundColor Green
