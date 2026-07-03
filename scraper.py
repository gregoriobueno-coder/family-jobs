#!/usr/bin/env python3
"""
Autonomous Scraper & Execution Agent (scraper.py)
Phase 0: Sourcing (Hybrid Loader: Direct APIs first, falling back to Playwright)
Phase 1: Semantic Filtering & Gatekeeper (Batched Gemini REST API with Structured JSON Output)
"""

import os
import re
import sys
import json
import time
import random
import hashlib
import requests
from urllib.parse import urlparse, urljoin
from jobspy import scrape_jobs

# Local Database Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_DIR = os.path.join(BASE_DIR, "database")

# Load Environment Parameters
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Playwright setup verification
PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    print("[WARNING] Playwright library not found. Falling back to API-only scraping modes.")

# Setup User-Agent header for HTTP requests
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def generate_job_id(title, company):
    """Generate a consistent primary key for spreadsheet row tracking."""
    raw_str = f"{title.strip().lower()}|{company.strip().lower()}"
    return hashlib.md5(raw_str.encode("utf-8")).hexdigest()

def clean_url(url):
    """Sanitize and extract raw URLs from markdown link patterns [text](url)."""
    url = url.strip()
    match = re.match(r"^\[.*\]\((https?://[^\s)]+)\)$", url)
    if match:
        return match.group(1)
    return url

def fetch_sources_from_db():
    """Retrieve the list of target companies and configurations from local JSON database."""
    print("[DB] Fetching local scraper sources...")
    sources_file = os.path.join(DATABASE_DIR, "sources.json")
    try:
        if os.path.exists(sources_file):
            with open(sources_file, "r", encoding="utf-8") as f:
                return json.load(f)
        print(f"[DB] sources.json not found at {sources_file}")
    except Exception as e:
        print(f"[DB] Error reading local sources: {e}")
    return []

def fetch_profiles_from_db():
    """Retrieve demographic and resume profiles from local JSON database."""
    print("[DB] Fetching local candidate profiles...")
    profiles_file = os.path.join(DATABASE_DIR, "profiles.json")
    try:
        if os.path.exists(profiles_file):
            with open(profiles_file, "r", encoding="utf-8") as f:
                return json.load(f)
        print(f"[DB] profiles.json not found at {profiles_file}")
    except Exception as e:
        print(f"[DB] Error reading local profiles: {e}")
    return {}

def scrape_greenhouse(company_url):
    """Scrape Greenhouse board using its fast public JSON API, avoiding DOM rendering."""
    print(f"[Scraper] Querying Greenhouse API for: {company_url}")
    parsed = urlparse(company_url)
    # Extracts company name from greenhouse.io/companyName
    path_parts = [p for p in parsed.path.split('/') if p]
    if not path_parts:
        return []
    company_name = path_parts[0]
    
    api_url = f"https://boards-api.greenhouse.io/v1/boards/{company_name}/jobs?content=true"
    try:
        res = requests.get(api_url, headers=HEADERS, timeout=15)
        if res.status_code == 200:
            data = res.json()
            jobs = []
            for item in data.get("jobs", []):
                jobs.append({
                    "title": item.get("title", ""),
                    "organization": company_name.capitalize(),
                    "url": item.get("absolute_url", ""),
                    "location": item.get("location", {}).get("name", "Remote"),
                    "description": item.get("content", "")
                })
            return jobs
    except Exception as e:
        print(f"[Scraper] Greenhouse API failed for {company_name}: {e}")
    return []

def scrape_lever(company_url):
    """Scrape Lever board using its public JSON API endpoint."""
    print(f"[Scraper] Querying Lever API for: {company_url}")
    parsed = urlparse(company_url)
    path_parts = [p for p in parsed.path.split('/') if p]
    if not path_parts:
        return []
    company_name = path_parts[0]
    
    api_url = f"https://api.lever.co/v0/postings/{company_name}"
    try:
        res = requests.get(api_url, headers=HEADERS, timeout=15)
        if res.status_code == 200:
            data = res.json()
            jobs = []
            for item in data:
                jobs.append({
                    "title": item.get("title", ""),
                    "organization": company_name.capitalize(),
                    "url": item.get("hostedUrl", ""),
                    "location": item.get("categories", {}).get("location", "Remote"),
                    "description": item.get("description", "") + "\n" + item.get("lists", [{}])[0].get("content", "")
                })
            return jobs
    except Exception as e:
        print(f"[Scraper] Lever API failed for {company_name}: {e}")
    return []

def scrape_workday(company_url):
    """
    Direct API requests targeting Workday internal search JSON endpoints.
    Bypasses headless Playwright scrolling by communicating directly with Workday's client API.
    """
    print(f"[Scraper] Querying Workday Client API for: {company_url}")
    try:
        parsed = urlparse(company_url)
        # Matches tenant and site from subdomain and paths
        # Format: tenant.wd5.myworkdayjobs.com/SiteName
        tenant = parsed.hostname.split('.')[0]
        path_parts = [p for p in parsed.path.split('/') if p]
        site_name = path_parts[0] if path_parts else "External"
        
        api_url = f"https://{parsed.hostname}/wday/cxs/{tenant}/{site_name}/jobs"
        payload = {
            "appliedFacets": {},
            "limit": 30,
            "offset": 0,
            "searchText": ""
        }
        res = requests.post(api_url, headers=HEADERS, json=payload, timeout=15)
        if res.status_code == 200:
            data = res.json()
            jobs = []
            for item in data.get("jobPostings", []):
                # Retrieve individual description
                job_path = item.get("externalPath", "")
                full_url = f"https://{parsed.hostname}{parsed.path}{job_path}"
                jobs.append({
                    "title": item.get("title", ""),
                    "organization": tenant.capitalize(),
                    "url": full_url,
                    "location": item.get("locationsText", "Remote/US"),
                    "description": "" # Fetched lazily or scored on details
                })
            return jobs
    except Exception as e:
        print(f"[Scraper] Workday API failed for {company_url}: {e}")
    return []

def scrape_weworkremotely(feed_url):
    """Parse We Work Remotely public RSS feed XML."""
    print(f"[Scraper] Fetching We Work Remotely RSS: {feed_url}")
    jobs = []
    try:
        res = requests.get(feed_url, headers=HEADERS, timeout=15)
        if res.status_code == 200:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(res.content)
            channel = root.find("channel")
            items = channel.findall("item") if channel is not None else []
            for item in items:
                title_text = item.find("title").text or ""
                link_text = item.find("link").text or ""
                desc_text = item.find("description").text or ""
                
                # WWR title format is usually: "CompanyName: JobTitle"
                company = "Unknown"
                title = title_text
                if ":" in title_text:
                    parts = title_text.split(":", 1)
                    company = parts[0].strip()
                    title = parts[1].strip()
                
                jobs.append({
                    "title": title,
                    "organization": company,
                    "url": link_text,
                    "location": "Remote",
                    "description": desc_text
                })
    except Exception as e:
        print(f"[Scraper] We Work Remotely RSS failed: {e}")
    return jobs

def scrape_himalayas(api_url):
    """Fetch job postings from Himalayas JSON API."""
    print(f"[Scraper] Querying Himalayas API: {api_url}")
    jobs = []
    try:
        res = requests.get(api_url, headers=HEADERS, timeout=15)
        if res.status_code == 200:
            data = res.json()
            for item in data.get("jobs", []):
                title = item.get("title", "")
                company = item.get("companyName", "Unknown")
                url = item.get("applicationLink", "")
                desc = item.get("description", "")
                
                # Check location restrictions (must be US-friendly)
                loc_restrictions = item.get("locationRestrictions", [])
                is_us_eligible = not loc_restrictions or any(
                    x.lower() in ["united states", "us", "usa", "worldwide", "north america"]
                    for x in loc_restrictions
                )
                
                if not is_us_eligible:
                    continue
                
                jobs.append({
                    "title": title,
                    "organization": company,
                    "url": url,
                    "location": "Remote",
                    "description": desc
                })
    except Exception as e:
        print(f"[Scraper] Himalayas API failed: {e}")
    return jobs

def scrape_playwright_fallback(company_url, keywords):
    """Headless Playwright Viewport Scroll fallback loop for custom/unrecognized portals."""
    if not PLAYWRIGHT_AVAILABLE:
        print(f"[Scraper] Playwright fallback unavailable for: {company_url}")
        return []
    
    print(f"[Scraper] Launching Playwright browser scroll loop for: {company_url}")
    jobs = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=HEADERS["User-Agent"])
            page.goto(company_url, timeout=45000)
            page.wait_for_load_state("networkidle")
            
            # Viewport scroll loop to force lazy loaders (like Workday listings pages) to render rows
            last_height = page.evaluate("document.body.scrollHeight")
            max_scrolls = 6
            for scroll in range(max_scrolls):
                # Increment scroll tick
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(random.uniform(1.0, 2.0)) # Humon-like delay
                
                new_height = page.evaluate("document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height
            
            # Extract potential job links containing keywords
            links = page.locator("a").all()
            print(f"[Scraper] Found {len(links)} total 'a' elements on page.")
            found_urls = set()
            sample_count = 0
            for link in links:
                href = link.get_attribute("href")
                text = link.inner_text()
                if href:
                    # Resolve relative URLs
                    full_href = urljoin(company_url, href)
                    if full_href not in found_urls:
                        if sample_count < 10:
                            print(f"  [DEBUG LINK] Text: '{text.strip().replace(chr(10), ' ')[:60]}', Href: '{href[:80]}', Resolved: '{full_href[:80]}'")
                            sample_count += 1
                        # Heuristic keyword match on anchor text
                        if any(k.lower() in text.lower() for k in keywords):
                            found_urls.add(full_href)
                            jobs.append({
                                "title": text.strip().split("\n")[0],
                                "organization": urlparse(company_url).hostname.split('.')[1].capitalize(),
                                "url": full_href,
                                "location": "Remote",
                                "description": text
                            })
            browser.close()
    except Exception as e:
        print(f"[Scraper] Playwright execution failed: {e}")
    return jobs

def local_pre_filter(jobs, keywords, excludes):
    """
    Tier 1 High-Speed Pre-Filter.
    Filters raw jobs locally in memory using fast keyword/regex rules.
    """
    qualified = []
    keyword_patterns = [re.compile(rf"\b{re.escape(k.strip())}\b", re.IGNORECASE) for k in keywords if k.strip()]
    exclude_patterns = [re.compile(rf"\b{re.escape(ex.strip())}\b", re.IGNORECASE) for ex in excludes if ex.strip()]
    
    # Notorious Staffing/Consulting Mega-Agencies
    agency_blacklist = [
        "teksystems", "insight global", "apex systems", "randstad", "robert half", 
        "revature", "bairesdev", "cybercoders", "infotree", "kforce", "tata consultancy", 
        "tcs", "cognizant", "infosys", "wipro", "hcl", "synergis", "collabera", "modis",
        "adecco", "manpower", "aerotek", "actalent", "judge group"
    ]
    
    for job in jobs:
        title = job["title"]
        org = job.get("organization", "").lower()
        
        # Agency Pre-filter
        if any(agency in org for agency in agency_blacklist):
            continue
        
        # Exclude patterns
        if any(pat.search(title) for pat in exclude_patterns):
            continue
            
        # Keyword patterns (if defined, at least one must match)
        if keyword_patterns:
            if not any(pat.search(title) for pat in keyword_patterns):
                continue
                
        # "Florida Iron Curtain" geographic pre-filters (must be Remote or in Florida)
        location = job.get("location", "").lower()
        is_remote = "remote" in location or "virtual" in location or "work from home" in location
        is_florida = re.search(r'\bfl\b', location) or "florida" in location
        
        if not is_remote and not is_florida:
            continue
            
        qualified.append(job)
    return qualified

def evaluate_jobs_batch(jobs_batch, profiles, api_key):
    """
    Phase 1: The Gatekeeper.
    Batches up to 15 job listings into a single Gemini JSON schema request.
    """
    def heuristic_fallback(jobs):
        print("[Gatekeeper] Using heuristic fallback for evaluation...")
        evals = []
        for i, job in enumerate(jobs):
            title = job.get("title", "").lower()
            location = job.get("location", "").lower()
            
            best_match = "None"
            score = 0
            reasoning = "Failed to match"
            
            if any(k in title for k in ["data", "bi", "business intelligence", "qa", "automation"]):
                best_match = "Greg"
                score = 85
                reasoning = "Heuristic match for Greg"
            elif any(k in title for k in ["project manager", "scrum", "agile", "tpm"]):
                best_match = "Rachel"
                score = 85
                reasoning = "Heuristic match for Rachel"
            elif any(k in title for k in ["merchandising", "retail", "property", "store"]):
                best_match = "Lorena"
                score = 85
                reasoning = "Heuristic match for Lorena"
                
            # Constraints
            if best_match == "Rachel":
                if "toronto" in location or "arlington" in location:
                    best_match = "None"
                    score = 0
                    reasoning = "Rachel constraint: no Toronto or Arlington."
                    
            evals.append({
                "temp_id": str(i),
                "best_match_candidate": best_match,
                "compatibility_score": score,
                "reasoning": reasoning
            })
        return evals

    if not api_key:
        print("[WARNING] No GEMINI_API_KEY set. Falling back to heuristic.")
        return heuristic_fallback(jobs_batch)
        
    print(f"[Gemini API] Evaluating batch of {len(jobs_batch)} jobs...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    
    # Construct clean structured candidates summary
    candidates_summary = ""
    for name, prof in profiles.items():
        candidates_summary += f"CANDIDATE: {name}\nResume Gist: {prof.get('summary', '')}\nCompetencies: {prof.get('coreCompetencies', '')}\nSponsorship Needed: {prof.get('requiresSponsor', 'No')}\n---\n"
        
    # Formulate listing bundle
    job_listings_text = ""
    for idx, job in enumerate(jobs_batch):
        job_listings_text += f"JOB INDEX: {idx}\nTitle: {job['title']}\nOrg: {job['organization']}\nLocation: {job['location']}\nDescription snippet: {job.get('description', '')[:1000]}\n---\n"
        
    system_prompt = (
        "You are an elite, objective recruiter. Compare the given JOB INDEX listings against the CANDIDATE profiles. "
        "Determine compatibility. Rules:\n"
        "1. A candidate is compatible ONLY if they match the core skills and domain context.\n"
        "2. Score compatibility from 0 to 100.\n"
        "3. Assign the candidate name to best_match_candidate ('Greg', 'Rachel', 'Lorena', or 'None').\n"
        "4. If the job description indicates the employer is a staffing agency, consulting firm, or recruiting firm hiring on behalf of a third-party client (e.g. 'our client is looking for...'), you MUST assign the best_match_candidate to 'None' and score it 0.\n"
        "Return a JSON object containing the array of evaluations."
    )
    
    user_prompt = f"CANDIDATES PROFILE DETAILS:\n{candidates_summary}\n\nJOB LISTINGS TO SCORE:\n{job_listings_text}"
    
    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": user_prompt}]}
        ],
        "systemInstruction": {
            "parts": [{"text": system_prompt}]
        },
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "evaluations": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "temp_id": { "type": "STRING", "description": "The INDEX string of the evaluated job (e.g. '0', '1', etc.)" },
                                "best_match_candidate": { "type": "STRING", "description": "Must be 'Greg', 'Rachel', 'Lorena', or 'None'" },
                                "compatibility_score": { "type": "INTEGER" },
                                "reasoning": { "type": "STRING" }
                            },
                            "required": ["temp_id", "best_match_candidate", "compatibility_score", "reasoning"]
                        }
                    }
                }
            },
            "temperature": 0.1
        }
    }
    
    try:
        res = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=30)
        if res.status_code == 200:
            res_json = res.json()
            raw_text = res_json["candidates"][0]["content"]["parts"][0]["text"]
            eval_data = json.loads(raw_text)
            return eval_data.get("evaluations", [])
        else:
            print(f"[Gemini API] HTTP Error: {res.status_code} - {res.text}")
            return heuristic_fallback(jobs_batch)
    except Exception as e:
        print(f"[Gemini API] Evaluation error: {e}")
        return heuristic_fallback(jobs_batch)
        
    return heuristic_fallback(jobs_batch)

