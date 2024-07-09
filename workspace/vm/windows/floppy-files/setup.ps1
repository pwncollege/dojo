# -- fixnetwork --

# You cannot enable Windows PowerShell Remoting on network connections that are set to Public
# Spin through all the network locations and if they are set to Public, set them to Private
# using the INetwork interface:
# http://msdn.microsoft.com/en-us/library/windows/desktop/aa370750(v=vs.85).aspx
# For more info, see:
# http://blogs.msdn.com/b/powershell/archive/2009/04/03/setting-network-location-to-private.aspx

# Network location feature was only introduced in Windows Vista - no need to bother with this
# if the operating system is older than Vista
if([environment]::OSVersion.version.Major -lt 6) { return }

# You cannot change the network location if you are joined to a domain, so abort
if(1,3,4,5 -contains (Get-WmiObject win32_computersystem).DomainRole) { return }

# Get network connections
$networkListManager = [Activator]::CreateInstance([Type]::GetTypeFromCLSID([Guid]"{DCB00C01-570F-4A9B-8D69-199FDBA5723B}"))
$connections = $networkListManager.GetNetworkConnections()

$connections |foreach {
	Write-Host $_.GetNetwork().GetName()"category was previously set to"$_.GetNetwork().GetCategory()
	$_.GetNetwork().SetCategory(1)
	Write-Host $_.GetNetwork().GetName()"changed to category"$_.GetNetwork().GetCategory()
}

# -- setup powershell profile --
if (!(Test-Path -Path $PROFILE)) {
  New-Item -ItemType File -Path $PROFILE -Force
}

# -- disable windows defender --
Uninstall-WindowsFeature -Name Windows-Defender

# -- enable SSH --
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
# Start the sshd service
#Start-Service sshd
# This will be done later when the service actually exists
#Set-Service -Name sshd -StartupType 'Manual'

# set default shell to powershell
New-ItemProperty -Path "HKLM:\SOFTWARE\OpenSSH" -Name DefaultShell -Value "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -PropertyType String -Force

# Confirm the Firewall rule is configured. It should be created automatically by setup.
if (!(Get-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -ErrorAction SilentlyContinue | Select-Object Name, Enabled)) {
    Write-Output "Firewall Rule 'OpenSSH-Server-In-TCP' does not exist, creating it..."
    New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22
} else {
    Write-Output "Firewall rule 'OpenSSH-Server-In-TCP' has been created and exists."
}

# -- virtfs --
(New-Object Net.WebClient).DownloadFile("https://github.com/winfsp/winfsp/releases/download/v2.0/winfsp-2.0.23075.msi", "C:\winfsp.msi")
Start-Process msiexec -ArgumentList "/i C:\winfsp.msi /qn" -Wait
Remove-Item -Force -Path C:\winfsp.msi
# while the server ISO is plugged in, the virtio drivers are in the 2nd CDROM slot, E:
# ...but when we boot up later without the server ISO it will be in D:
pnputil.exe /add-driver E:\virtio-win\viofs\2k22\amd64\viofs.inf /install
# ...but when we boot up later without the server ISO it will be in D:
& "C:\Program Files (x86)\WinFsp\bin\fsreg.bat" virtiofs "D:\virtio-win\viofs\2k22\amd64\virtiofs.exe" "-t %1 -m %2"


# -- install chocolately --
Set-ExecutionPolicy Bypass -Scope Process -Force; [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))

# -- install telnet --
Enable-WindowsOptionalFeature -Online -NoRestart -FeatureName "TelnetClient"

# -- install tools --
choco install --ignore-detected-reboot -y visualstudio2022community
choco install --ignore-detected-reboot -y visualstudio2022-workload-nativedesktop
choco install --ignore-detected-reboot -y git
choco install --ignore-detected-reboot -y python311 --params "CompileAll=1"
choco install --ignore-detected-reboot -y neovim
choco install --ignore-detected-reboot -y sysinternals
choco install --ignore-detected-reboot -y procexp
choco install --ignore-detected-reboot -y adoptopenjdk
choco install --ignore-detected-reboot -y ghidra

