@echo off
REM Group photo: copy your army list in New Recruit, then double-click this file.
cd /d "%~dp0"
python army_photo.py --group-photo %*
pause
