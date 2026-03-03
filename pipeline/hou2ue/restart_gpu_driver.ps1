# Restart NVIDIA GPU drivers to activate TdrDelay=60
# Must be run as Administrator
$gpu1 = "PCI\VEN_10DE&DEV_2684&SUBSYS_40BF1458&REV_A1\4&1babdf5b&0&0009"
$gpu2 = "PCI\VEN_10DE&DEV_2684&SUBSYS_40BF1458&REV_A1\6&9197ff2&0&00000011"

Write-Host "Restarting GPU 1..."
pnputil /restart-device "$gpu1"
Write-Host "GPU1 exit: $LASTEXITCODE"

Write-Host "Restarting GPU 2..."
pnputil /restart-device "$gpu2"
Write-Host "GPU2 exit: $LASTEXITCODE"

Write-Host "Done. TdrDelay=60 should now be active."
