import os

def replace_in_file(filepath, old, new):
    if not os.path.exists(filepath): return
    with open(filepath, 'r') as f:
        content = f.read()
    content = content.replace(old, new)
    with open(filepath, 'w') as f:
        f.write(content)

app_py = "/Users/l/project/8401/app.py"
replace_in_file(app_py, 'BINANCE_API_KEY', 'OKX_API_KEY')
replace_in_file(app_py, 'BINANCE_SECRET_KEY', 'OKX_SECRET_KEY')
replace_in_file(app_py, 'BINANCE_PASSPHRASE', 'OKX_PASSPHRASE')
replace_in_file(app_py, 'Binance Auto-Trading Dashboard', 'OKX Auto-Trading Dashboard')
replace_in_file(app_py, 'Binance Trader', 'OKX Trader')
replace_in_file(app_py, 'Binance 연결', 'OKX 연결')
replace_in_file(app_py, 'Binance v2.5.1', 'OKX v2.5.1')
replace_in_file(app_py, 'Binance {tag}', 'OKX {tag}')
replace_in_file(app_py, '8410_<span', '8401_<span')
replace_in_file(app_py, '8410_BlueFrog', '8401_BBTS') # BlueFrog was 8409/8410's old name, maybe just keep 8401_BBTS
replace_in_file(app_py, '8410 봇은', '8401 봇은')

settings_tab = "/Users/l/project/8401/ui/settings_tab.py"
replace_in_file(settings_tab, '(8410)', '(8401)')

print("UI text patched.")
