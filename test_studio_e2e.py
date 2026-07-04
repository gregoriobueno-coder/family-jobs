#!/usr/bin/env python3
"""
Full end-to-end test that replicates EXACTLY what the browser sends
when clicking Tailor Resume, Cover Letter, and Analyze Fit.
Tests the live Vercel production endpoint.
"""
import urllib.request
import urllib.parse
import json
import sys

PROD_URL = "https://rachels-tracker.vercel.app/api"

FAKE_RESUME = """# RACHEL BUENO
Orlando, FL | (407) 555-1234 | rachel.bueno@email.com | linkedin.com/in/rachel

## EXPERIENCE
**Acme Corp**, Orlando, FL
*Senior Marketing Manager*, Jan 2022 – Present
- Spearheaded digital marketing campaigns generating $2.4M in pipeline revenue across 3 product lines
- Orchestrated cross-functional team of 8 to launch product rebrand, achieving 34% increase in brand awareness
- Analyzed A/B test results across 200+ email variants, improving open rates from 18% to 31%

**Beta Inc**, Miami, FL
*Marketing Specialist*, Jun 2019 – Dec 2021
- Managed $500K annual ad budget across Google, Meta, and LinkedIn channels with 4.2x ROAS
- Collaborated with sales team on ABM strategy targeting Fortune 500 accounts, closing 12 enterprise deals

## EDUCATION
**University of Florida**, Gainesville, FL
Bachelor of Science in Marketing, May 2019

## SKILLS & INTERESTS
Email Marketing, HubSpot, Salesforce, SEO/SEM, Google Analytics, Content Strategy, Project Management"""

FAKE_JD = """TARGET ROLE: Director of Marketing
ORGANIZATION: TechCorp Solutions
URL: https://example.com/job/director-marketing

--- EXTRACTED TEXT ---
We are seeking a Director of Marketing to lead our B2B marketing function.

Responsibilities:
- Lead a team of 5-10 marketers across demand gen, content, and brand
- Own the marketing budget of $2M+ and optimize for pipeline contribution
- Develop and execute integrated campaigns across digital, events, and ABM
- Partner closely with Sales to define ICP and improve lead quality
- Report weekly on pipeline metrics, MQLs, and campaign ROI to C-Suite

Requirements:
- 7+ years marketing experience, 3+ in leadership role
- Strong data-driven approach with experience in HubSpot/Salesforce
- Proven track record of scaling B2B pipeline through digital channels
- Bachelor's degree required; MBA preferred"""

SYSTEM_PROMPT_RESUME = """You are an expert Career Coach strictly following the Harvard MCS resume guidelines. Tailor the candidate's Base Resume to the Target Job Description.
CRITICAL RULES: Return ONLY the raw, clean markdown resume. No code blocks. No extra text."""

SYSTEM_PROMPT_COVER = """You are a career advisor following Harvard MCS cover letter guidelines. Write a tailored one-page cover letter.
Return ONLY the markdown letter."""

SYSTEM_PROMPT_ANALYZE = """You are a strict technical recruiter. Analyze the Base Resume against the Target Job Description. Provide:
1. Match Percentage
2. Skills Gap (bullet points)
3. Interview Prep (3 specific questions + strategy)"""


def call_api(action_name, system_prompt, user_query):
    payload = {
        "action": "generateResume",
        "systemPrompt": system_prompt,
        "userQuery": user_query
    }
    data = urllib.parse.urlencode({'data': json.dumps(payload)}).encode('utf-8')
    req = urllib.request.Request(
        PROD_URL,
        data=data,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            body = resp.read().decode('utf-8')
            result = json.loads(body)
            if 'error' in result:
                return False, f"API Error: {result['error'][:300]}"
            text = result.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')
            if not text:
                return False, f"Empty text in response. Raw: {body[:300]}"
            return True, text[:200]
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8')
        return False, f"HTTP {e.code}: {body[:300]}"
    except Exception as e:
        return False, f"Exception: {str(e)}"


USER_QUERY = f"BASE RESUME:\n{FAKE_RESUME}\n\nTARGET JOB DESCRIPTION:\n{FAKE_JD}"

tests = [
    ("Tailor Resume", SYSTEM_PROMPT_RESUME, USER_QUERY),
    ("Cover Letter", SYSTEM_PROMPT_COVER, USER_QUERY),
    ("Analyze Fit",  SYSTEM_PROMPT_ANALYZE, USER_QUERY),
]

print("=" * 60)
print("LIVE END-TO-END STUDIO TESTS")
print(f"Target: {PROD_URL}")
print("=" * 60)

all_passed = True
for name, sp, uq in tests:
    print(f"\n▶ Testing: {name}...")
    success, result = call_api(name, sp, uq)
    status = "✅ PASS" if success else "❌ FAIL"
    print(f"  {status}")
    print(f"  {'Preview:' if success else 'Error:'} {result}")
    if not success:
        all_passed = False

print("\n" + "=" * 60)
print("RESULT:", "✅ ALL TESTS PASSED" if all_passed else "❌ SOME TESTS FAILED")
print("=" * 60)
sys.exit(0 if all_passed else 1)
