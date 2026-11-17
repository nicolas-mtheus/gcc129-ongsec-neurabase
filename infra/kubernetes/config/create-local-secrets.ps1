$ErrorActionPreference = "Stop"

if (-not (Get-Command kubectl -ErrorAction SilentlyContinue)) {
    throw "kubectl was not found. Install kubectl and configure the local cluster first."
}

$namespaceResources = @(& kubectl get namespaces -o name)
if ($LASTEXITCODE -ne 0) {
    throw "Failed to list Kubernetes namespaces."
}
if ($namespaceResources -notcontains "namespace/ongsec") {
    throw "Namespace 'ongsec' does not exist. Apply base/namespace.yaml first."
}

$secretResources = @(& kubectl get secrets --namespace ongsec -o name)
if ($LASTEXITCODE -ne 0) {
    throw "Failed to list Secrets in namespace 'ongsec'."
}

$existingSecretNames = @($secretResources | ForEach-Object { "$_".Trim() })

function New-RandomSecretValue {
    $bytes = New-Object byte[] 24
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }

    return [BitConverter]::ToString($bytes).Replace("-", "").ToLowerInvariant()
}

function Apply-LocalSecret {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][hashtable]$Values
    )

    if ($existingSecretNames -contains "secret/$Name") {
        Write-Host "Secret '$Name' already exists. Skipping."
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

    Write-Host "Secret '$Name' created."
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

Write-Host "Local database and application Secrets are ready in namespace 'ongsec'."
