# Signs one file with Azure Artifact Signing. Inno Setup calls it through
# its SignTool directive for Setup.exe and the uninstaller (release.yml
# passes /DSIGN and /Sazure=... to ISCC), so it runs only in a release
# build where azure/login has already signed in.
#
# Reads the same repository variables as release.yml, passed in as
# environment variables: AZURE_SIGNING_ENDPOINT, AZURE_SIGNING_ACCOUNT,
# AZURE_SIGNING_PROFILE.
#
# Inno hands over temporary files whose names do not end in .exe (the
# uninstaller is signed as a .tmp file), so the file is copied into an
# empty folder as an .exe, signed there by folder and filter, and copied
# back.
param([Parameter(Mandatory = $true)][string]$File)

$ErrorActionPreference = "Stop"

if (-not (Get-Module -ListAvailable -Name ArtifactSigning)) {
    Install-Module -Name ArtifactSigning -Scope CurrentUser -Force -AllowClobber
}

$work = Join-Path ([System.IO.Path]::GetTempPath()) ("sc-sign-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $work | Out-Null
try {
    $copy = Join-Path $work "file.exe"
    Copy-Item -LiteralPath $File -Destination $copy
    $params = @{
        Endpoint               = $env:AZURE_SIGNING_ENDPOINT
        CodeSigningAccountName = $env:AZURE_SIGNING_ACCOUNT
        CertificateProfileName = $env:AZURE_SIGNING_PROFILE
        FilesFolder            = $work
        FilesFolderFilter      = "exe"
        FileDigest             = "SHA256"
        TimestampRfc3161       = "http://timestamp.acs.microsoft.com"
        TimestampDigest        = "SHA256"
    }
    Invoke-ArtifactSigning @params
    Copy-Item -LiteralPath $copy -Destination $File -Force
}
finally {
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
