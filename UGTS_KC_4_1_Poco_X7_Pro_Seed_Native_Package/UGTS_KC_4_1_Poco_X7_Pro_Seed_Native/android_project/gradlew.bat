@echo off
REM Windows handoff: install Gradle 8.13 or run through Android Studio.
gradle -p "%~dp0" %*
