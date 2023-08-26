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

# -- enable SSH --
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
# Start the sshd service
Start-Service sshd
# Autostart sshd
Set-Service -Name sshd -StartupType 'Automatic'

# Confirm the Firewall rule is configured. It should be created automatically by setup.
if (!(Get-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -ErrorAction SilentlyContinue | Select-Object Name, Enabled)) {
    Write-Output "Firewall Rule 'OpenSSH-Server-In-TCP' does not exist, creating it..."
    New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22
} else {
    Write-Output "Firewall rule 'OpenSSH-Server-In-TCP' has been created and exists."
}

# -- virtfs --
Invoke-Webrequest 'https://github.com/winfsp/winfsp/releases/download/v2.0/winfsp-2.0.23075.msi' -OutFile C:\winfsp.msi
Start-Process msiexec -ArgumentList "/i C:\winfsp.msi /qn" -Wait
Remove-Item C:\winfsp.msi
# this is a bit confusing, but
# while the server ISO is plugged in, the virtio drivers are in the 2nd CDROM slot, E:
pnputil.exe /add-driver E:\virtio-win\viofs\2k22\amd64\viofs.inf /install
# ...but when we boot up later without the server ISO it will be in D:
sc.exe create VirtioFsSvc binpath="D:\virtio-win\viofs\2k22\amd64\virtiofs.exe" start=auto depend= WinFsp.Launcher/VirtioFsDrv DisplayName="Virtio FS Service"

# -- shutdown --
Stop-Computer -computername localhost -force
