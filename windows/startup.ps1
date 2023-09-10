Remove-LocalGroupMember -Group "Administrators" -Member hacker
(Get-Service WinFsp.Launcher).WaitForStatus('Running')
& "C:\Program Files (x86)\WinFsp\bin\fsreg.bat" virtiofs "D:\virtio-win\viofs\2k22\amd64\virtiofs.exe" "-t %1 -m %2"
& "C:\Program Files (x86)\WinFsp\bin\launchctl-x64.exe" start virtiofs viofsY challenge Y:
& "C:\Program Files (x86)\WinFsp\bin\launchctl-x64.exe" start virtiofs viofsZ home Z:

$null > C:\flag

# crash course in the footguns of NTFS's ACL based permissions system that I learned
#  the hard way:
# - a "Deny" rule will always take precedence over an "Allow" rule.
#   For example: Admins Allow Read + Users Deny Read 
#   This will result in no one being able to read the flag because they all fall under
#    the "Users" rule.
# - ACLs inherit from the parent directory by default unless explicitly disabled.
#   Combined with the previous rule, this means that if an "Allow" rule is inherited
#    from the parent directory, there is no way to counteract it with a "Deny" rule.
#   You have to disable inheritance instead.

$flagAcl = New-Object System.Security.AccessControl.FileSecurity
# important: do not inherit from the parent directory.
$flagAcl.SetAccessRuleProtection($true, $false)
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
  "Administrators",
  "FullControl",
  "Allow"
)
$flagAcl.AddAccessRule($rule)
Set-Acl -Path C:\flag -AclObject $flagAcl
Set-Content -Path C:\flag -Value (Get-Content Y:\flag)
Remove-Item -Path Y:\flag -Force

if (Test-Path Y:\practice-mode-enabled) {
  Add-LocalGroupMember -Group "Administrators" -Member hacker
}

Start-Service sshd
Start-Service tvnserver
