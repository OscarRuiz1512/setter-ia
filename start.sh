#!/bin/bash
cd "$(dirname "$0")"
launchctl load ~/Library/LaunchAgents/com.setter-ia.server.plist 2>/dev/null
echo "Setter IA arrancando en http://localhost:8000"
echo "Panel admin: http://localhost:8000/panel"
echo "Logs: tail -f logs/server.log"
