#!/bin/bash
git add app.py ver.md
git commit -m "fix: 진입 횟수 통계 산출 정확도 개선 및 동적 전략 반영"
git tag v11.0.24
git push origin main
git push origin v11.0.24
