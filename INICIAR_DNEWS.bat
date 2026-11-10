@echo off
rem D.News em http://localhost:8790
cd /d "%~dp0"
start "" http://localhost:8790
python server.py
