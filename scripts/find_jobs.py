import sys

import json

import re

from dataclasses import dataclass, asdict

from typing import List, Dict, Optional

import requests

from bs4 import BeautifulSoup

KEYWORDS = [

    "python",

    "automation",

    "bot",

    "scraping",

    "api",

    "webhook",

    "selenium",

    "chrome",

    "data",

    "ai",

    "fastapi",

    "flask",

]

USER_AGENT = (

    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "

    "AppleWebKit/537.36 (KHTML, like Gecko) "

    "Chrome/120.0 Safari/537.36"

)

@dataclass

class Job:

    title: str

    budget: Optional[float]

    budget_raw: str

    proposals_raw: str

    proposals_num: int

    payment_verified: bool

    level: str

    duration: str

    link: str

    keyword_matches: List[str]

    keyword_count: int

    priority: str  # A / B / C

def fetch_html(url: str) -> str:

    headers = {"User-Agent": USER_AGENT}

    resp = requests.get(url, headers=headers, timeout=20)

    resp.raise_for_status()

    return resp.text

def parse_budget(text: str) -> Optional[float]:

    """

    Try to extract a numeric budget from text like:

    '$50', '$50.00', '$50 – $100', '$50 - $100', etc.

    Returns the upper bound / single value.

    """

    if not text:

        return None

    # Get all number-like parts

    nums = re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))

    if not nums:

        return None

    try:

        values = [float(n) for n in nums]

    except ValueError:

        return None

    # If it's a range, use the upper bound; otherwise the single value

    return max(values)

def parse_proposals_count(text: str) -> int:

    """

    Map Upwork proposals text to an approximate numeric value.

    Examples:

      'Less than 5' -> 5

      '5 to 10'     -> 10

      '10 to 15'    -> 15

      '15 to 20'    -> 20

      '20 to 50'    -> 50

      '50+'         -> 50

    """

    if not text:

        return 0

    text = text.lower().strip()

    # Direct number

    direct_nums = re.findall(r"\d+", text)

    if "less than" in text and direct_nums:

        try:

            return int(direct_nums[0])

        except ValueError:

            pass

    if "to" in text and len(direct_nums) >= 2:

        try:

            # use lower bound

            return int(direct_nums[0])

        except ValueError:

            pass

    if "less than" in text and not direct_nums:

        return 5

    if "50" in text or "50+" in text:

        return 50

    if direct_nums:

        try:

            return int(direct_nums[-1])

        except ValueError:

            pass

    return 0

def is_long_term(duration_text: str) -> bool:

    """

    長期案件（1ヶ月以上）を True。

    Upwork 例: 'Less than 1 month', '1 to 3 months', '3 to 6 months', 'More than 6 months'

    """

    if not duration_text:

        return False

    t = duration_text.lower()

    if "less than 1 month" in t or "less than one month" in t:

        return False

    if "month" in t:

        return True

    # fallback: treat 'short term' as OK, others as long-term if 'long' exists

    if "long" in t:

        return True

    return False

def get_keyword_matches(text: str) -> List[str]:

    text_lower = text.lower()

    matches = []

    for kw in KEYWORDS:

        if kw in text_lower:

            matches.append(kw)

    return matches

def detect_payment_verified(text: str) -> bool:

    if not text:

        return False

    t = text.lower()

    if "payment verified" in t:

        return True

    if "payment method not verified" in t:

        return False

    return False

def extract_job_cards(soup: BeautifulSoup) -> List[BeautifulSoup]:

    """

    Try multiple selectors to get job cards from Upwork search page.

    """

    cards = []

    # New UI (data-test="JobTile" or "OpportunityCard")

    cards.extend(soup.select('[data-test="JobTile"]'))

    cards.extend(soup.select('[data-test="OpportunityCard"]'))

    # Fallback: generic article / section cards

    if not cards:

        cards.extend(soup.select("article[data-test*='job']"))

        cards.extend(soup.select("section[data-test*='job']"))

    # Deduplicate

    seen = set()

    unique_cards = []

    for c in cards:

        key = id(c)

        if key not in seen:

            seen.add(key)

            unique_cards.append(c)

    return unique_cards

def extract_text(el: Optional[BeautifulSoup]) -> str:

    if el is None:

        return ""

    return " ".join(el.get_text(separator=" ", strip=True).split())

