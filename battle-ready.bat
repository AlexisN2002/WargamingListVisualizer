@echo off
REM Battle-ready: models spread out like box art, one character and its unit in the middle.
REM Copy your army list in New Recruit, then double-click this file.
cd /d "%~dp0"
python army_photo.py --battle-ready --center ask %*
pause
