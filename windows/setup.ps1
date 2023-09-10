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
Start-Service sshd
# Make sshd start manual
Set-Service -Name sshd -StartupType 'Manual'

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

Copy-Item A:\startup.ps1 -Destination "C:\Program Files\Common Files\"
& schtasks /create /tn "dojoinit" /sc onstart /delay 0000:00 /rl highest /ru system /tr "powershell.exe -file 'C:\Program Files\Common Files\startup.ps1'" /f

# -- install chocolately --
Set-ExecutionPolicy Bypass -Scope Process -Force; [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))

# -- install VNC server --
# install options reference: https://www.tightvnc.com/doc/win/TightVNC_2.7_for_Windows_Installing_from_MSI_Packages.pdf
choco install tightvnc -y --installArguments 'ADDLOCAL=Server SET_RFBPORT=1 VALUE_OF_RFBPORT=5912 SET_USEVNCAUTHENTICATION=1 VALUE_OF_USEVNCAUTHENTICATION=1 SET_PASSWORD=1 VALUE_OF_PASSWORD=abcd'
Set-Service -Name tvnserver -StartupType "Manual"

# -- install windbg --
(New-Object Net.WebClient).DownloadFile("https://windbg.download.prss.microsoft.com/dbazure/prod/1-2308-2002-0/windbg.msixbundle", "C:\windbg.msixbundle")
add-appxpackage -Path C:\windbg.msixbundle
Remove-Item -Force -Path C:\windbg.msixbundle

# -- install IDA --
$InstallIDA = "{INSTALLIDA}";
if ($InstallIDA -eq "True") {
    (New-Object Net.WebClient).DownloadFile("https://out7.hex-rays.com/files/idafree82_windows.exe", "C:\idafree.exe")
    Start-Process "C:\idafree.exe" -ArgumentList "--unattendedmodeui minimal --mode unattended --installpassword freeware" -Wait
    Remove-Item -Force -Path "C:\idafree.exe"
}

# -- install tools --
choco install -y visualstudio2022community
choco install -y visualstudio2022-workload-nativedesktop
choco install -y python311 --params "CompileAll=1"
choco install -y microsoft-windows-terminal

# -- disable admin account --
net user administrator /active:no

# -- shutdown --
Stop-Computer -computername localhost -force
