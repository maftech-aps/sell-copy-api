from __future__ import annotations
import re
from typing import List, Tuple
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, Comment
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, AnyHttpUrl

try:
    import trafilatura  # type: ignore
except Exception:
    trafilatura = None

app = FastAPI(title="URL→売れる説明文 API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

DOMAIN_RULES: dict[str, dict[str, List[str]]] = {
    "item.rakuten.co.jp": {
        "include": [
            "#itemDesc", "#item_description", "#productDetail",
            "#rakutenLimitedId_itemDescription", "div.item_desc",
            "div#description", "div.product-detail", "div#itemDetail",
        ],
        "exclude": [
            "#review-area", ".review", "#shop-info", "#shipping", "#payment",
            "#privacy", "#attention", ".product-review", "#voice"
        ],
    },
    "beerbeerbeer.beer": {
        "include": [
            ".item-detail__description", ".item-detail__body",
            ".product-detail__body", "#item-detail", ".description",
            "article .description"
        ],
        "exclude": [
            ".review", "#review", ".faq", ".policy", ".shipping",
            ".payment", ".return"
        ],
    },
    "generic": {
        "include": [
            "[data-product-description]", ".product-description",
            "#product-description", ".ProductMeta__Description",
            "article .product__description", "section#description",
            ".itemDetail__description", "#product-detail",
            "#description", ".description", ".product__description",
        ],
        "exclude": [
            ".review", "#reviews", "#customer-reviews", ".accordion--shipping",
            ".shipping", ".delivery", ".payment", ".returns", ".policy",
            "#faq", "#q-and-a", "#specs-table-only"
        ],
    },
}

TONES = {
    "standard": {"adj": ["わかりやすい", "実用的", "誠実"], "exclam": ""},
    "premium": {"adj": ["上質", "洗練", "特別"], "exclam": "。"},
    "casual": {"adj": ["カジュアル", "気軽", "毎日"], "exclam": "！"},
    "witty": {"adj": ["遊び心", "ちょい攻め", "記憶に残る"], "exclam": "！"},
}

PLATFORM_HINTS = {
    "rakuten": {"cta": "今すぐカートに入れる"},
    "amazon": {"cta": "今すぐ購入"},
    "base": {"cta": "カートに入れる"},
    "shopify": {"cta": "Add to Cart"},
    "instagram": {"cta": "プロフィールのリンクから"},
    "x": {"cta": "詳細はリンクへ"},
}


class ExtractRequest(BaseModel):
    url: AnyHttpUrl
    platform: str | None = "base"
    tone: str | None = "standard"
    char_limit: int | None = None
    keywords: list[str] | None = None
    brand: str | None = None
    price: str | None = None
    cta: bool | None = True


class ExtractResponse(BaseModel):
    success: bool
    raw_description: str
    sales_copy_md: str


def fetch_html(url: str, timeout: int = 20) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding
    return resp.text


def _remove_unwanted_nodes(soup: BeautifulSoup, exclude_selectors: List[str]) -> None:
    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()
    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        c.extract()
    for sel in exclude_selectors or []:
        for t in soup.select(sel):
            t.decompose()


def _collapse_whitespace(text: str) -> str:
    import re as _re
    text = _re.sub(r"\r\n?|\n\n+", "\n", text)
    text = _re.sub(r"\u3000", " ", text)
    text = _re.sub(r"[ \t\x0b\f\r]+", " ", text)
    lines = [ln.strip() for ln in text.split("\n")]
    text = "\n".join([ln for ln in lines if ln])
    return text.strip()


def extract_description(url: str) -> str:
    html = fetch_html(url)
    soup = BeautifulSoup(html, "lxml")
    netloc = urlparse(url).netloc
    rules = DOMAIN_RULES.get(netloc, DOMAIN_RULES["generic"])
    include, exclude = rules["include"], rules["exclude"]
    _remove_unwanted_nodes(soup, exclude)

    for sel in include:
        for el in soup.select(sel):
            text = el.get_text("\n", strip=True)
            text = _collapse_whitespace(text)
            if len(text) > 80:
                return text
    raise ValueError("商品説明を抽出できませんでした。")


def build_sales_copy(src: str, tone: str, platform: str, brand=None, price=None) -> str:
    tone_map = TONES.get(tone, TONES["standard"])
    cta = PLATFORM_HINTS.get(platform, PLATFORM_HINTS["base"])["cta"]

    title = src.split("\n")[0][:60]
    body = f"{title}は、{tone_map['adj'][1]}な仕上がりで、日常を{tone_map['adj'][2]}に彩ります。"
    if brand:
        body += f" ブランド: {brand}。"
    if price:
        body += f" 価格の目安: {price}。"

    out = [
        f"# {title}",
        f"**{title} — {tone_map['adj'][0]}な一品**{tone_map['exclam']}",
        "",
        body,
        "",
        "## 特徴",
        "- こだわりの仕立てで日常使いに最適",
        "- 贈り物・ギフトにも喜ばれる定番",
        "- シーンを選ばず使えるバランスの良さ",
        "",
        f"**{cta}**",
    ]
    return "\n".join(out)


@app.post("/extract-and-copy", response_model=ExtractResponse)
def extract_and_copy(req: ExtractRequest):
    try:
        raw = extract_description(str(req.url))
        md = build_sales_copy(raw, req.tone or "standard", req.platform or "base", req.brand, req.price)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    return ExtractResponse(success=True, raw_description=raw, sales_copy_md=md)



from fastapi.responses import HTMLResponse

PRIVACY_HTML = """
<!doctype html><meta charset="utf-8">
<title>プライバシーポリシー</title>
<h1>プライバシーポリシー</h1>
<p>本API（URL→売れる説明文API）は、ユーザーが送信した商品URLおよび派生テキストを
API処理の目的で一時的に扱います。個人情報（氏名・住所・決済情報など）を意図的に収集しません。</p>
<h2>収集するデータ</h2>
<ul>
<li>入力された商品URL</li>
<li>サーバーログ（アクセス日時/リクエスト元IP等、Render/ホスティングの標準ログ）</li>
</ul>
<h2>利用目的</h2>
<ul>
<li>商品説明テキストの抽出・文章生成の提供</li>
<li>品質改善・障害対応（エラーログ解析など）</li>
</ul>
<h2>第三者提供</h2>
<p>法令に基づく場合を除き、個人を特定できる形で第三者に提供しません。</p>
<h2>データ保管</h2>
<p>サーバーログはホスティングの保持期間に従い、自動的に削除されます。アプリ側で永続保存は行いません。</p>
<h2>お問い合わせ</h2>
<p>ポリシーに関するお問い合わせは、<a href="mailto:ai@maf-tech.jp">ai@maf-tech.jp</a> までご連絡ください。</p>
"""

@app.get("/privacy", include_in_schema=False)
def privacy():
    return HTMLResponse(PRIVACY_HTML)