# git requires a reboot to work, so we can't install git python packages right now...
py -m pip install --user pwntools
py -m pip install --user IPython
py -m pip install --user ROPgadget

# -- install VNC server --
# install options reference: https://www.tightvnc.com/doc/win/TightVNC_2.7_for_Windows_Installing_from_MSI_Packages.pdf
choco install --ignore-detected-reboot tightvnc -y --installArguments 'ADDLOCAL=Server SET_RFBPORT=1 VALUE_OF_RFBPORT=5912 SET_USEVNCAUTHENTICATION=1 VALUE_OF_USEVNCAUTHENTICATION=1 SET_PASSWORD=1 SET_DISCONNECTACTION=2 VALUE_OF_PASSWORD=abcd'
# this will be done later when the service actually exists
#Set-Service -Name tvnserver -StartupType 'Manual'

& sc.exe create ChallengeProxy binPath="C:\Program Files\Common Files\challenge-proxy.exe" displayname="Challenge Proxy" depend=TcpIp start=auto

if (!(Get-NetFirewallRule -Name "ChallengeProxy-In-TCP" -ErrorAction SilentlyContinue | Select-Object Name, Enabled)) {
    Write-Output "Firewall Rule 'ChallengeProxy-In-TCP' does not exist, creating it..."
    New-NetFirewallRule -Name 'ChallengeProxy-In-TCP' -DisplayName 'ChallengeProxy' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 4001
} else {
    Write-Output "Firewall rule 'ChallengeProxy-In-TCP' has been created and exists."
}

# -- disable admin account --
net user administrator /active:no

# Based on https://gist.github.com/Tras2/06670c93199b5621ce2076a36e86f41e
function EnableWmiRemoting($namespace) {
    $invokeparams = @{Namespace=$namespace;Path="__systemsecurity=@"}
    $output = Invoke-WmiMethod -Name GetSecurityDescriptor @invokeparams
    if ($output.ReturnValue -ne 0) {
        throw "GetSecurityDescriptor failed: $($output.ReturnValue)"
    }
    $acl = $output.Descriptor

    $computerName = (Get-WmiObject Win32_ComputerSystem).Name
    $acc = Get-WmiObject -Class Win32_Group -Filter "Domain='$computerName' and Name='Users'"

    $WBEM_ENABLE            = 0x00001 # Enable
    $WBEM_METHOD_EXECUTE    = 0x00002 # MethodExecute
    $WBEM_FULL_WRITE_REP    = 0x00004 # FullWrite
    $WBEM_PARTIAL_WRITE_REP = 0x00008 # PartialWrite
    $WBEM_WRITE_PROVIDER    = 0x00010 # ProviderWrite
    $WBEM_REMOTE_ACCESS     = 0x00020 # RemoteAccess
    $WBEM_RIGHT_SUBSCRIBE   = 0x00040
    $WBEM_RIGHT_PUBLISH     = 0x00080
    $READ_CONTROL           = 0x20000 # ReadSecurity
    $WRITE_DAC              = 0x40000 # WriteSecurity

    # Execute Methods | Enable Account | ProviderWrite
    $defaultMask = $WBEM_METHOD_EXECUTE + $WBEM_ENABLE + $WBEM_WRITE_PROVIDER
    # Remote Enable
    $accessMask = $defaultMask + $WBEM_REMOTE_ACCESS

    $ace = (New-Object System.Management.ManagementClass("win32_Ace")).CreateInstance()
    $ace.AccessMask = $accessMask
    $ace.AceFlags = 0

    $trustee = (New-Object System.Management.ManagementClass("win32_Trustee")).CreateInstance()
    $trustee.SidString = $acc.Sid
    $ace.Trustee = $trustee

    $ACCESS_ALLOWED_ACE_TYPE = 0x0
    $ACCESS_DENIED_ACE_TYPE  = 0x1
    $ace.AceType = $ACCESS_ALLOWED_ACE_TYPE

    $acl.DACL += $ace.psobject.immediateBaseObject
    $output = Invoke-WmiMethod -Name SetSecurityDescriptor -ArgumentList $acl.psobject.immediateBaseObject @invokeparams
    if ($output.ReturnValue -ne 0) {
        throw "SetSecurityDescriptor failed: $($output.ReturnValue)"
    }
}

