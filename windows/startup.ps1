(Get-Service WinFsp.Launcher).WaitForStatus('Running')
& "C:\Program Files (x86)\WinFsp\bin\fsreg.bat" virtiofs "D:\virtio-win\viofs\2k22\amd64\virtiofs.exe" "-t %1 -m %2"
& "C:\Program Files (x86)\WinFsp\bin\launchctl-x64.exe" start virtiofs viofsY challenge Y:
& "C:\Program Files (x86)\WinFsp\bin\launchctl-x64.exe" start virtiofs viofsZ home Z:
