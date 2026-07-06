import sys
import json
import time
import os
import re
from playwright.sync_api import sync_playwright

try:
    import google.generativeai as genai
except ImportError:
    print("google-generativeai not found. Please pip install google-generativeai")
    sys.exit(1)

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

def update_job_status(job_url, screenshot_path):
    try:
        jobs_path = 'database/jobs.json'
        with open(jobs_path, 'r') as f:
            jobs = json.load(f)
            
        for job in jobs:
            if job.get("url") == job_url or job_url in job.get("url", ""):
                job["userStatus"] = "Applied"
                job["appliedDate"] = time.strftime("%Y-%m-%d")
                job["screenshotPath"] = screenshot_path
                break
                
        with open(jobs_path, 'w') as f:
            json.dump(jobs, f, indent=2)
        print("✅ jobs.json database updated with Applied status.")
    except Exception as e:
        print(f"Failed to update jobs.json: {e}")

def generate_documents(candidate_name, profile, job_description):
    print("🧠 Generating Tailored Resume and Cover Letter via Gemini...")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("❌ ERROR: GEMINI_API_KEY environment variable not set.")
        sys.exit(1)
        
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    prompt = f"""
    You are a Senior Technical Recruiter and ATS Expert. Your job is to rewrite a resume to achieve a 100% match score for a specific job, while keeping the candidate's core truth intact.
    
    TASK: Write a highly tailored Resume and Cover Letter for {candidate_name}.
    
    CRITICAL RECRUITER INSTRUCTIONS:
    1. AGGRESSIVELY REWRITE bullet points to inject the exact keywords, tools, and methodologies mentioned in the Job Description. DO NOT just copy the old resume.
    2. QUANTIFY achievements (e.g., "Increased X by Y%", "Managed budget of $Z"). If exact numbers aren't in the profile, use realistic generic business metrics that match their seniority.
    3. Output ONLY valid HTML. DO NOT output markdown. DO NOT use ```html codeblocks. Just raw HTML.
    4. ATS-OPTIMIZED DESIGN: Use an ultra-clean, minimalist Harvard-style format. NO tables, NO columns. Use standard fonts (Arial/Helvetica). Use standard semantic tags (<h1>, <h2>, <ul>, <li>).
    5. The Resume MUST be wrapped entirely inside a <div id="resume">.
    6. The Cover Letter MUST be wrapped entirely inside a <div id="cover_letter">.
    7. Ensure the cover letter is highly persuasive, mapping the candidate's unique background directly to the company's specific needs in the JD.
    
    CANDIDATE PROFILE:
    {json.dumps(profile)}
    
    JOB DESCRIPTION:
    {job_description[:5000]}
    """
    
    res = model.generate_content(prompt)
    html_raw = res.text
    # Clean up markdown code blocks if gemini disobeys
    html_raw = re.sub(r'^```html', '', html_raw, flags=re.MULTILINE)
    html_raw = re.sub(r'^```', '', html_raw, flags=re.MULTILINE).strip()
    return html_raw

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
        is_ci = os.environ.get("CI", "false").lower() == "true"
        browser = p.chromium.launch(headless=is_ci, slow_mo=50)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800}
        )
        page = context.new_page()

        try:
            print("Navigating to application page...")
            page.goto(job_url, wait_until="networkidle")
            time.sleep(2)
            
            # Scrape Job Description for Tailoring
            print("📖 Scraping Job Description...")
            job_description = page.inner_text("body")
            
            # Generate PDFs in the background using a hidden page
            html_content = generate_documents(candidate_name, profile, job_description)
            pdf_page = context.new_page()
            pdf_page.set_content(html_content)
            
            print("🖨️  Printing Tailored Resume to PDF...")
            pdf_page.add_style_tag(content="#cover_letter { display: none !important; } #resume { display: block !important; }")
            pdf_page.pdf(path="tailored_resume.pdf", format="Letter", margin={"top": "0.5in", "bottom": "0.5in", "left": "0.5in", "right": "0.5in"})
            
            print("🖨️  Printing Tailored Cover Letter to PDF...")
            pdf_page.set_content(html_content) # reset
            pdf_page.add_style_tag(content="#resume { display: none !important; } #cover_letter { display: block !important; }")
            pdf_page.pdf(path="cover_letter.pdf", format="Letter", margin={"top": "0.5in", "bottom": "0.5in", "left": "0.5in", "right": "0.5in"})
            
            pdf_page.close()

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
                    
                    # File Uploads
                    print("📎 Attaching Resume and Cover Letter PDFs...")
                    resume_input = page.locator("input[type='file']").first
                    if resume_input.is_visible():
                        resume_input.set_input_files("tailored_resume.pdf")
                    
                    # Greenhouse usually has multiple file inputs. We try to find the cover letter one.
                    inputs = page.locator("input[type='file']")
                    if inputs.count() > 1:
                        inputs.nth(1).set_input_files("cover_letter.pdf")

                    print("\n🎉 Core fields injected successfully!")
                    
                    if "--autonomous" in sys.argv:
                        print("🚀 AUTONOMOUS MODE: Submitting Application...")
                        submit_btn = page.locator("button[id='submit_app'], input[id='submit_app']").first
                        if submit_btn.is_visible():
                            submit_btn.click()
                            print("Waiting for submission confirmation...")
                            time.sleep(5) # Wait for network
                            
                            os.makedirs("database/screenshots", exist_ok=True)
                            job_id = str(hash(job_url))[1:10]
                            screenshot_path = f"database/screenshots/proof_{job_id}.png"
                            page.screenshot(path=screenshot_path, full_page=True)
                            print(f"📸 Autonomous Submission Complete. Screenshot saved to: {screenshot_path}")
                            
                            update_job_status(job_url, screenshot_path)
                        else:
                            print("Submit button not found.")
                    else:
                        print("⚠️ Pausing Playwright. Please manually click 'Submit'!")
                        page.pause()
                except Exception as e:
                    print(f"Minor error filling form: {e}")
                    if "--autonomous" not in sys.argv: page.pause()
                    
            elif "lever.co" in page.url:
                print("Lever ATS Detected! (Auto-fill experimental).")
                if "--autonomous" not in sys.argv: page.pause()
            else:
                print("Unknown ATS or generic job board. Please fill out manually.")
                if "--autonomous" not in sys.argv: page.pause()

        except Exception as e:
            print(f"Critical Error: {e}")
            if "--autonomous" not in sys.argv: page.pause()

        finally:
            browser.close()
            print("Browser closed.")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python auto_apply.py <JOB_URL> <CANDIDATE_NAME> [--autonomous]")
        sys.exit(1)
        
    url = sys.argv[1]
    name = sys.argv[2]
    auto_apply(url, name)
