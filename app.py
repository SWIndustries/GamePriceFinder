import asyncio
import aiohttp
from bs4 import BeautifulSoup
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import re
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import chromedriver_autoinstaller

app = FastAPI()

# ---------- FRONTEND ----------
HTML_PAGE = """<!DOCTYPE html>
<html>
<head>
  <title>PC Game Key Price Finder</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 40px; }
    h1 { color: #444; }
    input[type=text] { width: 300px; padding: 8px; }
    button { padding: 8px 14px; margin-left: 6px; }
    table { margin-top: 20px; border-collapse: collapse; width: 90%; }
    th, td { border: 1px solid #ccc; padding: 8px; }
    th { background: #eee; }
  </style>
</head>
<body>
  <h1>PC Game Key Price Finder</h1>
  <input id="gameInput" type="text" placeholder="Enter game name">
  <button onclick="search()">Search</button>

  <div id="results"></div>

  <script>
    async function search() {
      const query = document.getElementById('gameInput').value;
      document.getElementById('results').innerHTML = "Searching...";
      let res = await fetch('/search?q=' + encodeURIComponent(query));
      let data = await res.json();
      if(data.length === 0) {
          document.getElementById('results').innerHTML = "<p>No results found.</p>";
          return;
      }
      let html = "<table><tr><th>Store</th><th>Title</th><th>Price</th><th>Link</th></tr>";
      data.forEach(item => {
        html += `<tr><td>${item.store}</td><td>${item.title||''}</td><td>${item.price||'?'}</td><td><a href="${item.url}" target="_blank">View</a></td></tr>`;
      });
      html += "</table>";
      document.getElementById('results').innerHTML = html;
    }
  </script>
</body>
</html>"""

@app.get("/", response_class=HTMLResponse)
async def home():
    return HTML_PAGE

# ---------- HELPERS ----------
async def fetch_html(session, url):
    try:
        async with session.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=10) as r:
            return await r.text()
    except Exception:
        return ""

def extract_price(text):
    m = re.search(r"(\d+[.,]?\d*)", text.replace(",", "."))
    return float(m.group(1)) if m else 99999

# ---------- STATIC SITE CRAWLERS ----------
async def crawl_cdkeys(session, game):
    url = f"https://www.cdkeys.com/catalogsearch/result/?q={game}"
    html = await fetch_html(session, url)
    soup = BeautifulSoup(html, "lxml")
    results = []
    for item in soup.select(".product-item"):
        title = item.select_one(".product-item-link")
        price = item.select_one(".price")
        if title and price:
            results.append({
                "store":"CDKeys",
                "title":title.text.strip(),
                "price":price.text.strip(),
                "url":title["href"]
            })
    return results

async def crawl_fanatical(session, game):
    url = f"https://www.fanatical.com/en/search?search={game}"
    html = await fetch_html(session, url)
    soup = BeautifulSoup(html, "lxml")
    results = []
    for card in soup.select(".card"):
        title_el = card.select_one(".card__title")
        price_el = card.select_one(".price")
        if title_el and price_el:
            results.append({
                "store":"Fanatical",
                "title":title_el.text.strip(),
                "price":price_el.text.strip(),
                "url":"https://www.fanatical.com" + title_el.get("href")
            })
    return results

# ---------- DYNAMIC SITE CRAWLERS USING SELENIUM ----------
def selenium_driver():
    chromedriver_autoinstaller.install()
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=chrome_options)
    return driver

async def crawl_dynamic_site(func, game):
    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(loop.run_in_executor(None, func, game), timeout=15)
    except asyncio.TimeoutError:
        return []

def crawl_instantgaming(game):
    driver = selenium_driver()
    try:
        driver.get(f"https://www.instant-gaming.com/en/search/?query={game}")
        results = []
        items = driver.find_elements_by_css_selector(".item")
        for card in items[:10]:  # limit top 10
            try:
                title = card.find_element_by_css_selector(".title").text
                price = card.find_element_by_css_selector(".price").text
                link = card.get_attribute("href")
                results.append({"store":"Instant Gaming","title":title,"price":price,"url":link})
            except: pass
        return results
    finally:
        driver.quit()

def crawl_g2a(game):
    driver = selenium_driver()
    try:
        driver.get(f"https://www.g2a.com/search?query={game}")
        results = []
        items = driver.find_elements_by_css_selector("a.sc-1j3ie3s-0")
        for card in items[:10]:
            try:
                title = card.find_element_by_css_selector("h3").text
                price = card.find_element_by_css_selector(".sc-1x6crnh-2").text
                link = card.get_attribute("href")
                results.append({"store":"G2A","title":title,"price":price,"url":link})
            except: pass
        return results
    finally:
        driver.quit()

def crawl_gmg(game):
    driver = selenium_driver()
    try:
        driver.get(f"https://www.greenmangaming.com/search/{game}/")
        results = []
        items = driver.find_elements_by_css_selector(".product")[:10]
        for card in items:
            try:
                title = card.find_element_by_css_selector(".product-title").text
                price = card.find_element_by_css_selector(".product-price").text
                link = card.find_element_by_css_selector("a").get_attribute("href")
                results.append({"store":"GreenManGaming","title":title,"price":price,"url":link})
            except: pass
        return results
    finally:
        driver.quit()

# ---------- SEARCH ENDPOINT ----------
@app.get("/search", response_class=JSONResponse)
async def search(q: str):
    async with aiohttp.ClientSession() as session:
        tasks = [
            asyncio.wait_for(crawl_cdkeys(session, q), timeout=10),
            asyncio.wait_for(crawl_fanatical(session, q), timeout=10),
            crawl_dynamic_site(crawl_instantgaming, q),
            crawl_dynamic_site(crawl_g2a, q),
            crawl_dynamic_site(crawl_gmg, q)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    flat = []
    for res in results:
        if isinstance(res, list):
            flat.extend(res)
    flat.sort(key=lambda x: extract_price(x["price"]))
    return flat

# ---------- CLOUD-READY SERVER ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=port)
