Remove-LocalGroupMember -Group "Administrators" -Member hacker
(Get-Service WinFsp.Launcher).WaitForStatus('Running')
& "C:\Program Files (x86)\WinFsp\bin\fsreg.bat" virtiofs "D:\virtio-win\viofs\2k22\amd64\virtiofs.exe" "-t %1 -m %2"
& "C:\Program Files (x86)\WinFsp\bin\launchctl-x64.exe" start virtiofs viofsY challenge Y:
& "C:\Program Files (x86)\WinFsp\bin\launchctl-x64.exe" start virtiofs viofsZ home Z:

$null > C:\flag
$flagAcl = New-Object System.Security.AccessControl.FileSecurity
$adminsRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
  "Administrators",
  "Read",
  "Allow"
)
$flagAcl.AddAccessRule($adminsRule)
$denyRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
  "Users",
  "Read",
  "Deny"
)
$flagAcl.AddAccessRule($denyRule)
Set-Acl -Path C:\flag -AclObject $flagAcl
Set-Content -Path C:\flag -Value (Get-Content Y:\flag)
Remove-Item -Path Y:\flag -Force

if (Test-Path Y:\practice-mode-enabled) {
  Add-LocalGroupMember -Group "Administrators" -Member hacker
}

Start-Service sshd
Start-Service tvnserver
