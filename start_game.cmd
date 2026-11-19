@echo off
cd /d "%~dp0"
python reaction_game.py
if errorlevel 1 pause
