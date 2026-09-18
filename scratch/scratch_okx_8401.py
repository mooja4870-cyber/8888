import ccxt
import json

keys = json.load(open('/Users/l/project/8888/okx_keys.json'))['8401']
okx = ccxt.okx({
    'apiKey': keys['apikey'],
    'secret': keys['secret'],
    'password': keys['passphrase'],
    'options': {'defaultType': 'swap'},
    'enableRateLimit': True
})

try:
    bal = okx.fetch_balance()
    print(f"OKX Balance for 8401: {bal.get('USDT', {}).get('total')}")
    positions = okx.fetch_positions()
    active = [p for p in positions if float(p['contracts']) > 0]
    print(f"Active positions on OKX for 8401: {len(active)}")
    for p in active:
        print(f"  {p['symbol']}: {p['side']} {p['contracts']}")
except Exception as e:
    print("Error:", e)
