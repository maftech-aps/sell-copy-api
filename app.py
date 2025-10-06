from __future__ import annotations
from urllib.parse import urlparse
from typing import List
import requests
from bs4 import BeautifulSoup, Comment
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, AnyHttpUrl

app = FastAPI(
    title="楽天市場→売れる説明文API",
    version="1.0.0",
    servers=[{"url": "https://sell-copy-api.onrender.com"}],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

# ---------------- 楽天市場専用ルール ----------------
INCLUDE_SELECTORS = [
    "#itemDesc",
    "#item_description",
    "#productDetail",
    "#rakutenLimitedId_itemDescription",
    "div.item_desc",
    "div#description",
    "div.product-detail",
    "div#itemDetail",
]
EXCLUDE_SELECTORS = [
    "#review-area", ".review", "#shop-info", "#shipping", "#payment",
    "#privacy", "#attention", ".product-review", "#voice"
]

def fetch_html(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    return resp.text

def extract_rakuten_description(url: str) -> str:
    netloc = urlparse(url).netloc
    if "item.rakuten.co.jp" not in netloc:
        raise ValueError("楽天市場の商品URLのみ対応しています。")
    html = fetch_html(url)
    soup = BeautifulSoup(html, "lxml")

    # 不要要素除去
    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()
    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        c.extract()
    for sel in EXCLUDE_SELECTORS:
        for el in soup.select(sel):
            el.decompose()

    # 商品説明領域の探索
    candidates = []
    for sel in INCLUDE_SELECTORS:
        for el in soup.select(sel):
            text = el.get_text("\n", strip=True)
            if len(text) > 80:
                candidates.append((len(text), text))
    if not candidates:
        raise ValueError("楽天の商品説明文を抽出できませんでした。")
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1].strip()

# ---------------- コピー生成 ----------------
def build_sales_copy(raw: str, tone="premium") -> str:
    tone_text = "上質で洗練された"
    title = raw.split("\n")[0][:60]
    body = f"{title}は、{tone_text}仕上がりで、日常を特別に彩ります。"
    md = f"""# {title}
**{title} — {tone_text}一品。**

{body}

## 特徴
- こだわりの仕立てで日常使いに最適
- 贈り物・ギフトにも喜ばれる定番
- シーンを選ばず使えるバランスの良さ

**今すぐカートに入れる**
"""
    return md

# ---------------- APIエンドポイント ----------------
class ExtractRequest(BaseModel):
    url: AnyHttpUrl

class ExtractResponse(BaseModel):
    success: bool
    raw_description: str
    sales_copy_md: str

@app.post("/extract-and-copy", response_model=ExtractResponse)
def extract_and_copy(req: ExtractRequest):
    try:
        raw = extract_rakuten_description(req.url)
        md = build_sales_copy(raw)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    return ExtractResponse(success=True, raw_description=raw, sales_copy_md=md)

# ---------------- プライバシーポリシー ----------------
from fastapi.responses import HTMLResponse
@app.get("/privacy", include_in_schema=False)
def privacy():
    return HTMLResponse("<h1>プライバシーポリシー</h1><p>楽天市場URLのみを解析します。</p>")