EnableWmiRemoting "Root/WMI"
EnableWmiRemoting "Root/CIMV2"
EnableWmiRemoting "Root/StandardCimv2"

# -- edit password policy & shutdown policy --
& secedit /export /cfg C:\Windows\Temp\policy-edit.inf
(Get-Content -Path C:\Windows\Temp\policy-edit.inf) `
    -replace "PasswordComplexity = 1", "PasswordComplexity = 0" `
    -replace "SeShutdownPrivilege .+", "`$0,hacker" `
    -replace "SeRemoteShutdownPrivilege .+", "`$0,hacker" |
    Set-Content -Path C:\Windows\Temp\policy-edit.inf
& secedit /configure /db C:\windows\security\local.sdb /cfg C:\Windows\Temp\policy-edit.inf
Remove-Item -Force C:\Windows\Temp\policy-edit.inf
Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\Lsa" -Name "LimitBlankPasswordUse" -Value 0

# -- set empty password for hacker user --
$SecureString = New-Object System.Security.SecureString
Get-LocalUser -Name hacker | Set-LocalUser -Password $SecureString -PasswordNeverExpires $true

# -- edit SSH config --
# to support empty passwords, we require the following settings:
# PasswordAuthentication yes
# PermitEmptyPasswords yes
Copy-Item "A:\sshd_config" -Destination "$env:programdata\ssh\sshd_config"

# install.ps1
# - Single script for installing user applications used in windows challenge VM
# - Infra/Required installs should be placed in setup.ps1

# Wrapper obj used to create shortcuts throughout
$WScriptObj = (New-Object -ComObject ("WScript.Shell"))

# Disable Superfetch - prevent windows VM dynamically preloading RAM
Stop-Service -Force -Name "SysMain"
Set-Service -Name "SysMain" -StartupType Disabled

# Install VCLib dependency
Invoke-WebRequest -Uri https://aka.ms/Microsoft.VCLibs.x64.14.00.Desktop.appx -outfile Microsoft.VCLibs.x86.14.00.Desktop.appx
Add-AppxPackage Microsoft.VCLibs.x86.14.00.Desktop.appx
Remove-Item Microsoft.VCLibs.x86.14.00.Desktop.appx

# choco friendly installs
# Note: Several packages do not install correctly via choco despite
# being packaged, hence the manual installs below

# install windbg
(New-Object Net.WebClient).DownloadFile("https://windbg.download.prss.microsoft.com/dbazure/prod/1-2308-2002-0/windbg.msixbundle", "C:\windbg.msixbundle")
add-appxpackage -Path C:\windbg.msixbundle
Remove-Item -Force -Path C:\windbg.msixbundle
$windbg_sc = $WScriptObj.CreateShortcut("C:\Users\hacker\Desktop/windbg.lnk")
$windbg_sc.TargetPath = "C:\Users\Hacker\AppData\Local\Microsoft\WindowsApps\WinDbgX.exe"
$windbg_sc.save()

if ("INSTALL_IDA_FREE" -eq "yes") {
    (New-Object Net.WebClient).DownloadFile("https://out7.hex-rays.com/files/idafree82_windows.exe", "C:\idafree.exe")
    Start-Process "C:\idafree.exe" -ArgumentList "--unattendedmodeui minimal --mode unattended --installpassword freeware" -Wait
    Remove-Item -Force -Path "C:\idafree.exe"
}

