param([switch]$Silencioso, [switch]$Remover)
# Instalador do Titan Match (Windows) — instala no seu usuário, sem administrador.
#   Python embutido + app em %LOCALAPPDATA%\TitanMatch
#   Atalho em DaVinci Resolve > Workspace > Scripts > Color > Titan Match
# Uso sem janela:  powershell -ExecutionPolicy Bypass -File Instalar_Titan_Match.ps1 -Silencioso [-Remover]
$ErrorActionPreference = 'Stop'
$payload  = Join-Path $PSScriptRoot 'Arquivos'
$root     = Join-Path $env:LOCALAPPDATA 'TitanMatch'
$scripts  = Join-Path $env:APPDATA 'Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Color'
$launcher = Join-Path $scripts 'Titan Match.py'
$versao   = (Get-Content (Join-Path $payload 'app\VERSION') -Raw).Trim()

function Assert-Dentro([string]$path, [string]$base) {
    $r = [IO.Path]::GetFullPath($path); $b = [IO.Path]::GetFullPath($base).TrimEnd('\') + '\'
    if (-not $r.StartsWith($b, [StringComparison]::OrdinalIgnoreCase)) { throw "Destino inesperado: $r" }
}

function Instalar {
    foreach ($p in @('python\pythonw.exe', 'app\titan_match\__init__.py', 'app\templates', 'Titan Match.py')) {
        if (-not (Test-Path -LiteralPath (Join-Path $payload $p))) { throw 'Pacote incompleto. Extraia o ZIP inteiro antes de instalar.' }
    }
    if (Get-Process pythonw -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$root*" }) {
        throw 'Feche a janela do Titan Match antes de instalar.'
    }
    New-Item -ItemType Directory -Force -Path $root | Out-Null
    # Backup do app anterior (licença, configuração e logs ficam intactos: não estão em app\ nem python\)
    $appOld = Join-Path $root 'app'
    if (Test-Path -LiteralPath $appOld) {
        $bk = Join-Path $root ('backups\instalador-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
        New-Item -ItemType Directory -Force -Path $bk | Out-Null
        Copy-Item -LiteralPath $appOld -Destination $bk -Recurse
    }
    foreach ($part in @('python', 'app')) {
        $dest = Join-Path $root $part
        Assert-Dentro $dest $root
        if (Test-Path -LiteralPath $dest) { Remove-Item -LiteralPath $dest -Recurse -Force }
        Copy-Item -LiteralPath (Join-Path $payload $part) -Destination $dest -Recurse
    }
    New-Item -ItemType Directory -Force -Path $scripts | Out-Null
    $l = (Get-Content (Join-Path $payload 'Titan Match.py') -Raw).Replace('__TITAN_MATCH_ROOT__', $root)
    [IO.File]::WriteAllText($launcher, $l, (New-Object Text.UTF8Encoding $false))
    # Pasta de LUTs do Titan Match na pasta mestre do Resolve (o plugin grava os LUTs de CST aqui)
    $lut = 'C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\LUT\Titan Match'
    try { New-Item -ItemType Directory -Force -Path $lut | Out-Null } catch {}
    return "Titan Match $versao instalado! No DaVinci Resolve: página Color > Workspace > Scripts > Titan Match."
}

function Remover {
    Assert-Dentro (Join-Path $root 'app') $root
    foreach ($part in @('python', 'app')) {
        $d = Join-Path $root $part
        if (Test-Path -LiteralPath $d) { Remove-Item -LiteralPath $d -Recurse -Force }
    }
    if (Test-Path -LiteralPath $launcher) { Remove-Item -LiteralPath $launcher -Force }
    return 'Titan Match removido. Sua licença e configurações foram mantidas.'
}

if ($Silencioso) {
    try { if ($Remover) { Write-Host (Remover) } else { Write-Host (Instalar) } }
    catch { Write-Host ('ERRO: ' + $_.Exception.Message); exit 1 }
    exit 0
}

Add-Type -AssemblyName PresentationFramework
[xml]$markup = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Titan Match" Width="600" Height="600" ResizeMode="NoResize" WindowStartupLocation="CenterScreen"
        Background="#090B14" Foreground="#F1F5F9" FontFamily="Segoe UI">
 <Grid Margin="32">
  <Grid.RowDefinitions><RowDefinition Height="70"/><RowDefinition Height="26"/><RowDefinition Height="*"/><RowDefinition Height="56"/><RowDefinition Height="26"/></Grid.RowDefinitions>
  <Image x:Name="Brand" HorizontalAlignment="Left" Height="56" Stretch="Uniform"/>
  <TextBlock Grid.Row="1" Text="OBSIDIAN • ROXO TITAN" Foreground="#A45FFF" FontSize="11"/>
  <StackPanel Grid.Row="2" Margin="0,18,0,0">
   <TextBlock Text="Color match por referência." FontSize="24" FontWeight="SemiBold" Margin="0,0,0,14"/>
   <TextBlock Text="Escolha a imagem de referência e o Titan Match monta a árvore de nós no DaVinci Resolve." Foreground="#94A3B8" TextWrapping="Wrap" Margin="0,0,0,18"/>
   <Border Background="#131525" BorderBrush="#232742" BorderThickness="1" CornerRadius="12" Padding="18"><StackPanel>
    <TextBlock Text="Instalação no seu usuário • sem administrador" FontSize="14"/>
    <TextBlock Text="Python já incluído. Atualizações automáticas pelo GitHub, com backup." Foreground="#94A3B8" Margin="0,8,0,0" TextWrapping="Wrap"/>
   </StackPanel></Border>
   <TextBlock x:Name="Status" Text="Feche o Titan Match antes de instalar ou remover." Foreground="#40C9FF" Margin="0,16,0,0" TextWrapping="Wrap"/>
  </StackPanel>
  <Grid Grid.Row="3"><Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="16"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
   <Button x:Name="Remove" Content="Remover" Height="40" Background="#1C2034" Foreground="#CBD5E1" BorderThickness="0"/>
   <Button x:Name="Install" Grid.Column="2" Content="Instalar / atualizar" Height="40" Background="#8855F7" Foreground="#FFFFFF" FontWeight="Bold" BorderThickness="0"/>
  </Grid>
  <TextBlock x:Name="Ver" Grid.Row="4" Foreground="#64748B" VerticalAlignment="Bottom" FontSize="11"/>
 </Grid>
</Window>
'@
$window = [Windows.Markup.XamlReader]::Load((New-Object Xml.XmlNodeReader $markup))
$logo = Join-Path $payload 'app\assets\titan_match_logo.png'
if (Test-Path -LiteralPath $logo) { $window.FindName('Brand').Source = $logo }
$window.FindName('Ver').Text = "Titan Match • v$versao"
$ico = Join-Path $payload 'app\assets\titan_match.ico'
if (Test-Path -LiteralPath $ico) { $window.Icon = $ico }
$status = $window.FindName('Status')
$window.FindName('Install').Add_Click({
    try { $status.Text = 'Instalando…'; $window.Dispatcher.Invoke([action]{}, 'Render'); $status.Text = Instalar }
    catch { $status.Text = 'Falha na instalação: ' + $_.Exception.Message }
})
$window.FindName('Remove').Add_Click({
    if ([Windows.MessageBox]::Show('Remover o Titan Match? Sua licença e configurações serão mantidas.', 'Titan Match', 'YesNo', 'Question') -ne 'Yes') { return }
    try { $status.Text = Remover } catch { $status.Text = 'Não foi possível remover: ' + $_.Exception.Message }
})
$null = $window.ShowDialog()
