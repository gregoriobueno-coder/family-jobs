import json
import time
from playwright.sync_api import sync_playwright

def load_jobs():
    with open('database/jobs.json', 'r') as f:
        return json.load(f)

def save_jobs(jobs):
    with open('database/jobs.json', 'w') as f:
        json.dump(jobs, f, indent=2)

def check_expired():
    jobs = load_jobs()
    print(f"Checking {len(jobs)} jobs for expiration...")
    
    active_jobs = []
    expired_count = 0
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        for idx, job in enumerate(jobs):
            url = job.get('url', '')
            
            # For now we only check indeed jobs that the user hasn't explicitly applied to
            if 'indeed.com' in url and job.get('userStatus') != 'Applied':
                print(f"[{idx}/{len(jobs)}] Checking: {job['title'][:30]}...")
                try:
                    page.goto(url, wait_until='domcontentloaded', timeout=15000)
                    time.sleep(1) # wait for redirect or text to load
                    
                    content = page.content().lower()
                    if "this job has expired" in content or "no longer available" in content or "job does not exist" in content or page.url.endswith("expired"):
                        print("  ❌ EXPIRED! Removing...")
                        expired_count += 1
                        continue # Skip appending to active_jobs
                    else:
                        print("  ✅ Active.")
                except Exception as e:
                    print(f"  ⚠️ Error checking {url}: {e}")
            
            active_jobs.append(job)
            
        browser.close()
        
    if expired_count > 0:
        save_jobs(active_jobs)
        print(f"\nCleanup complete. Removed {expired_count} expired jobs.")
    else:
        print("\nCleanup complete. No expired jobs found.")

if __name__ == "__main__":
    check_expired()