def parse_jobs(html: str, base_url: str) -> List[Job]:

    soup = BeautifulSoup(html, "html.parser")

    cards = extract_job_cards(soup)

    jobs: List[Job] = []

    for card in cards:

        # Title & link

        title_el = card.select_one('a[data-test="job-title"]') or card.select_one("a")

        title = extract_text(title_el)

        if not title:

            continue

        link = ""

        if title_el and title_el.has_attr("href"):

            link = title_el["href"]

            if link.startswith("/"):

                # prepend base domain if not present

                match = re.match(r"^https?://[^/]+", base_url)

                if match:

                    link = match.group(0) + link

        # Budget / rate

        budget_el = (

            card.select_one('[data-test="job-type"] + span')

            or card.select_one('[data-test="budget"]')

            or card.select_one('[data-test="job-price"]')

        )

        budget_raw = extract_text(budget_el)

        budget = parse_budget(budget_raw)

        # Proposals

        proposals_el = (

            card.select_one('[data-test="proposals"]')

            or card.find(lambda tag: tag.name == "span" and "proposal" in tag.get_text(strip=True).lower())

        )

        proposals_raw = extract_text(proposals_el)

        proposals_num = parse_proposals_count(proposals_raw)

        # Payment verified

        payment_el = (

            card.select_one('[data-test="payment-verification-status"]')

            or card.find(lambda tag: tag.name == "span" and "payment" in tag.get_text(strip=True).lower())

        )

        payment_text = extract_text(payment_el)

        payment_verified = detect_payment_verified(payment_text)

        # Experience level

        level_el = (

            card.select_one('[data-test="experience-level"]')

            or card.find(lambda tag: tag.name == "span" and "level" in tag.get_text(strip=True).lower())

        )

        level = extract_text(level_el)

        # Duration

        duration_el = (

            card.select_one('[data-test="job-duration"]')

            or card.find(lambda tag: tag.name == "span" and "month" in tag.get_text(strip=True).lower())

        )

        duration = extract_text(duration_el)

        # Keyword matching (title + maybe small snippet)

        desc_el = card.select_one('[data-test="job-description-text"]') or card.select_one("p")

        combined_text = title + " " + extract_text(desc_el)

        matches = get_keyword_matches(combined_text)

        keyword_count = len(matches)

        job = Job(

            title=title,

            budget=budget,

            budget_raw=budget_raw,

            proposals_raw=proposals_raw,

            proposals_num=proposals_num,

            payment_verified=payment_verified,

            level=level,

            duration=duration,

            link=link,

            keyword_matches=matches,

            keyword_count=keyword_count,

            priority="C",  # temp, will set later

        )

        jobs.append(job)

    return jobs

def apply_filters_and_priorities(jobs: List[Job]) -> Dict[str, List[Job]]:

    result = {"A": [], "B": [], "C": []}

    for job in jobs:

        # Exclude: budget > 150

        if job.budget is not None and job.budget > 150:

            continue

        # Exclude: proposals > 20

        if job.proposals_num > 20:

            continue

        # Exclude: payment not verified

        if not job.payment_verified:

            continue

        # Exclude: long term (>= 1 month)

        if is_long_term(job.duration):

            continue

        # Exclude: keyword matches 0

        if job.keyword_count == 0:

            continue

        # Priority

        if job.keyword_count >= 3 and job.proposals_num < 10:

            job.priority = "A"

        elif job.keyword_count >= 1 and job.proposals_num < 15:

            job.priority = "B"

        else:

            job.priority = "C"

        result[job.priority].append(job)

    return result

def print_table(grouped: Dict[str, List[Job]]) -> None:

    def print_group(label: str, jobs: List[Job]) -> None:

        if not jobs:

            return

        print(f"\n=== {label} ===")

        header = f"{'Title':60}  {'Budget':>8}  {'Prop':>4}  {'Level':12}  {'KW':>2}  Link"

        print(header)

        print("-" * len(header))

        for j in jobs:

            title = (j.title[:57] + "...") if len(j.title) > 60 else j.title

            budget_str = f"{j.budget:.0f}" if j.budget is not None else "-"

            print(

                f"{title:60}  {budget_str:>8}  {j.proposals_num:>4}  {j.level[:12]:12}  {j.keyword_count:>2}  {j.link}"

            )

    print_group("A: 強優先（3キーワード以上 & Proposals < 10）", grouped.get("A", []))

    print_group("B: 中優先（1〜2キーワード & Proposals < 15）", grouped.get("B", []))

    print_group("C: 候補外（その他）", grouped.get("C", []))

def to_json(grouped: Dict[str, List[Job]]) -> str:

    out = {k: [asdict(j) for j in v] for k, v in grouped.items()}

    return json.dumps(out, ensure_ascii=False, indent=2)

def main():

    if len(sys.argv) != 2:

        print("Usage: python find_jobs.py <Upwork search URL>", file=sys.stderr)

        sys.exit(1)

    url = sys.argv[1]

    html = sys.stdin.read() if url == "-" else (fetch_html(url) if url.startswith("http") else open(url, "r", encoding="utf-8").read())

    jobs = parse_jobs(html, url)

    grouped = apply_filters_and_priorities(jobs)

    print_table(grouped)

    print("\n\n=== JSON ===")

    print(to_json(grouped))

if __name__ == "__main__":

    main()

