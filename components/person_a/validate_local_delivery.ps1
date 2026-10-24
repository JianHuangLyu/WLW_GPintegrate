param(
    [string]$Image = 'wlw/person-a:0.9.0-local-models',
    [switch]$SkipBuild,
    [switch]$PrepareModels
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$referenceRoot = (Resolve-Path (Join-Path $repoRoot '../reference')).Path
$runRoot = (Resolve-Path (Join-Path $repoRoot '../run')).Path
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$validationRoot = Join-Path $runRoot "output/person_a-local-delivery-$stamp"
New-Item -ItemType Directory -Path $validationRoot | Out-Null
$utf8 = New-Object System.Text.UTF8Encoding($false)
$results = [ordered]@{ status = 'running'; image = $Image; started = (Get-Date).ToString('o'); steps = @() }
$results.repo_head = (& git -C $repoRoot rev-parse HEAD | Out-String).Trim()
$results.prepare_models = [bool]$PrepareModels

function Invoke-DockerCheck {
    param([string]$Name, [string[]]$DockerArgs)
    Write-Host "Running $Name"
    $priorPreference = $ErrorActionPreference
    try {
        # Windows PowerShell 5 wraps native stderr progress as ErrorRecords.
        # Judge the process exit code while retaining both streams in the log.
        $ErrorActionPreference = 'Continue'
        & docker @DockerArgs 2>&1 | Tee-Object -FilePath (Join-Path $validationRoot "$Name.log")
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $priorPreference }
    if ($code -ne 0) { throw "$Name failed with exit code $code" }
    $script:results.steps += $Name
}

try {
    Invoke-DockerCheck -Name 'engine' -DockerArgs @('version')
    if (-not $SkipBuild) {
        Invoke-DockerCheck -Name 'clean-build' -DockerArgs @('build', '--no-cache', '--progress', 'plain', '-f', (Join-Path $PSScriptRoot 'Dockerfile'), '-t', $Image, $repoRoot)
    }
    Invoke-DockerCheck -Name 'image-identity' -DockerArgs @('image', 'inspect', '--format', '{{.Id}}', $Image)

    # Unit tests get an isolated writable copy of only the six small assets.
    # Production inference below mounts the real reference tree read-only.
    $testReference = Join-Path $validationRoot 'test-reference'
    $smallAssets = @(
        'checkpoint/soft_prompt_stage2_64SP_50epoch_chunk_option_conditions_retrieval_mixed_best.pt',
        'template_ref/DxStructuredCandidates_integrated.json',
        'template_ref/Histologic_Type_mappingTable.json',
        'template_ref/candidateReference.json',
        'template_ref/[typeLevel]visualAttrs_v1.2.1_2603241656.json',
        'template_ref/chunks_with_attribute_condition.json'
    )
    foreach ($asset in $smallAssets) {
        $destination = Join-Path $testReference "person_a/$asset"
        New-Item -ItemType Directory -Path (Split-Path $destination) -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $referenceRoot "person_a/$asset") -Destination $destination
    }
    $testMounts = @('--rm', '--network', 'none', '-v', "${repoRoot}:/app:ro", '-v', "${testReference}:/reference", '-v', "${validationRoot}:/run", '--entrypoint', 'python', $Image)
    Invoke-DockerCheck -Name 'root-tests' -DockerArgs (@('run') + $testMounts + @('-m', 'unittest', 'discover', '-s', 'tests', '-v'))
    Invoke-DockerCheck -Name 'canonical-cli-tests' -DockerArgs (@('run') + $testMounts + @('-m', 'unittest', 'discover', '-s', 'components/person_a/tests', '-v'))

    if ($PrepareModels) {
        # Only explicit preparation has network, credentials and a writable
        # reference mount. The two inference processes below receive none.
        $envFile = Join-Path $repoRoot 'integration/.env'
        if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) { throw "Preparation requires an existing authorized HF_TOKEN in $envFile" }
        $preparationMounts = @('run', '--rm', '--env-file', $envFile, '-v', "${referenceRoot}:/reference", '-v', "${validationRoot}:/run", '--entrypoint', 'python', $Image)
        foreach ($asset in @('gemma-query-generator', 'medgemma-report-extractor')) {
            Invoke-DockerCheck -Name "prepare-$asset" -DockerArgs ($preparationMounts + @('-m', 'components.person_a.prepare_local_models', '--asset', $asset))
        }
    }

    $runtimeMounts = @('run', '--rm', '--network', 'none', '--gpus', 'all', '-v', "${referenceRoot}:/reference:ro", '-v', "${validationRoot}:/run", '--entrypoint', 'python', $Image)
    $example = '/app/components/person_a/examples/local_model_delivery'
    Invoke-DockerCheck -Name 'prepare-smoke-f' -DockerArgs ($runtimeMounts + @('-m', 'components.person_a.prepare_delivery_smoke', '--output', '/run/F.reference-smoke.json'))
    Invoke-DockerCheck -Name 'medgemma-real-d' -DockerArgs ($runtimeMounts + @('-m', 'components.person_a.report_decompose', '--input', "$example/case_list.valid.json", '--output', '/run/D.medgemma.json', '--config', '/app/components/person_a/configs/report_decompose.default.json'))
    Invoke-DockerCheck -Name 'gemma-real-g' -DockerArgs ($runtimeMounts + @('-m', 'components.person_a.query_generation', '--input', "$example/D_dx_pairs.valid.json", '--input', '/run/F.reference-smoke.json', '--output', '/run/G.gemma.json', '--config', '/app/components/person_a/configs/query_generation.single_device.json'))

    $check = @'
import json
from pathlib import Path
from contracts.runtime import validate_artifact
from contracts.metadata import dx_items
for filename, contract, key in [('D.medgemma.json','D.DxPairs','medgemma_report_extraction'),('G.gemma.json','G.VisualAttributeQueries','learnable_query_generation')]:
    artifact=json.loads((Path('/run')/filename).read_text())
    validate_artifact(artifact,contract)
    provenance=artifact['payload']['reference_versions'][key]
    integrity=provenance.get('model_integrity',provenance)
    assert integrity['integrity_verified'] is True
    assert integrity['local_files_only'] is True
    assert integrity['model_path'].startswith('/reference/person_a/checkpoint/')
    item=dx_items(artifact['payload'])['Histologic_Type']
    if contract=='D.DxPairs':
        assert item['DxResultCls']=='ADH', 'MedGemma must extract the explicit synthetic diagnosis'
    else:
        assert len(item['visualAttrQueries'])==1
    print(filename, 'schema and model provenance PASS')
'@
    Invoke-DockerCheck -Name 'provenance' -DockerArgs ($runtimeMounts + @('-c', $check))
    $results.status = 'passed'
} catch {
    $results.status = 'failed'
    $results.error = $_.Exception.Message
    throw
} finally {
    $results.finished = (Get-Date).ToString('o')
    [System.IO.File]::WriteAllText((Join-Path $validationRoot 'acceptance-summary.json'), ($results | ConvertTo-Json -Depth 8), $utf8)
    Write-Host "Evidence: $validationRoot"
}
