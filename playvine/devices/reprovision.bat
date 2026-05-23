@echo off
title Device Provisioning
setlocal enabledelayedexpansion
mode con cols=35 lines=10
goto main
:main
cls
echo PlayVine - Device Provisioning
echo.
echo  Select DRM scheme:
echo.
echo    [1] Widevine
echo    [2] PlayReady
echo    [Q] Quit
echo.
set "choice="
set /p "choice=> "
if /i "%choice%"=="1" goto menuwv
if /i "%choice%"=="2" goto menupr
if /i "%choice%"=="Q" goto end
if /i "%choice%"=="quit" goto end
goto main
:menuwv
cls
echo Widevine
echo.
echo    [1] New .wvd 		 (from client_id.bin + private_key.pem)
echo    [2] Migrate .wvd     (upgrade an old .wvd to the current format)
echo    [B] Back
echo.
set "choice="
set /p "choice=Choice: "
if /i "%choice%"=="1" goto wv_create
if /i "%choice%"=="2" goto wv_migrate
if /i "%choice%"=="B" goto main
goto menuwv
:wv_create
cls
echo Widevine - Create Device
echo.
set "wv_client="
set /p "wv_client=Path to client_id.bin: "
if "!wv_client!"=="" (
    echo. & echo client_id is required. & pause & goto menuwv
)
if not exist "!wv_client!" (
    echo. & echo File not found: !wv_client! & pause & goto menuwv
)
set "wv_key="
set /p "wv_key=Path to private_key.pem (RSA private key): "
if "!wv_key!"=="" (
    echo. & echo Private key is required. & pause & goto menuwv
)
if not exist "!wv_key!" (
    echo. & echo File not found: !wv_key! & pause & goto menuwv
)
set "wv_type="
set /p "wv_type=Device type [ANDROID / CHROME] (default: ANDROID): "
if "!wv_type!"=="" set "wv_type=ANDROID"
set "wv_level="
set /p "wv_level=Security Level? (default: 3): "
if "!wv_level!"=="" set "wv_level=3"
set "wv_vmp="
set /p "wv_vmp=Path to VMP FileHashes blob (optional): "
set "wv_out="
set /p "wv_out=Output path or filename (optional): "
echo.
echo Running: pywidevine create-device...
echo.
if "!wv_vmp!"=="" (
    if "!wv_out!"=="" (
        pywidevine create-device -t !wv_type! -l !wv_level! -k "!wv_key!" -c "!wv_client!"
    ) else (
        pywidevine create-device -t !wv_type! -l !wv_level! -k "!wv_key!" -c "!wv_client!" -o "!wv_out!"
    )
) else (
    if "!wv_out!"=="" (
        pywidevine create-device -t !wv_type! -l !wv_level! -k "!wv_key!" -c "!wv_client!" -v "!wv_vmp!"
    ) else (
        pywidevine create-device -t !wv_type! -l !wv_level! -k "!wv_key!" -c "!wv_client!" -v "!wv_vmp!" -o "!wv_out!"
    )
)
echo.
pause
goto main
:wv_migrate
cls
echo Widevine - Migrate Device
echo.
echo  Migrate old WVD to new.
echo.
set "wv_path="
set /p "wv_path=Path to .wvd file to migrate: "
if "!wv_path!"=="" (
    echo. & echo Path is required. & pause & goto menuwv
)
if not exist "!wv_path!" (
    echo. & echo File not found: !wv_path! & pause & goto menuwv
)
echo.
echo Running: pywidevine migrate "!wv_path!"
echo.
pywidevine migrate "!wv_path!"
echo.
pause
goto main
:menupr
cls
echo PlayReady
echo.
echo    [1] Reprovision .prd  (new leaf certificate (Requires v3 or higher))
echo    [2] Create new .prd   (from group certificate + group key)
echo    [B] Back
echo.
set "choice="
set /p "choice=Choice: "
if /i "%choice%"=="1" goto pr_reprovision
if /i "%choice%"=="2" goto pr_create
if /i "%choice%"=="B" goto main
goto menupr
:pr_reprovision
cls
echo PlayReady - Reprovision Device
echo.
echo  Re-issues the leaf certificate on an existing PRD.
echo  Only works on PRD files of v3 or higher.
echo.
set "pr_path="
set /p "pr_path=Path to .prd file: "
if "!pr_path!"=="" (
    echo. & echo .prd path is required. & pause & goto menupr
)
if not exist "!pr_path!" (
    echo. & echo File not found: !pr_path! & pause & goto menupr
)
set "pr_enc="
set /p "pr_enc=Path to encryption key (optional): "
set "pr_sig="
set /p "pr_sig=Path to signing key (optional): "
set "pr_out="
set /p "pr_out=Output path (optional): "
echo.
echo Running: pyplayready reprovision-device...
echo.
if "!pr_enc!"=="" (
    if "!pr_sig!"=="" (
        if "!pr_out!"=="" (
            pyplayready reprovision-device "!pr_path!"
        ) else (
            pyplayready reprovision-device "!pr_path!" -o "!pr_out!"
        )
    ) else (
        if "!pr_out!"=="" (
            pyplayready reprovision-device "!pr_path!" -s "!pr_sig!"
        ) else (
            pyplayready reprovision-device "!pr_path!" -s "!pr_sig!" -o "!pr_out!"
        )
    )
) else (
    if "!pr_sig!"=="" (
        if "!pr_out!"=="" (
            pyplayready reprovision-device "!pr_path!" -e "!pr_enc!"
        ) else (
            pyplayready reprovision-device "!pr_path!" -e "!pr_enc!" -o "!pr_out!"
        )
    ) else (
        if "!pr_out!"=="" (
            pyplayready reprovision-device "!pr_path!" -e "!pr_enc!" -s "!pr_sig!"
        ) else (
            pyplayready reprovision-device "!pr_path!" -e "!pr_enc!" -s "!pr_sig!" -o "!pr_out!"
        )
    )
)
echo.
pause
goto main
:pr_create
cls
echo PlayReady - Create Device
echo.
echo  Provide: group_key OR protected_group_key.
echo.
set "pr_gkey="
set /p "pr_gkey=Path to group key (leave blank if using protected): "
set "pr_pgkey="
if "!pr_gkey!"=="" set /p "pr_pgkey=Path to protected group key: "
if "!pr_gkey!"=="" if "!pr_pgkey!"=="" (
    echo. & echo You must provide one of the two group keys. & pause & goto menupr
)
if not "!pr_gkey!"=="" if not exist "!pr_gkey!" (
    echo. & echo File not found: !pr_gkey! & pause & goto menupr
)
if not "!pr_pgkey!"=="" if not exist "!pr_pgkey!" (
    echo. & echo File not found: !pr_pgkey! & pause & goto menupr
)
set "pr_gcert="
set /p "pr_gcert=Path to group certificate chain: "
if "!pr_gcert!"=="" (
    echo. & echo Group certificate is required. & pause & goto menupr
)
if not exist "!pr_gcert!" (
    echo. & echo File not found: !pr_gcert! & pause & goto menupr
)
set "pr_enc="
set /p "pr_enc=Path to encryption key (optional): "
set "pr_sig="
set /p "pr_sig=Path to signing key (optional): "
set "pr_out="
set /p "pr_out=Output path (optional): "
echo.
echo Running: pyplayready create-device...
echo.
set "pr_cmd=pyplayready create-device -c "!pr_gcert!""
if not "!pr_gkey!"=="" set "pr_cmd=!pr_cmd! -k "!pr_gkey!""
if not "!pr_pgkey!"=="" set "pr_cmd=!pr_cmd! -pk "!pr_pgkey!""
if not "!pr_enc!"=="" set "pr_cmd=!pr_cmd! -e "!pr_enc!""
if not "!pr_sig!"=="" set "pr_cmd=!pr_cmd! -s "!pr_sig!""
if not "!pr_out!"=="" set "pr_cmd=!pr_cmd! -o "!pr_out!""
call !pr_cmd!
echo.
pause
goto main
:end
endlocal
exit /b 0