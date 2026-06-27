#!/usr/bin/env python3
import os
import json
import ssl
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

# Fix Mac Python SSL: create unverified context for outbound HTTPS calls
# (Connection is still encrypted — this only bypasses local cert store issues)
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


PORT = 8000
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_DIR = os.path.join(BASE_DIR, "database")

# Helper to load environment from .env file if it exists
def load_dotenv():
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    if "=" in line:
                        key, val = line.split("=", 1)
                        os.environ[key.strip()] = val.strip()

load_dotenv()

class APIHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        # Allow CORS just in case
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        # Intercept /api requests
        parsed_url = urllib.parse.urlparse(self.path)
        if parsed_url.path == "/api":
            self.handle_get_jobs()
        else:
            # Fall back to standard static file serving
            super().do_GET()

    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)
        if parsed_url.path == "/api":
            self.handle_api_post()
        else:
            self.send_error(404, "Not Found")

    def handle_get_jobs(self):
        jobs_file = os.path.join(DATABASE_DIR, "jobs.json")
        try:
            if os.path.exists(jobs_file):
                with open(jobs_file, "r", encoding="utf-8") as f:
                    jobs_data = json.load(f)
            else:
                jobs_data = []
            
            response_bytes = json.dumps(jobs_data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response_bytes)))
            self.end_headers()
            self.wfile.write(response_bytes)
        except Exception as e:
            self.send_error_response(500, f"Failed to read jobs database: {str(e)}")

    def handle_api_post(self):
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length).decode("utf-8")
        
        payload = {}
        # Support both urlencoded (data=...) and application/json
        content_type = self.headers.get("Content-Type", "")
        if "application/x-www-form-urlencoded" in content_type:
            parsed_params = urllib.parse.parse_qs(post_data)
            if "data" in parsed_params:
                try:
                    payload = json.loads(parsed_params["data"][0])
                except json.JSONDecodeError:
                    self.send_error_response(400, "Invalid JSON in data parameter")
                    return
            else:
                # Fallback: try parsing form fields directly if not wrapped in data
                payload = {k: v[0] for k, v in parsed_params.items()}
        else:
            # Try direct JSON parsing
            try:
                payload = json.loads(post_data) if post_data else {}
            except json.JSONDecodeError:
                self.send_error_response(400, "Invalid JSON body")
                return

        action = payload.get("action")
        if not action:
            self.send_error_response(400, "Missing action parameter")
            return

        if action == "getProfiles":
            self.handle_get_profiles()
        elif action == "getSources":
            self.handle_get_sources()
        elif action == "addSource":
            self.handle_add_source(payload)
        elif action == "updateStatus":
            self.handle_update_status(payload)
        elif action == "batchUpsertJobs":
            self.handle_batch_upsert_jobs(payload)
        elif action == "generateResume":
            self.handle_generate_resume(payload)
        elif action == "fetchUrl":
            self.handle_fetch_url(payload)
        else:
            self.send_error_response(400, f"Unknown action: {action}")

    def handle_get_profiles(self):
        profiles_file = os.path.join(DATABASE_DIR, "profiles.json")
        try:
            if os.path.exists(profiles_file):
                with open(profiles_file, "r", encoding="utf-8") as f:
                    profiles_data = json.load(f)
            else:
                profiles_data = {}
            self.send_json_response({"success": True, "profiles": profiles_data})
        except Exception as e:
            self.send_error_response(500, f"Failed to read profiles database: {str(e)}")

    def handle_get_sources(self):
        sources_file = os.path.join(DATABASE_DIR, "sources.json")
        try:
            if os.path.exists(sources_file):
                with open(sources_file, "r", encoding="utf-8") as f:
                    sources_data = json.load(f)
            else:
                sources_data = []
            self.send_json_response({"success": True, "sources": sources_data})
        except Exception as e:
            self.send_error_response(500, f"Failed to read sources database: {str(e)}")

    def handle_add_source(self, payload):
        sources_file = os.path.join(DATABASE_DIR, "sources.json")
        try:
            if os.path.exists(sources_file):
                with open(sources_file, "r", encoding="utf-8") as f:
                    sources_data = json.load(f)
            else:
                sources_data = []

            # Map form parameters to capitalized JSON keys
            new_source = {
                "Organization": payload.get("org", "").strip(),
                "URL": payload.get("url", "").strip(),
                "Target Keywords": payload.get("keywords", "").strip(),
                "Exclude Keywords": payload.get("excludes", "").strip(),
                "Sector Tag": payload.get("sector", "All").strip()
            }
            
            sources_data.append(new_source)
            with open(sources_file, "w", encoding="utf-8") as f:
                json.dump(sources_data, f, indent=2)

            self.send_json_response({"success": True})
        except Exception as e:
            self.send_error_response(500, f"Failed to add source: {str(e)}")

    def handle_update_status(self, payload):
        job_id = payload.get("jobId")
        new_status = payload.get("status")
        if not job_id:
            self.send_error_response(400, "Missing jobId")
            return

        jobs_file = os.path.join(DATABASE_DIR, "jobs.json")
        try:
            if os.path.exists(jobs_file):
                with open(jobs_file, "r", encoding="utf-8") as f:
                    jobs_data = json.load(f)
            else:
                jobs_data = []

            updated = False
            for job in jobs_data:
                if job.get("id") == job_id:
                    job["userStatus"] = new_status
                    updated = True
                    break

            if updated:
                with open(jobs_file, "w", encoding="utf-8") as f:
                    json.dump(jobs_data, f, indent=2)
                self.send_json_response({"success": True, "jobId": job_id, "newStatus": new_status})
            else:
                self.send_json_response({"success": False, "error": "Job not found"})
        except Exception as e:
            self.send_error_response(500, f"Failed to update status: {str(e)}")

    def handle_batch_upsert_jobs(self, payload):
        incoming_jobs = payload.get("jobs", [])
        jobs_file = os.path.join(DATABASE_DIR, "jobs.json")
        try:
            if os.path.exists(jobs_file):
                with open(jobs_file, "r", encoding="utf-8") as f:
                    jobs_data = json.load(f)
            else:
                jobs_data = []

            # Map existing jobs by id
            jobs_map = {job["id"]: job for job in jobs_data if "id" in job}
            
            updated_count = 0
            appended_count = 0

            for job in incoming_jobs:
                job_id = job.get("id")
                if not job_id:
                    continue

                if job_id in jobs_map:
                    # Update existing job, but preserve userStatus if not explicitly updated in the incoming payload
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

            self.send_json_response({
                "success": True,
                "updated": updated_count,
                "appended": appended_count
            })
        except Exception as e:
            self.send_error_response(500, f"Failed to batch upsert jobs: {str(e)}")

    def handle_generate_resume(self, payload):
        # Build list of API keys from environment (primary + fallbacks)
        keys = []
        for var in ["GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3"]:
            k = os.environ.get(var)
            if k:
                keys.append(k)

        if not keys:
            self.send_error_response(500, "No GEMINI_API_KEY environment variables configured.")
            return

        # Models to try in order: lite first (cheapest quota), then full flash
        models = ["gemini-2.5-flash-lite", "gemini-2.0-flash", "gemini-2.5-flash"]

        gemini_payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": payload.get("userQuery", "")}]
                }
            ],
            "systemInstruction": {
                "parts": [{"text": payload.get("systemPrompt", "")}]
            },
            "generationConfig": {
                "temperature": 0.2
            }
        }
        body = json.dumps(gemini_payload).encode("utf-8")

        last_error = "All API keys and models exhausted."
        for model in models:
            for key in keys:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
                req = urllib.request.Request(
                    url,
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                try:
                    with urllib.request.urlopen(req, timeout=30, context=_ssl_ctx) as response:
                        response_bytes = response.read()
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.send_header("Content-Length", str(len(response_bytes)))
                        self.end_headers()
                        self.wfile.write(response_bytes)
                        return  # Success — stop
                except urllib.error.HTTPError as e:
                    err_text = e.read().decode("utf-8")
                    if e.code in [429, 500, 502, 503, 504]:
                        last_error = f"HTTP {e.code} on {model}"
                        continue  # Try next key / model
                    elif e.code == 404:
                        last_error = f"Model {model} not found"
                        break  # This model is unavailable, skip to next model
                    else:
                        self.send_json_response({"error": f"Gemini API HTTP Error {e.code}: {err_text}"})
                        return
                except Exception as e:
                    last_error = str(e)
                    continue

        self.send_json_response({"error": f"All Gemini API keys/models exhausted. Last error: {last_error}. Try again later."})

    def handle_fetch_url(self, payload):
        target_url = payload.get("url")
        if not target_url:
            self.send_error_response(400, "Missing url parameter")
            return
            
        try:
            req = urllib.request.Request(
                target_url, 
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
            )
            with urllib.request.urlopen(req, timeout=15, context=_ssl_ctx) as response:
                html = response.read().decode("utf-8", errors="ignore")
                self.send_json_response({"success": True, "html": html})
        except Exception as e:
            self.send_json_response({"success": False, "error": str(e)})

    def send_json_response(self, data):
        response_bytes = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.end_headers()
        self.wfile.write(response_bytes)

    def send_error_response(self, status_code, message):
        response_bytes = json.dumps({"error": message}).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.end_headers()
        self.wfile.write(response_bytes)

def run():
    print(f"Starting server on http://localhost:{PORT} ...")
    server_address = ("", PORT)
    httpd = ThreadingHTTPServer(server_address, APIHandler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        httpd.server_close()

if __name__ == "__main__":
    run()
