"""Compila el codigo del plugin contra la API oficial de cada version de AutoCAD (paquetes NuGet), sin tener
AutoCAD instalado. Si compila, la API que usa el plugin existe con la misma firma en esa version.
NO prueba el comportamiento en vivo (idioma, dialogos, tipos de linea): solo que el codigo es compatible.

Uso: python tools/matriz_api.py [2019 2025 ...]   (sin argumentos: todas)
2019-2024: AutoCAD.NET (net48); 2025-2026: ModPlus.AutoCAD.API (net8); 2027: AutoCAD.NET 26 (net10).
Necesita el SDK de .NET 10 y acceso a nuget.org."""
import os, shutil, subprocess, sys, re, json
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "plugin", "AutoCadMcpPlugin")
BASE = os.path.join(os.environ.get("TEMP", "/tmp"), "matriz_api")
os.makedirs(BASE, exist_ok=True)

# (version de AutoCAD, paquete, target)
MATRIZ = [("2019", "23.0.0", "net48"), ("2020", "23.1.0", "net48"), ("2021", "24.0.0", "net48"),
          ("2022", "24.1.51000", "net48"), ("2023", "24.2.0", "net48"), ("2024", "24.3.0", "net48"),
          ("2025", "modplus:2025:3.0.0", "net8.0-windows"), ("2026", "modplus:2026:3.0.0", "net8.0-windows"),
          ("2027", "26.0.0", "net10.0-windows")]
solo = sys.argv[1:]
resumen = []
for anio, ver, tfm in MATRIZ:
    if solo and anio not in solo:
        continue
    d = os.path.join(BASE, anio)
    if os.path.exists(d):
        shutil.rmtree(d, ignore_errors=True)
    shutil.copytree(SRC, d, ignore=shutil.ignore_patterns("bin", "obj", "*.csproj"))
    if ver.startswith("modplus:"):
        _, anio_m, v_m = ver.split(":")
        paquete = f'<PackageReference Include="ModPlus.AutoCAD.API.{anio_m}" Version="{v_m}" ExcludeAssets="runtime" />'
    else:
        paquete = f'<PackageReference Include="AutoCAD.NET" Version="{ver}" ExcludeAssets="runtime" />'
    extra_net48 = ('<PackageReference Include="System.Text.Json" Version="8.0.5" />\n'
                   '    <Reference Include="System.Windows.Forms" />') if tfm == "net48" else ""
    fw = '<FrameworkReference Include="Microsoft.WindowsDesktop.App" />' if tfm != "net48" else ""
    copia = "<CopyLocalLockFileAssemblies>true</CopyLocalLockFileAssemblies>" if tfm != "net48" else ""
    csproj = f"""<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>{tfm}</TargetFramework>
    <LangVersion>latest</LangVersion>
    <AssemblyName>AutoCadMcpPlugin</AssemblyName>
    <RootNamespace>AutoCadMcpPlugin</RootNamespace>
    <PlatformTarget>x64</PlatformTarget>
    {copia}
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Microsoft.CodeAnalysis.CSharp" Version="4.8.0" />
    {paquete}
    {extra_net48}
    {fw}
  </ItemGroup>
</Project>"""
    open(os.path.join(d, "AutoCadMcpPlugin.csproj"), "w", encoding="utf-8").write(csproj)
    r = subprocess.run(["dotnet", "build", d, "-c", "Release", "--nologo", "-v", "q"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    sal = r.stdout + r.stderr
    lineas_err = sorted(set(l.strip() for l in sal.splitlines() if " error " in l))
    ok = r.returncode == 0
    resumen.append((anio, ver, tfm, ok, len(lineas_err)))
    print(f"AutoCAD {anio} ({ver}, {tfm}): {'COMPILA' if ok else 'FALLA'}  errores distintos: {len(lineas_err)}", flush=True)
    for l in lineas_err[:6]:
        print("    ", re.sub(r"\[.*?\]$", "", l)[:230], flush=True)
json.dump(resumen, open(os.path.join(BASE, "resumen.json"), "w"))
sys.exit(0 if all(r[3] for r in resumen) else 1)
