"""Portal collectors for WF02: LinkedIn, Indeed, Naukri."""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
_REQUEST_TIMEOUT = 20
_RETRY_COUNT = 3
_RETRY_DELAY = 2.0


class PortalCollectionError(RuntimeError):
    """Raised when a portal collector fails fatally."""


# ── shared helpers ────────────────────────────────────────────────────────────

def _get_with_retry(url: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
    session = requests.Session()
    session.headers.update(_HEADERS)
    last_exc: Exception = RuntimeError("no attempt made")
    for attempt in range(_RETRY_COUNT):
        try:
            response = session.get(url, params=params, timeout=_REQUEST_TIMEOUT)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < _RETRY_COUNT - 1:
                time.sleep(_RETRY_DELAY * (attempt + 1))
    raise PortalCollectionError(f"GET {url} failed after {_RETRY_COUNT} attempts: {last_exc}")


def _clean(text: Any) -> str:
    return " ".join(str(text or "").split())


# ── LinkedIn collector ────────────────────────────────────────────────────────

def collect_linkedin_jobs(
    keywords: List[str],
    locations: List[str],
    max_results: int = 25,
) -> List[Dict[str, Any]]:
    """Scrape LinkedIn public job search (no login required for listings)."""
    jobs: List[Dict[str, Any]] = []
    keyword_str = " OR ".join(keywords[:4])
    location_str = locations[0] if locations else "Remote"
    params = {
        "keywords": keyword_str,
        "location": location_str,
        "f_TPR": "r86400",  # last 24h
        "start": 0,
    }
    base_url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    while len(jobs) < max_results:
        try:
            response = _get_with_retry(base_url, params=params)
        except PortalCollectionError:
            break
        soup = BeautifulSoup(response.text, "lxml")
        cards = soup.find_all("li")
        if not cards:
            break
        for card in cards:
            job = _parse_linkedin_card(card)
            if job:
                # Scoring compares the candidate's skills against the job text.
                # The result cards carry no description at all, so without this
                # every job scores on its title alone and nothing clears a
                # realistic threshold.
                job["description"] = _fetch_linkedin_description(job["url"])
                jobs.append(job)
            if len(jobs) >= max_results:
                break
        params["start"] = int(params["start"]) + len(cards)
        time.sleep(1.5)
    return jobs[:max_results]


def _fetch_linkedin_description(url: str) -> str:
    """Read the job description off a public LinkedIn posting.

    Best effort: a posting that cannot be fetched still yields a usable job
    record, just a weaker match score, so failure returns an empty string
    rather than aborting the whole collection.
    """
    if not url:
        return ""
    try:
        response = _get_with_retry(url)
    except PortalCollectionError:
        return ""
    soup = BeautifulSoup(response.text, "lxml")
    node = soup.select_one("div.description__text") or soup.select_one(
        "div.show-more-less-html__markup"
    )
    if node is None:
        return ""
    text = node.get_text(" ", strip=True)
    # The guest page appends its expander controls to the text.
    text = re.sub(r"\s*Show (?:more|less)\s*", " ", text).strip()
    time.sleep(1.0)  # the search loop already paces itself; keep detail hits polite too
    return text[:6000]


def _parse_linkedin_card(card: Any) -> Optional[Dict[str, Any]]:
    try:
        title_tag = card.find("h3", class_=re.compile("base-search-card__title|job-search-card__title"))
        company_tag = card.find("h4", class_=re.compile("base-search-card__subtitle|job-search-card__company-name"))
        location_tag = card.find("span", class_=re.compile("job-search-card__location"))
        link_tag = card.find("a", href=re.compile(r"linkedin\.com/jobs/view/"))
        title = _clean(title_tag.text) if title_tag else ""
        company = _clean(company_tag.text) if company_tag else ""
        location = _clean(location_tag.text) if location_tag else ""
        url = str(link_tag["href"]).split("?")[0] if link_tag else ""
        if not title or not company:
            return None
        return {
            "title": title,
            "company": company,
            "location": location,
            "url": url,
            "source": "linkedin",
            "description": "",
            "posted_date": "",
            "skills": [],
        }
    except Exception:
        return None


# ── Indeed collector ──────────────────────────────────────────────────────────

def collect_indeed_jobs(
    keywords: List[str],
    locations: List[str],
    max_results: int = 25,
) -> List[Dict[str, Any]]:
    """Scrape Indeed public job search results."""
    jobs: List[Dict[str, Any]] = []
    keyword_str = " ".join(keywords[:4])
    location_str = locations[0] if locations else "Remote"
    base_url = "https://www.indeed.com/jobs"
    params = {"q": keyword_str, "l": location_str, "start": 0, "sort": "date"}
    while len(jobs) < max_results:
        try:
            response = _get_with_retry(base_url, params=params)
        except PortalCollectionError:
            break
        soup = BeautifulSoup(response.text, "lxml")
        cards = soup.find_all("div", class_=re.compile(r"job_seen_beacon|resultContent"))
        if not cards:
            break
        for card in cards:
            job = _parse_indeed_card(card)
            if job:
                jobs.append(job)
            if len(jobs) >= max_results:
                break
        params["start"] = int(params["start"]) + 10
        time.sleep(1.5)
    return jobs[:max_results]


def _parse_indeed_card(card: Any) -> Optional[Dict[str, Any]]:
    try:
        title_tag = card.find("span", id=re.compile("jobTitle"))
        company_tag = card.find("span", {"data-testid": "company-name"}) or card.find("span", class_=re.compile("companyName"))
        location_tag = card.find("div", {"data-testid": "text-location"}) or card.find("div", class_=re.compile("companyLocation"))
        link_tag = card.find("a", href=re.compile(r"/rc/clk|/pagead/clk"))
        title = _clean(title_tag.text) if title_tag else ""
        company = _clean(company_tag.text) if company_tag else ""
        location = _clean(location_tag.text) if location_tag else ""
        href = link_tag["href"] if link_tag else ""
        url = f"https://www.indeed.com{href}" if href.startswith("/") else href
        if not title or not company:
            return None
        return {
            "job_title": title,
            "company_name": company,
            "job_location": location,
            "apply_url": url,
            "source": "indeed",
            "description": "",
            "posted_date": "",
            "skills": [],
        }
    except Exception:
        return None


# ── Naukri collector ──────────────────────────────────────────────────────────

def collect_naukri_jobs(
    keywords: List[str],
    locations: List[str],
    experience_years: int = 0,
    max_results: int = 25,
) -> List[Dict[str, Any]]:
    """Scrape Naukri public job search."""
    jobs: List[Dict[str, Any]] = []
    keyword_str = "-".join(k.lower().replace(" ", "-") for k in keywords[:3])
    location_str = "-".join(l.lower().replace(" ", "-") for l in locations[:2]) if locations else "india"
    exp = min(max(experience_years, 0), 30)
    base_url = f"https://www.naukri.com/{keyword_str}-jobs-in-{location_str}-{exp}"
    try:
        response = _get_with_retry(base_url)
    except PortalCollectionError:
        return []
    soup = BeautifulSoup(response.text, "lxml")
    cards = soup.find_all("article", class_=re.compile("jobTuple")) or soup.find_all("div", class_=re.compile("cust-job-tuple"))
    for card in cards:
        job = _parse_naukri_card(card)
        if job:
            jobs.append(job)
        if len(jobs) >= max_results:
            break
    return jobs[:max_results]


def _parse_naukri_card(card: Any) -> Optional[Dict[str, Any]]:
    try:
        title_tag = card.find("a", class_=re.compile("title"))
        company_tag = card.find("a", class_=re.compile("subTitle")) or card.find("span", class_=re.compile("companyInfo"))
        location_tag = card.find("span", class_=re.compile("location"))
        title = _clean(title_tag.text) if title_tag else ""
        company = _clean(company_tag.text) if company_tag else ""
        location = _clean(location_tag.text) if location_tag else ""
        url = str(title_tag["href"]) if title_tag and title_tag.get("href") else ""
        if not title or not company:
            return None
        return {
            "title": title,
            "company": company,
            "location": location,
            "url": url,
            "source": "naukri",
            "description": "",
            "posted_date": "",
            "skills": [],
        }
    except Exception:
        return None


# ── collector dispatcher ──────────────────────────────────────────────────────

def collect_remoteok_jobs(
    keywords: List[str],
    max_results: int = 25,
) -> List[Dict[str, Any]]:
    """Read RemoteOK's public JSON feed and keep what matches the keywords.

    The feed is a single global list rather than a search endpoint, so filtering
    happens here. Descriptions ship with the feed, which means these records
    score properly without a second request per job.
    """
    try:
        response = _get_with_retry("https://remoteok.com/api")
    except PortalCollectionError:
        return []

    try:
        records = response.json()
    except ValueError:
        return []
    if not isinstance(records, list):
        return []

    # Each keyword becomes the set of words that must all appear in the title,
    # in any order. Exact-phrase matching missed 'Senior QA Automation Engineer'
    # for the keyword 'QA Automation Engineer'; whole-word matching avoids 'qa'
    # hitting 'equality' or 'test' hitting 'latest'.
    wanted: List[List[re.Pattern[str]]] = []
    for keyword in keywords:
        words = [word for word in re.split(r"\W+", keyword.strip().lower()) if word]
        if words:
            wanted.append([re.compile(rf"\b{re.escape(word)}\b") for word in words])
    jobs: List[Dict[str, Any]] = []
    for record in records:
        # The first element is RemoteOK's legal notice, not a posting.
        if not isinstance(record, dict) or not record.get("position"):
            continue

        description = _clean(BeautifulSoup(str(record.get("description", "")), "lxml").get_text(" "))
        # Title only. The description mentions 'QA' or 'testing' in passing on
        # plenty of unrelated roles, and RemoteOK's tags are auto-generated and
        # near-useless - a Creative Director post carries 27 of them including
        # 'testing' and 'golang'. The title is the only trustworthy signal here.
        haystack = str(record.get("position", "")).lower()
        if wanted and not any(
            all(pattern.search(haystack) for pattern in group) for group in wanted
        ):
            continue

        jobs.append(
            {
                "title": _clean(str(record.get("position", ""))),
                "company": _clean(str(record.get("company", ""))),
                "location": _clean(str(record.get("location") or "Remote")),
                "url": str(record.get("url") or record.get("apply_url") or ""),
                "source": "remoteok",
                "description": description[:6000],
                "posted_date": str(record.get("date", "")),
                "skills": [str(tag) for tag in record.get("tags") or []],
            }
        )
        if len(jobs) >= max_results:
            break
    return jobs


def collect_portal(
    portal_name: str,
    keywords: List[str],
    locations: List[str],
    experience_years: int = 0,
    max_results: int = 25,
) -> List[Dict[str, Any]]:
    """Dispatch to the right collector for `portal_name`."""
    name = portal_name.lower()
    if name == "linkedin":
        return collect_linkedin_jobs(keywords, locations, max_results)
    if name == "indeed":
        return collect_indeed_jobs(keywords, locations, max_results)
    if name == "naukri":
        return collect_naukri_jobs(keywords, locations, experience_years, max_results)
    if name == "remoteok":
        return collect_remoteok_jobs(keywords, max_results)
    return []


def save_portal_feed(output_dir: Path, portal_name: str, jobs: List[Dict[str, Any]]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    feed_path = output_dir / f"{portal_name}.json"
    feed_path.write_text(json.dumps(jobs, indent=2), encoding="utf-8")
    return feed_path
