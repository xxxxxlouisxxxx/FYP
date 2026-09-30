"""Generate recorded-style sandbox fixtures for the outdoor-apparel proof-of-concept domain pack.

Payloads reuse the DataForSEO envelope, SERP and search-volume shapes from
``generate_sandbox_fixtures.py`` so the same platform parsers read them; only the content differs.
Scenarios include one need with no search volume returned (NOT_COLLECTED) and one brand that is
visible in search but never recommended in generative answers.

Run: python scripts/generate_outdoor_apparel_fixtures.py [--out DIR]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate_sandbox_fixtures import RECORDED_AT, _slug, serp_doc, volume_doc, write  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "domain_packs" / "outdoor_apparel" / "sandbox"
MARKET = "HK"
MARKET_NAME = "Hong Kong"
RETAIL = ["www.chamonix.com.hk", "www.hktvmall.com", "www.protrek.com.hk", "www.zalora.com.hk"]
FORUMS = ["lihkg.com", "www.discuss.com.hk", "www.reddit.com"]
MEDIA = ["www.outdoorgearlab.com", "www.switchbacktravel.com", "www.gearpatrol.com"]
OFF_SERP = ["https://www.outdoorgearreview.example/", "https://www.hikingblog.example/"]
MANUFACTURER = {
    "The North Face": "www.thenorthface.com",
    "Columbia": "www.columbia.com",
    "Patagonia": "www.patagonia.com",
    "Arc'teryx": "www.arcteryx.com",
    "Uniqlo": "www.uniqlo.com",
    "Quechua": "www.decathlon.com.hk",
    "Mammut": "www.mammut.com",
    "Montbell": "www.montbell.com",
    "Icebreaker": "www.icebreaker.com",
    "Smartwool": "www.smartwool.com",
}

NEEDS = {
    "humid_rain_shell": {
        "query": ("q_humid_rain_shell_en", "breathable rain jacket for humid weather"),
        "phrase": "breathable rain jackets for humid weather",
        "supply": "Breathable Rain Jacket",
        "attr": "a waterproof breathable 3-layer shell with pit zips",
        "products": [
            ("Arc'teryx", "Beta LT"),
            ("Patagonia", "Torrentshell 3L"),
            ("Montbell", "Versalite"),
            ("The North Face", "Dryzzle FUTURELIGHT"),
            ("Columbia", "OutDry Extreme"),
        ],
        "exclude": ("Mammut", "Convey Tour", "is too warm for humid summers"),
        "generic": ("The North Face", "Columbia"),
    },
    "sun_protection_hoodie": {
        "query": ("q_sun_hoodie_en", "best UPF sun protection hoodie"),
        "phrase": "UPF sun protection hoodies",
        "supply": "UPF 50+ Sun Hoodie",
        "attr": "UPF 50+ sun protection in a lightweight knit",
        "products": [
            ("Patagonia", "Capilene Cool"),
            ("Uniqlo", "UV Protection Pocketable Parka"),
            ("Columbia", "Silver Ridge"),
            ("Smartwool", "Active Ultralite"),
        ],
        "exclude": ("Icebreaker", "260 Tech", "is too heavy for summer sun"),
        "generic": ("Uniqlo", "Patagonia"),
    },
    "kids_rain_suit": {
        "query": ("q_kids_rain_suit_en", "waterproof kids rain suit"),
        "phrase": "waterproof kids rain suits",
        "supply": "Kids Rain Suit",
        "attr": "a kids waterproof one-piece with taped seams",
        "products": [("Quechua", "MH500 Kids"), ("Columbia", "Watertight II Kids"), ("The North Face", "Antora Kids")],
        "exclude": ("Arc'teryx", "Beta LT", "is not made in kids sizes"),
        "generic": ("Quechua", "Columbia"),
        "serp_only_brand": ("Uniqlo", "Kids Pocketable Parka"),
    },
    "packable_down_travel": {
        "query": ("q_packable_down_en", "packable down jacket for travel"),
        "phrase": "packable down jackets for travel",
        "supply": "Packable Down Jacket",
        "attr": "packable down insulation that stuffs into its own pocket",
        "products": [
            ("Uniqlo", "Ultra Light Down"),
            ("Montbell", "Plasma 1000"),
            ("Patagonia", "Down Sweater"),
            ("Arc'teryx", "Cerium"),
            ("The North Face", "Aconcagua"),
        ],
        "exclude": ("Columbia", "Arcadia", "is not insulated"),
        "generic": ("Uniqlo", "Montbell"),
    },
    "merino_base_layer": {
        "query": ("q_merino_base_layer_en", "merino wool base layer"),
        "phrase": "merino wool base layers",
        "supply": "Merino Base Layer",
        "attr": "a soft merino base layer that resists odour",
        "products": [
            ("Icebreaker", "200 Oasis"),
            ("Smartwool", "Classic Thermal"),
            ("Montbell", "Wickron"),
            ("Patagonia", "Capilene Air"),
        ],
        "exclude": ("Uniqlo", "HEATTECH", "is synthetic, not merino"),
        "generic": ("Icebreaker", "Smartwool"),
    },
    "plus_size_hiking_pants": {
        "query": ("q_plus_size_hiking_pants_en", "plus size hiking pants"),
        "phrase": "plus size hiking pants",
        "supply": "Plus Size Hiking Pants",
        "attr": "extended sizes up to 4XL in a 4-way stretch fabric",
        "products": [("Columbia", "Silver Ridge Plus"), ("Quechua", "MH500 Plus"), ("Patagonia", "Quandary Plus")],
        "exclude": ("Mammut", "Runbold", "stops at size XL"),
        "generic": ("Columbia", "Mammut"),
    },
}

# volume None = provider returned null; supply = on-need product pages in the top 10;
# recs = answers (of repeats) that recommend a product; cite = whether citations appear in the SERP.
SCENARIOS = {
    "humid_rain_shell": dict(volume=4400, yoy=0.21, supply=2, recs=1, cite="high"),
    "sun_protection_hoodie": dict(volume=2900, yoy=0.30, supply=3, recs=3, cite="low"),
    "kids_rain_suit": dict(volume=2600, yoy=0.08, supply=4, recs=3, cite="high"),
    "packable_down_travel": dict(volume=3600, yoy=0.02, supply=8, recs=3, cite="high"),
    "merino_base_layer": dict(volume=None, yoy=0.0, supply=6, recs=3, cite="high"),
    "plus_size_hiking_pants": dict(volume=2400, yoy=0.18, supply=1, recs=1, cite="high"),
}


def serp_items(need: str, supply: int) -> list[dict]:
    n = NEEDS[need]
    supply_items = []
    for i in range(supply):
        brand, model = n["products"][i % len(n["products"])]
        domain = RETAIL[i // 2 % len(RETAIL)] if i % 2 == 0 else MANUFACTURER[brand]
        supply_items.append((domain, f"{brand} {model} {n['supply']}", f"Shop the {brand} {model} with {n['attr']}."))
    others = [
        (FORUMS[0], f"Any {n['phrase']}? - LIHKG", f"Hikers in {MARKET_NAME} say local shops have few {n['phrase']}."),
        (MEDIA[0], f"The Best {n['phrase'].title()} | OutdoorGearLab", f"We tested {n['phrase']} side by side."),
        (
            "www.hk01.com",
            f"Hikers struggle to find {n['phrase']}",
            f"Choice of {n['phrase']} in {MARKET_NAME} is limited.",
        ),
        (MEDIA[1], f"{n['phrase'].title()} Guide | Switchback Travel", "Our picks after a season of testing."),
        (FORUMS[2], f"{n['phrase'].capitalize()} - reddit", "Discussion thread with 85 comments."),
        (MEDIA[2], f"How to choose {n['phrase']} | Gear Patrol", "What to look for before you buy."),
        (FORUMS[1], f"{n['phrase'].capitalize()} discussion - Discuss.com.hk", "Members share where they shop."),
        (MANUFACTURER[n["generic"][0]], f"Outdoor Clothing | {n['generic'][0]} {MARKET_NAME}", "Shop the new season."),
        (RETAIL[0], "Outdoor Clothing Sale | CHAMONIX", "Members get 10% off hiking apparel."),
        ("www.hko.gov.hk", "Weather and UV index - Hong Kong Observatory", "Daily forecasts for outdoor activities."),
    ]
    if n.get("serp_only_brand"):
        b, p = n["serp_only_brand"]
        others.insert(0, (MANUFACTURER[b], f"{b} {p} | {b} {MARKET_NAME}", f"The {b} {p} for rainy school runs."))
        others.insert(2, (RETAIL[1], f"{b} {p}", f"{b} {p} available now."))
        others.insert(4, (MEDIA[2], f"{b} {p} review", f"Is the {b} {p} worth it?"))
    others = others[: max(0, 10 - len(supply_items))]
    ordered: list[tuple[str, str, str]] = []
    first, second = (list(supply_items), others) if supply >= 5 else (others, list(supply_items))
    while first or second:
        if first:
            ordered.append(first.pop(0))
        if second:
            ordered.append(second.pop(0))
    return [
        {
            "type": "organic",
            "rank_group": rank,
            "rank_absolute": rank,
            "position": "left",
            "domain": domain,
            "title": title,
            "url": f"https://{domain}/{_slug(title)[:60]}",
            "description": snippet,
            "breadcrumb": f"https://{domain} › outdoor",
            "is_image": False,
            "is_video": False,
        }
        for rank, (domain, title, snippet) in enumerate(ordered, start=1)
    ]


def gerp_answers(need: str, sc: dict, serp_urls: list[str], repeats: int = 5) -> list[dict]:
    n = NEEDS[need]
    ex_b, ex_p, ex_reason = n["exclude"]
    answers = []
    for r in range(repeats):
        if r % 3 < sc["recs"]:
            (b1, p1), (b2, p2) = n["products"][0], n["products"][1]
            text = (
                f"For {n['phrase']} in {MARKET_NAME}, my top pick is the {b1} {p1}, which offers {n['attr']}. "
                f"Another good option is the {b2} {p2}. I would avoid the {ex_b} {ex_p} because it {ex_reason}."
            )
            cites = serp_urls[:2] if sc["cite"] == "high" else [u + _slug(p1) for u in OFF_SERP]
        else:
            g1, g2 = n["generic"]
            text = (
                f"When shopping for {n['phrase']}, check the fit and look for {n['attr']}. "
                f"Brands such as {g1} and {g2} make items in this category, but stock in {MARKET_NAME} varies, "
                "so try them on in store before buying."
            )
            cites = [OFF_SERP[0] + _slug(n["phrase"])]
        answers.append(
            {
                "repeat_index": r,
                "model_id": "recorded-gerp-2026-09",
                "recorded_at": RECORDED_AT,
                "answer_text": text,
                "citations": cites,
            }
        )
    return answers


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=ROOT)
    root = parser.parse_args().out
    rows: list[tuple[str, int | None, float]] = []
    for need, sc in SCENARIOS.items():
        qid, kw = NEEDS[need]["query"]
        rows.append((kw, sc["volume"], sc["yoy"]))
        items = serp_items(need, sc["supply"])
        write(root / MARKET / "serp" / f"{qid}.json", serp_doc(MARKET, qid, kw, "en", items))
        urls = [i["url"] for i in items]
        write(
            root / MARKET / "gerp" / f"{qid}.json",
            {"query_id": qid, "market": MARKET, "answers": gerp_answers(need, sc, urls)},
        )
    write(root / MARKET / "demand" / "search_volume_en.json", volume_doc(MARKET, "en", rows))
    print(f"fixtures written to {root}")


if __name__ == "__main__":
    main()
