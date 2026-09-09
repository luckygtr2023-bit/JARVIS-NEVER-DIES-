$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut('C:\Users\ravit\OneDrive\Desktop\J.A.R.V.I.S. Launcher.lnk')
$Shortcut.TargetPath = 'D:\TiTech Prabha Solution\Brahma AI\Brahma AI\Brahma-AI---Lite-main\Brahma-AI---Lite-main\.venv\Scripts\pythonw.exe'
$Shortcut.Arguments = '"D:\TiTech Prabha Solution\Brahma AI\Brahma AI\Brahma-AI---Lite-main\Brahma-AI---Lite-main\main.py"'
$Shortcut.WorkingDirectory = 'D:\TiTech Prabha Solution\Brahma AI\Brahma AI\Brahma-AI---Lite-main\Brahma-AI---Lite-main'
$Shortcut.WindowStyle = 7
$Shortcut.Description = 'Launch J.A.R.V.I.S.'
if ('D:\TiTech Prabha Solution\Brahma AI\Brahma AI\Brahma-AI---Lite-main\Brahma-AI---Lite-main\assets\jarvis_logo.ico') { $Shortcut.IconLocation = 'D:\TiTech Prabha Solution\Brahma AI\Brahma AI\Brahma-AI---Lite-main\Brahma-AI---Lite-main\assets\jarvis_logo.ico,0' }
$Shortcut.Save()