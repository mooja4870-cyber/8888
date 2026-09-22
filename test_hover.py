from playwright.sync_api import sync_playwright

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        errors = []
        page.on("pageerror", lambda err: errors.append(err.message))
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
        
        page.goto("http://localhost:8888/")
        page.wait_for_timeout(2000)
        
        # Move mouse over botAssetChartCanvas
        canvas = page.locator("#botAssetChartCanvas")
        if canvas.count() > 0:
            box = canvas.bounding_box()
            print("Canvas found at", box)
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.wait_for_timeout(1000)
        
        print("JS Errors:", errors)
        browser.close()

run()
