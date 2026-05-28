@echo off
setlocal
set "RUN_TAG=2025-09-24_backfill"
python comments_single_only.py --profile erez_gersman --headless --likes-mode off --comments force --reset-daily
echo.
echo Done. Output at: "%CD%\data\instagram_media\%RUN_TAG%"
pause