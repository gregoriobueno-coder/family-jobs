import sys
import json
import time
from playwright.sync_api import sync_playwright

def load_profile(name):
    try:
        with open('database/profiles.json', 'r') as f:
            data = json.load(f)
            if "profiles" in data:
                return data["profiles"].get(name)
            return data.get(name)
    except Exception as e:
        print(f"Failed to load profiles.json: {e}")
        return None

def auto_apply(job_url, candidate_name):
    profile = load_profile(candidate_name)
    if not profile:
        print(f"Error: Profile for '{candidate_name}' not found. Ensure database/profiles.json exists.")
        return

    print(f"==================================================")
    print(f"🤖 Autonomous Job Application Runner")
    print(f"Candidate: {candidate_name}")
    print(f"Target: {job_url}")
    print(f"==================================================")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=50)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800}
        )
        page = context.new_page()

        try:
            print("Navigating to application page...")
            page.goto(job_url, wait_until="networkidle")
            time.sleep(2)

            if "greenhouse.io" in page.url or "boards.greenhouse.io" in page.url:
                print("✅ Greenhouse ATS Detected! Commencing data injection...")
                
                try:
                    if page.locator("input[id='first_name']").is_visible():
                        page.locator("input[id='first_name']").fill(candidate_name)
                    if page.locator("input[id='last_name']").is_visible():
                        page.locator("input[id='last_name']").fill(profile.get("lastName", "Bueno"))
                    if page.locator("input[id='email']").is_visible():
                        page.locator("input[id='email']").fill(profile.get("email", f"{candidate_name.lower()}.bueno@gmail.com"))
                    if page.locator("input[id='phone']").is_visible():
                        page.locator("input[id='phone']").fill(profile.get("phone", "(555) 555-5555"))
                    
                    linkedin_fields = page.locator("input[type='text']")
                    for i in range(linkedin_fields.count()):
                        placeholder = linkedin_fields.nth(i).get_attribute("placeholder") or ""
                        if "linkedin" in placeholder.lower():
                            linkedin_fields.nth(i).fill(profile.get("linkedIn", ""))
                            break
                            
                    print("\n🎉 Core fields injected successfully!")
                    print("⚠️ Pausing Playwright. Please manually upload the tailored Resume PDF and click 'Submit'!")
                except Exception as e:
                    print(f"Minor error filling form: {e}")
                    
                page.pause()
            elif "lever.co" in page.url:
                print("Lever ATS Detected! (Auto-fill experimental).")
                page.pause()
            else:
                print("Unknown ATS or generic job board. Please fill out manually.")
                page.pause()

        except Exception as e:
            print(f"Critical Error: {e}")
            page.pause()

        finally:
            browser.close()
            print("Browser closed.")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python auto_apply.py <JOB_URL> <CANDIDATE_NAME>")
        sys.exit(1)
        
    url = sys.argv[1]
    name = sys.argv[2]
    auto_apply(url, name)
