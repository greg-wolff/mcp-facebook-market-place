#!/usr/bin/env python3
"""Find under-market deals in a sweep of LA Marketplace categories."""
import asyncio
import json
import re
import statistics
import sys
from pathlib import Path

from scraper import scrape_marketplace_async

CATEGORIES = [
    "iphone 15",
    "macbook air m2",
    "ps5",
    "apple watch ultra",
    "electric bike",
]

JUNK_PATTERNS = [
    r"\bbroken\b", r"\bcracked\b", r"\bparts?\b", r"\bnot working\b",
    r"\bdamage\b", r"\bcase only\b", r"\bbox only\b", r"\bdoes not\b",
    r"\bno power\b", r"\bdead\b", r"\bfor repair\b", r"\bissue\b",
]


def parse_price(s: str) -> float | None:
    if not s:
        return None
    m = re.search(r"[\d,]+(?:\.\d+)?", s.replace(",", ""))
    return float(m.group()) if m else None


def is_junk_title(title: str) -> bool:
    t = title.lower()
    return any(re.search(p, t) for p in JUNK_PATTERNS)


def rank_deals(listings: list[dict], category: str) -> list[dict]:
    priced = [{**l, "price_num": parse_price(l["price"])} for l in listings]
    priced = [l for l in priced if l["price_num"]]
    if len(priced) < 4:
        return []

    prices = [l["price_num"] for l in priced]
    median = statistics.median(prices)
    p25 = statistics.quantiles(prices, n=4)[0]
    # Filter junk titles + extreme low (likely scam/parts/typo)
    floor = median * 0.25
    candidates = []
    for l in priced:
        if l["price_num"] < floor:
            continue
        if is_junk_title(l["title"]):
            continue
        discount = (median - l["price_num"]) / median
        if discount < 0.30:  # less than 30% below median: not a "deal"
            continue
        candidates.append({
            **l,
            "category": category,
            "median": median,
            "p25": p25,
            "discount_pct": round(discount * 100, 1),
        })
    candidates.sort(key=lambda x: -x["discount_pct"])
    return candidates


async def main():
    sweep_file = Path("sweep.json")
    if sweep_file.exists() and "--reuse" in sys.argv:
        sweep = json.loads(sweep_file.read_text())
    else:
        sweep = {}
        for q in CATEGORIES:
            print(f"Searching: {q}", file=sys.stderr)
            results = await scrape_marketplace_async(
                query=q, location_id="la", days_listed=7, headless=True
            )
            sweep[q] = [
                {"listing_id": l.listing_id, "title": l.title, "price": l.price,
                 "location": l.location, "url": l.url, "image_url": l.image_url}
                for l in results
            ]
        sweep_file.write_text(json.dumps(sweep, indent=2))

    all_deals = []
    for q, listings in sweep.items():
        deals = rank_deals(listings, q)
        all_deals.extend(deals)
        n = len(listings)
        med = statistics.median([parse_price(l["price"]) for l in listings if parse_price(l["price"])]) if n else 0
        print(f"\n{q}: {n} listings, median ${med:.0f}, {len(deals)} candidate deals", file=sys.stderr)

    all_deals.sort(key=lambda x: -x["discount_pct"])
    print(json.dumps(all_deals[:15], indent=2))


if __name__ == "__main__":
    asyncio.run(main())
