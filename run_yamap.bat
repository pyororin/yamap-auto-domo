@echo off
REM --- 環境変数を設定 ---
set YAMAP_LOGIN_ID=shunichi1014@gmail.com
set YAMAP_LOGIN_PASSWORD=yamaptest
set YAMAP_USER_ID=278948

REM --- スクリプトのあるディレクトリに移動（必要に応じてパスを修正） ---
cd /d E:\vscode\yamap-auto-domo

REM --- Pythonスクリプトを実行 ---
python -m yamap_auto.yamap_auto_domo

REM --- 終了待機 ---
pause
