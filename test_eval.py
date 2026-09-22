from playwright.sync_api import sync_playwright

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("http://localhost:8888/")
        page.wait_for_timeout(1000)
        
        print("Chart exists?", page.evaluate("typeof Chart !== 'undefined'"))
        print("Chart.Tooltip exists?", page.evaluate("typeof Chart.Tooltip !== 'undefined'"))
        if page.evaluate("typeof Chart.Tooltip !== 'undefined'"):
            print("Chart.Tooltip.positioners exists?", page.evaluate("typeof Chart.Tooltip.positioners !== 'undefined'"))
        browser.close()

run()
