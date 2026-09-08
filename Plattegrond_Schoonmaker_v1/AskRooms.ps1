Add-Type -AssemblyName System.Windows.Forms
$result = [System.Windows.Forms.MessageBox]::Show(
    "Wil je ook losse PNG's per ruimte laten maken (inclusief deuren/ramen)?" + [Environment]::NewLine + [Environment]::NewLine + "Dit duurt iets langer en werkt het best bij tekeningen met CAD-lagen.",
    "Plattegrond Schoonmaker",
    [System.Windows.Forms.MessageBoxButtons]::YesNo,
    [System.Windows.Forms.MessageBoxIcon]::Question
)
if ($result -eq [System.Windows.Forms.DialogResult]::Yes) {
    Write-Output "yes"
} else {
    Write-Output "no"
}
