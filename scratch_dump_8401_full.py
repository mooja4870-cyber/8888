import sys
import app
import json

app._HIST_CACHE.clear()
data = app.collect()
bot8401 = next((b for b in data['bots'] if b['name'] == '8401'), None)
print(json.dumps(bot8401, indent=2, ensure_ascii=False))
