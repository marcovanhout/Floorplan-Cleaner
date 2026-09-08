Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Filter = "PDF bestanden (*.pdf)|*.pdf"
$dialog.Title = "Kies een plattegrond-PDF"
if ($dialog.ShowDialog() -eq "OK") {
    Write-Output $dialog.FileName
}
