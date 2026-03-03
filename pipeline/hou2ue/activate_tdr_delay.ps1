# Full GPU driver disable + enable cycle to activate TdrDelay=60 from registry
# WARNING: Screen will go black for 3-10 seconds while GPU reloads
# Must be run as Administrator

$gpu1 = "PCI\VEN_10DE&DEV_2684&SUBSYS_40BF1458&REV_A1\4&1babdf5b&0&0009"
$gpu2 = "PCI\VEN_10DE&DEV_2684&SUBSYS_40BF1458&REV_A1\6&9197ff2&0&00000011"

Write-Host "[1/4] Disabling GPU 1..."
pnputil /disable-device "$gpu1"
Write-Host "GPU1 disable exit: $LASTEXITCODE"

Write-Host "[2/4] Disabling GPU 2..."
pnputil /disable-device "$gpu2"
Write-Host "GPU2 disable exit: $LASTEXITCODE"

Write-Host "[3/4] Waiting 3 seconds for driver unload..."
Start-Sleep -Seconds 3

Write-Host "[4/4] Re-enabling GPU 1..."
pnputil /enable-device "$gpu1"
Write-Host "GPU1 enable exit: $LASTEXITCODE"

Write-Host "[5/4] Re-enabling GPU 2..."
pnputil /enable-device "$gpu2"
Write-Host "GPU2 enable exit: $LASTEXITCODE"

Write-Host "GPU driver full restart complete. TdrDelay=60 should now be active."
Write-Host "Verify: reg query HKLM\SYSTEM\CurrentControlSet\Control\GraphicsDrivers /v TdrDelay"
