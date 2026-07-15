@echo off
rem BabaYaga watchdog for the Windows VPS: relaunches the bot if it crashes or
rem the terminal restarts. Set your EXNESS_* / guardrail environment variables
rem before running this (see docs\exness-vps.md).
rem
rem The hard-stop lock is respected: if HALTED.lock exists, the relaunched bot
rem starts in the halted state and will NOT trade until you delete the file.

:loop
python examples\run_exness.py
echo(
echo Bot exited with code %errorlevel%. Restarting in 10 seconds (Ctrl+C to stop)...
timeout /t 10 /nobreak >nul
goto loop
