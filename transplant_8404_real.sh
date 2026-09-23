#!/bin/bash
set -e
SOURCE="/Users/l/project/8410"
TARGET="/Users/l/project/8404"

echo "=================================================="
echo " 8404(OKX) <- 8410(Binance) 안전 이식 수술 시작"
echo "=================================================="

# 1. rsync로 로직 덮어쓰기 (위험 파일 철저 배제)
echo "▶ 8410 로직 복사 중..."
rsync -a --delete \
  --exclude='.env' \
  --exclude='.git' \
  --exclude='venv' \
  --exclude='run.sh' \
  --exclude='run_bot.sh' \
  --exclude='api.md' \
  --exclude='*.log' \
  --exclude='logs/' \
  --exclude='data/' \
  --exclude='scratch/' \
  --exclude='__pycache__/' \
  "$SOURCE/" "$TARGET/"

# 2. 거래소 설정(EXCHANGE_ID)을 okx로 원복
echo "▶ 8404 거래소 정체성(okx) 강제 주입..."
cd "$TARGET"
sed -i '' 's/"EXCHANGE_ID": "[^"]*"/"EXCHANGE_ID": "okx"/' config.json
if ! grep -q '"EXCHANGE_ID": "okx"' config.json; then
    echo "❌ config.json 거래소 패치 실패!"
    exit 1
fi

# 3. run.sh 라벨 수정 (8404_binance -> 8404_okx)
sed -i '' 's/8404_binance/8404_okx/g' run.sh

# 4. 8404 봇 재기동
echo "▶ 8404 봇 프로세스 재기동..."
./run_bot.sh stop 2>/dev/null || pkill -f "8404" || true
sleep 1
bash run.sh

echo "▶ 기동 확인 대기 (5초)..."
sleep 5
echo "=================================================="
echo " 이식 완료! 마켓 로드 상태 확인:"
tail -n 15 bot_engine.log
echo "=================================================="
