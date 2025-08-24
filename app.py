import asyncio
import aiohttp
from bs4 import BeautifulSoup
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import re
import os

app = FastAPI()

# ---------- FRONTEND ----------
HTML_PAGE = """
<!DOCTYPE html>
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
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def home():
    return HTML_PAGE

# ---------- HELPERS ----------
async def fetch_html(session, url):
    try:
        async with session.get(url, headers={"User-Agent":"Mozilla/5.0"}) as r:
            return await r.text()
    except Exception:
        return ""

def extract_price(text):
    m = re.search(r"(\d+[.,]?\d*)", text.replace(",", "."))
    return float(m.group(1)) if m else 99999

# ---------- CRAWLERS ----------
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

async def crawl_instantgaming(session, game):
    url = f"https://www.instant-gaming.com/en/search/?query={game}"
    html = await fetch_html(session, url)
    soup = BeautifulSoup(html, "lxml")
    results = []
    for card in soup.select(".item"):
        title = card.select_one(".title")
        price = card.select_one(".price")
        link = card.get("href")
        if title and price and link:
            results.append({
                "store":"Instant Gaming",
                "title":title.text.strip(),
                "price":price.text.strip(),
                "url":"https://www.instant-gaming.com" + link
            })
    return results

async def crawl_g2a(session, game):
    url = f"https://www.g2a.com/search?query={game}"
    html = await fetch_html(session, url)
    soup = BeautifulSoup(html, "lxml")
    results = []
    for card in soup.select("a.sc-1j3ie3s-0"):
        title = card.select_one("h3")
        price = card.select_one(".sc-1x6crnh-2")
        if title and price:
            results.append({
                "store":"G2A",
                "title":title.text.strip(),
                "price":price.text.strip(),
                "url":"https://www.g2a.com" + card.get("href")
            })
    return results

async def crawl_gmg(session, game):
    url = f"https://www.greenmangaming.com/search/{game}/"
    html = await fetch_html(session, url)
    soup = BeautifulSoup(html, "lxml")
    results = []
    for card in soup.select(".product"):
        title = card.select_one(".product-title")
        price = card.select_one(".product-price")
        link = card.select_one("a")
        if title and price and link:
            results.append({
                "store":"GreenManGaming",
                "title":title.text.strip(),
                "price":price.text.strip(),
                "url":"https://www.greenmangaming.com" + link.get("href")
            })
    return results

# ---------- SEARCH ENDPOINT ----------
@app.get("/search", response_class=JSONResponse)
async def search(q: str):
    async with aiohttp.ClientSession() as session:
        tasks = [
            crawl_cdkeys(session, q),
            crawl_fanatical(session, q),
            crawl_instantgaming(session, q),
            crawl_g2a(session, q),
            crawl_gmg(session, q),
        ]
        results = await asyncio.gather(*tasks)
    flat = [item for sublist in results for item in sublist]
    flat.sort(key=lambda x: extract_price(x["price"]))
    return flat

# ---------- CLOUD-READY SERVER ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=port)