# install Windows Terminal
Invoke-WebRequest -Uri https://github.com/microsoft/terminal/releases/download/v1.7.1091.0/Microsoft.WindowsTerminal_1.7.1091.0_8wekyb3d8bbwe.msixbundle -outfile Microsoft.WindowsTerminal_1.7.1091.0_8wekyb3d8bbwe.msixbundle
Add-AppxPackage -Path .\Microsoft.WindowsTerminal_1.7.1091.0_8wekyb3d8bbwe.msixbundle
Remove-Item Microsoft.WindowsTerminal_1.7.1091.0_8wekyb3d8bbwe.msixbundle

# x64 Debug - Note: Releases get deleted so this URL is going to break
Invoke-WebRequest -Uri https://github.com/x64dbg/x64dbg/releases/download/snapshot/snapshot_2024-03-08_16-44.zip -Outfile x64dbg.zip
Expand-Archive x64dbg.zip -DestinationPath "C:/pwncollege/x64dbg" -Force
Remove-Item x64dbg.zip
$x64dbg_sc = $WScriptObj.CreateShortcut("C:\Users\hacker\Desktop/x64dbg.lnk")
$x64dbg_sc.TargetPath = "C:\pwncollege\x64dbg\release\x96dbg.exe"
$x64dbg_sc.save()

# rp++
Invoke-WebRequest -Uri https://github.com/0vercl0k/rp/releases/download/v2.1.3/rp-win.zip -Outfile rp-win.zip
Expand-Archive rp-win.zip -DestinationPath "C:/pwncollege/rp-win" -Force
Remove-Item rp-win.zip

# CFF Explorer
Invoke-WebRequest -Uri  https://ntcore.com/files/ExplorerSuite.exe -Outfile "C:\ExplorerSuite.exe"
Start-Process "C:\ExplorerSuite.exe" -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-" -Wait
Remove-Item -Force -Path "C:\ExplorerSuite.exe"

# These install correctly with choco, but keeping manual install steps
# Sysinternals
#Invoke-WebRequest -Uri https://download.sysinternals.com/files/SysinternalsSuite.zip -Outfile sysinternals.zip
#Expand-Archive sysinternals.zip -DestinationPath "C:\pwncollege\sysinternals" -Force

# Process Explorer
#Invoke-WebRequest -Uri https://download.sysinternals.com/files/ProcessExplorer.zip -Outfile procexp.zip
#Expand-Archive procexp.zip -DestinationPath "C:\pwncollege\processExplorer" -Force
#$pe_sc = $WScriptObj.CreateShortcut("C:\Users\hacker\Desktop/Process Explorer.lnk")
#$pe_sc.TargetPath = "C:\pwncollege\procexp64.exe"
#$x64dbg_sc.save()

# -- hosts file --
$ip = [System.Net.Dns]::GetHostAddresses("msdl.microsoft.com")
Add-Content -Path $env:windir\System32\drivers\etc\hosts -Value "`n$ip`tmsdl.microsoft.com" -Force

$ip = [System.Net.Dns]::GetHostAddresses("public-lumina.hex-rays.com")
Add-Content -Path $env:windir\System32\drivers\etc\hosts -Value "`n$ip`tpublic-lumina.hex-rays.com" -Force

# Unfortunately, launching sshd must be set as a startup file and cannot be done done via the service interface in this file
Copy-Item A:\config_startup.ps1 -Destination "C:\Program Files\Common Files\startup.ps1"
& schtasks /create /tn "dojoinit" /sc onstart /delay 0000:00 /rl highest /ru system /tr "powershell.exe -file 'C:\Program Files\Common Files\startup.ps1'" /f

# config services' StartupType to start when Start-Service is called or manually started (Manual) instead of start with Windows (Automatic)
Set-Service -Name sshd -StartupType Manual
Set-Service -Name tvnserver -StartupType Manual

# -- shutdown --
Stop-Computer -computername localhost -force
