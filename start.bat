@echo off
cd /d "%~dp0"
start "TyphoonMap Server" cmd /k python server.py
start "TyphoonMap" http://127.0.0.1:8765/
