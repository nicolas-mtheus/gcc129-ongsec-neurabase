$ErrorActionPreference = "Stop"

if (-not (Get-Command kubectl -ErrorAction SilentlyContinue)) {
    throw "kubectl was not found. Install kubectl and configure the local cluster first."
}

& kubectl get namespace ongsec *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Namespace 'ongsec' does not exist. Apply base/namespace.yaml first."
}

function New-RandomSecretValue {
    $bytes = New-Object byte[] 24
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }

    return [Convert]::ToBase64String($bytes)
}

function Apply-LocalSecret {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][hashtable]$Values
    )

    & kubectl get secret $Name --namespace ongsec *> $null
    if ($LASTEXITCODE -eq 0) {
        return
    }

    $encodedValues = foreach ($key in $Values.Keys) {
        $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Values[$key]))
        "  ${key}: `"$encoded`""
    }

    $manifest = @"
apiVersion: v1
kind: Secret
metadata:
  name: $Name
  namespace: ongsec
type: Opaque
data:
$($encodedValues -join "`n")
"@

    $manifest | & kubectl apply -f - | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to apply Secret '$Name'."
    }
}

foreach ($service in @("org", "audit", "task", "badge")) {
    $password = New-RandomSecretValue
    Apply-LocalSecret -Name "$service-db-credentials" -Values @{
        POSTGRES_PASSWORD = $password
        DB_PASSWORD       = $password
    }
}

Apply-LocalSecret -Name "ongsec-app-credentials" -Values @{
    JWT_SECRET = New-RandomSecretValue
}

Write-Host "Created local database and application Secrets in namespace 'ongsec'."
