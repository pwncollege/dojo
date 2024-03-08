# install.ps1
# - Single script for installing user applications used in windows challenge VM
# - Infra/Required installs should be placed in setup.ps1

# Wrapper obj used to create shortcuts throughout
$WScriptObj = (New-Object -ComObject ("WScript.Shell"))

# TODO: Move superfetch disable to setup.ps1
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

# x64 Debug
Invoke-WebRequest -Uri https://github.com/x64dbg/x64dbg/releases/download/snapshot/snapshot_2024-02-19_03-16.zip -Outfile x64dbg.zip
Expand-Archive x64dbg.zip -DestinationPath "C:/pwncollege/x64dbg" -Force
Remove-Item x64dbg.zip
$x64dbg_sc = $WScriptObj.CreateShortcut("C:\Users\hacker\Desktop/x64dbg.lnk")
$x64dbg_sc.TargetPath = "C:\pwncollege\x64dbg\release\x96dbg.exe"
$x64dbg_sc.save()


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


# -- shutdown --
Stop-Computer -computername localhost -force
