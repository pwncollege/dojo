# Invokes a Cmd.exe shell script and updates the environment.
function Invoke-CmdScript {
  param(
    [String] $scriptName
  )
  $cmdLine = """$scriptName"" $args & set"
  & $Env:SystemRoot\system32\cmd.exe /c $cmdLine |
  select-string '^([^=]*)=(.*)$' | foreach-object {
    $varName = $_.Matches[0].Groups[1].Value
    $varValue = $_.Matches[0].Groups[2].Value
    set-item Env:$varName $varValue
  }
}
Invoke-CmdScript 'C:/Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat' x86_amd64
Push-Location 'C:/Program Files/Common Files'
cl challenge-proxy.c

#Copy-Item -Force challenge-proxy.exe "C:\Program Files\Common Files\"

# Do not use configuration init any further
#Copy-Item -Force startup.ps1 -Destination "C:\Program Files\Common Files\startup.ps1"
#Remove-Item startup.ps1

# -- Add New tasks here to run as hacker with admin privileges ---


# -- shutdown --
Stop-Computer -computername localhost -force
