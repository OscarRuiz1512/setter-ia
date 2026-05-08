#!/bin/bash
launchctl unload ~/Library/LaunchAgents/com.setter-ia.server.plist 2>/dev/null
pkill -f "uvicorn main:app" 2>/dev/null
echo "Setter IA detenido."