def group_candidate_criteria(sources):
    """Group all target keywords and exclude keywords from sources by Sector Tag."""
    candidate_keywords = {"Greg": set(), "Rachel": set(), "Lorena": set()}
    candidate_excludes = {"Greg": set(), "Rachel": set(), "Lorena": set()}
    for src in sources:
        tag = src.get("Sector Tag")
        if tag in candidate_keywords:
            kw_str = src.get("Target Keywords") or ""
            ex_str = src.get("Exclude Keywords") or ""
            for k in kw_str.split(","):
                if k.strip():
                    candidate_keywords[tag].add(k.strip().lower())
            for ex in ex_str.split(","):
                if ex.strip():
                    candidate_excludes[tag].add(ex.strip().lower())
    return candidate_keywords, candidate_excludes

def main():
    print("====================================================")
    print("STARTING AUTONOMOUS JOB PIPELINE SCRAPER RUN")
    print("====================================================")
    
    # 1. Fetch parameters
    sources = fetch_sources_from_db()
    profiles = fetch_profiles_from_db()
    
    if not sources:
        print("[ERROR] No target sources retrieved from the database. Exiting.")
        sys.exit(1)
        
    print(f"[DB] Retrieved {len(sources)} scraping target sources.")
    
    scraped_jobs = []
    
    # Build candidate-specific keywords and excludes from sources.json
    candidate_keywords, candidate_excludes = group_candidate_criteria(sources)
    
    # Combined keywords/excludes for unified remote boards
    all_kws = set()
    all_exs = set()
    for cand in ["Greg", "Rachel", "Lorena"]:
        all_kws.update(candidate_keywords.get(cand, []))
        all_exs.update(candidate_excludes.get(cand, []))
    
    # 2. Phase 0: Sourcing
    for src in sources:
        url = src.get("url") or src.get("URL") or ""
        url = clean_url(url)
        org = src.get("org") or src.get("Organization") or src.get("organization") or "Unknown"
        keywords_str = src.get("keywords") or src.get("Target Keywords") or src.get("keywords") or ""
        excludes_str = src.get("excludes") or src.get("Exclude Keywords") or src.get("excludes") or ""
        
        keywords = [k.strip() for k in keywords_str.split(",") if k.strip()]
        excludes = [ex.strip() for ex in excludes_str.split(",") if ex.strip()]
        
        # If it is a unified remote board, use combined keywords/excludes to pre-filter
        is_unified = "weworkremotely.com" in url or "himalayas.app" in url
        if is_unified:
            keywords = list(all_kws)
            excludes = list(all_exs)
        
        if not url or url == "#":
            continue
            
        print(f"\n[Sourcing] Processing company: {org} ({url})")
        
        # Hybrid Loader checks
        raw_list = []
        if "weworkremotely.com" in url:
            raw_list = scrape_weworkremotely(url)
        elif "himalayas.app" in url:
            raw_list = scrape_himalayas(url)
        elif "greenhouse.io" in url:
            raw_list = scrape_greenhouse(url)
        elif "lever.co" in url:
            raw_list = scrape_lever(url)
        elif "myworkdayjobs.com" in url:
            raw_list = scrape_workday(url)
        else:
            # Fallback to browser scroll loop if Playwright is available
            raw_list = scrape_playwright_fallback(url, keywords or ["software", "manager", "education"])
            
        print(f"[Sourcing] Harvested {len(raw_list)} raw job listings.")
        
        # Apply local pre-filtering
        filtered = local_pre_filter(raw_list, keywords, excludes)
        print(f"[Sourcing] Passed Tier 1 local filter: {len(filtered)} / {len(raw_list)} jobs.")
        scraped_jobs.extend(filtered)
        
    # 2b. Sourcing via JobSpy
    print("\n[Sourcing] Starting JobSpy search queries...")
    jobspy_raw_jobs = []
    
    # Define optimized search terms for each candidate to avoid rate limiting
    jobspy_search_terms = {
        "Greg": ["Data Analyst", "Business Intelligence", "QA Automation Engineer"],
        "Rachel": ["Program Manager", "Project Manager", "Process Improvement Manager"],
        "Lorena": ["Visual Merchandising Manager", "Retail Operations Manager", "Property Manager"]
    }

    jobspy_locations = {
        "Greg": ["Florida", "Remote"],
        "Rachel": ["Orlando, FL"],
        "Lorena": ["Florida"]
    }
                    
    # Perform JobSpy searches
    for candidate, terms in jobspy_search_terms.items():
        print(f"\n[JobSpy] Sourcing jobs for candidate: {candidate}")
        kws = list(candidate_keywords[candidate])
        exs = list(candidate_excludes[candidate])
        
        # Target locations
        locations = jobspy_locations.get(candidate, ["Florida"])
        for loc in locations:
            for term in terms:
                print(f"  Querying: '{term}' in '{loc}'...")
                try:
                    # Limit results to 15 per query, past 7 days (168 hours)
                    jobs_df = scrape_jobs(
                        site_name=["indeed", "linkedin"],
                        search_term=term,
                        location=loc,
                        results_wanted=15,
                        hours_old=168,
                        country_indeed="USA",
                        job_type="fulltime"
                    )
                    
                    if jobs_df is not None and not jobs_df.empty:
                        print(f"  [JobSpy] Found {len(jobs_df)} raw listings.")
                        for _, row in jobs_df.iterrows():
                            title = str(row.get("title", "")).strip()
                            company = str(row.get("company", "")).strip()
                            url = str(row.get("job_url", "")).strip()
                            location_str = str(row.get("location", "")).strip()
                            desc = str(row.get("description", "")).strip()
                            is_remote = bool(row.get("is_remote", False))
                            
                            if not title or not url:
                                continue
                                
                            if not location_str:
                                location_str = "Remote" if is_remote else "Florida"
                                
                            jobspy_raw_jobs.append({
                                "title": title,
                                "organization": company if company else "Unknown",
                                "url": url,
                                "location": location_str,
                                "description": desc,
                                "candidate_hint": candidate  # keep track of who we searched this for
                            })
                    else:
                        print("  [JobSpy] No jobs returned.")
                except Exception as e:
                    print(f"  [JobSpy] Query failed for '{term}' in '{loc}': {e}")
                    
                # Sleep to avoid rate limiting
                time.sleep(random.uniform(2.0, 4.0))
                
    print(f"\n[JobSpy] Total jobs harvested: {len(jobspy_raw_jobs)}")
    
    # Filter JobSpy jobs using candidates' combined criteria
    filtered_jobspy_jobs = []
    for job in jobspy_raw_jobs:
        candidate = job["candidate_hint"]
        kws = list(candidate_keywords[candidate])
        exs = list(candidate_excludes[candidate])
        
        # Apply local pre-filter criteria
        passed = local_pre_filter([job], kws, exs)
        if passed:
            # Remove candidate hint before adding to global list
            job_clean = job.copy()
            del job_clean["candidate_hint"]
            filtered_jobspy_jobs.append(job_clean)
            
    print(f"[JobSpy] Passed Tier 1 local filter: {len(filtered_jobspy_jobs)} / {len(jobspy_raw_jobs)} jobs.")
    scraped_jobs.extend(filtered_jobspy_jobs)
        
    if not scraped_jobs:
        print("\n[Scraper] No jobs passed local pre-filters. Run complete.")
        sys.exit(0)
        
    # Filter out already existing jobs
    jobs_file = os.path.join(DATABASE_DIR, "jobs.json")
    existing_job_ids = set()
    try:
        if os.path.exists(jobs_file):
            with open(jobs_file, "r", encoding="utf-8") as f:
                jobs_data = json.load(f)
                existing_job_ids = {j.get("id") for j in jobs_data if j.get("id")}
    except Exception as e:
        print(f"[DB] Error loading existing jobs: {e}")
        
    filtered_new_jobs = []
    for job in scraped_jobs:
        job_id = generate_job_id(job["title"], job["organization"])
        if job_id not in existing_job_ids:
            filtered_new_jobs.append(job)
            
    print(f"[Scraper] Filtered out {len(scraped_jobs) - len(filtered_new_jobs)} existing jobs.")
    scraped_jobs = filtered_new_jobs
    
    if not scraped_jobs:
        print("\n[Scraper] No new jobs to score. Run complete.")
        sys.exit(0)
        
    print(f"\n[Scraper] Total jobs needing semantic scoring: {len(scraped_jobs)}")
    
    # 3. Phase 1: The Gatekeeper (Batched semantic matching)
    batch_size = 12
    scored_jobs = []
    
    for i in range(0, len(scraped_jobs), batch_size):
        batch = scraped_jobs[i:i+batch_size]
        evals = evaluate_jobs_batch(batch, profiles, GEMINI_API_KEY)
        
        # Map evaluations back to jobs
        for ev in evals:
            try:
                idx = int(ev.get("temp_id", -1))
                if 0 <= idx < len(batch):
                    job = batch[idx]
                    score = ev.get("compatibility_score", 0)
                    candidate = ev.get("best_match_candidate", "None")
                    
                    if score >= 80 and candidate != "None":
                        # Set schema parameters
                        job_id = generate_job_id(job["title"], job["organization"])
                        scored_jobs.append({
                            "id": job_id,
                            "title": job["title"],
                            "organization": job["organization"],
                            "url": job["url"],
                            "location": job["location"],
                            "description": job.get("description", "")[:4000],
                            "type": candidate,  # Matches the compatible candidate name
                            "source": "Python Agent",
                            "userStatus": "Queued",  # Moves directly into candidate application queue
                            "postDate": time.strftime("%Y-%m-%d"),
                            "compatibilityScore": score
                        })
            except Exception as e:
                print(f"[Gatekeeper] Error matching batch item: {e}")
                
    print(f"\n[Gatekeeper] Passed compatibility threshold (>=80%): {len(scored_jobs)} jobs.")
    
    # 4. Save results to local JSON database
    if scored_jobs:
        print(f"\n[DB] Committing {len(scored_jobs)} qualified jobs to local database...")
        jobs_file = os.path.join(DATABASE_DIR, "jobs.json")
        try:
            if os.path.exists(jobs_file):
                with open(jobs_file, "r", encoding="utf-8") as f:
                    jobs_data = json.load(f)
            else:
                jobs_data = []

            jobs_map = {job["id"]: job for job in jobs_data if "id" in job}
            updated_count = 0
            appended_count = 0

            for job in scored_jobs:
                job_id = job.get("id")
                if not job_id:
                    continue

                if job_id in jobs_map:
                    # Update existing job, but preserve userStatus if not explicitly updated
                    existing_job = jobs_map[job_id]
                    user_status = job.get("userStatus") or existing_job.get("userStatus") or ""
                    existing_job.update(job)
                    existing_job["userStatus"] = user_status
                    updated_count += 1
                else:
                    # Append new job
                    jobs_data.append(job)
                    jobs_map[job_id] = job
                    appended_count += 1

            with open(jobs_file, "w", encoding="utf-8") as f:
                json.dump(jobs_data, f, indent=2)

            print(f"[DB] Local update complete: {updated_count} updated, {appended_count} appended.")
        except Exception as e:
            print(f"[DB] Error writing to local jobs database: {e}")
    else:
        print("\n[Scraper] No qualified jobs to save.")

    print("\n====================================================")
    print("RUN COMPLETED SUCCESSFULLY")
    print("====================================================")

if __name__ == "__main__":
    main()
