@echo off
REM Deployment board: copy your army list in New Recruit and double-click this file,
REM or drop one or two list files (.txt) onto it.
cd /d "%~dp0"
python army_photo.py --board --map ask --terrain ask --board-style ask %*
pause
