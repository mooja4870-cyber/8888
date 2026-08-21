#!/bin/bash
git add app.py ver.md
git commit -m "fix: 대시보드 새로고침 시 8개 봇이 순간 표시되는 플리커링 현상 해결"
git tag v2.3.31
git push origin main
git push origin v2.3.31
