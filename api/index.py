import os
import json
import base64
import urllib.parse
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler

# Unified database manager supporting local filesystem and serverless GitHub REST API writes
class DBManager:
    def __init__(self):
        self.is_vercel = os.environ.get("VERCEL") is not None
        self.github_token = os.environ.get("GITHUB_TOKEN")
        self.repo = "gregoriobueno-coder/family-jobs"
        self.branch = "main"
        # In Vercel, the directory containing python files is api/
        self.api_dir = os.path.dirname(os.path.abspath(__file__))
        self.base_dir = os.path.dirname(self.api_dir)

    def _github_request(self, path, method="GET", body=None):
        url = f"https://api.github.com/repos/{self.repo}/contents/{path}"
        req = urllib.request.Request(url, method=method)
        req.add_header("Authorization", f"token {self.github_token}")
        req.add_header("Accept", "application/vnd.github.v3+json")
        req.add_header("User-Agent", "family-jobs-api")
        
        if body is not None:
            req.data = json.dumps(body).encode("utf-8")
            req.add_header("Content-Type", "application/json")
            
        try:
            with urllib.request.urlopen(req, timeout=15) as res:
                return json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_text = e.read().decode("utf-8")
            print(f"[DB ERROR] GitHub API error: {e.code} - {err_text}")
            raise Exception(f"GitHub API error: {e.code} - {err_text}")

    def read_file(self, relative_path):
        if not self.is_vercel or not self.github_token:
            # Local read
            local_path = os.path.join(self.base_dir, relative_path)
            if os.path.exists(local_path):
                with open(local_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            return [] if "jobs" in relative_path or "sources" in relative_path else {}
        else:
            # Vercel read from GitHub API
            try:
                res = self._github_request(relative_path, "GET")
                content_b64 = res.get("content", "")
                content_bytes = base64.b64decode(content_b64)
                return json.loads(content_bytes.decode("utf-8"))
            except Exception as e:
                print(f"[DB ERROR] Failed to read {relative_path} from GitHub: {e}")
                # Ephemeral fallback to read-only package files on Vercel deployment
                local_path = os.path.join(self.base_dir, relative_path)
                if os.path.exists(local_path):
                    with open(local_path, "r", encoding="utf-8") as f:
                        return json.load(f)
                return [] if "jobs" in relative_path or "sources" in relative_path else {}

    def write_file(self, relative_path, data, message="chore: update database"):
        if not self.is_vercel or not self.github_token:
            # Local write
            local_path = os.path.join(self.base_dir, relative_path)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return True
        else:
            # Vercel write to GitHub (commits updated JSON database back to repository)
            try:
                res = self._github_request(relative_path, "GET")
                sha = res.get("sha")
            except Exception:
                sha = None
                
            content_str = json.dumps(data, indent=2)
            content_b64 = base64.b64encode(content_str.encode("utf-8")).decode("utf-8")
            
            body = {
                "message": message + " [skip ci]",
                "content": content_b64,
                "branch": self.branch
            }
            if sha:
                body["sha"] = sha
                
            self._github_request(relative_path, "PUT", body)
            return True

db = DBManager()

class handler(BaseHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        # Intercept GET /api or sub-routes
        if parsed_url.path.startswith("/api"):
            self.handle_get_jobs()
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)
        if parsed_url.path.startswith("/api"):
            self.handle_api_post()
        else:
            self.send_error(404, "Not Found")

    def handle_get_jobs(self):
        try:
            jobs_data = db.read_file("database/jobs.json")
            response_bytes = json.dumps(jobs_data).encode("utf-8")
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response_bytes)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(response_bytes)
        except Exception as e:
            self.send_error_response(500, f"Failed to read jobs database: {str(e)}")

    def handle_api_post(self):
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length).decode("utf-8")
        
        payload = {}
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
                payload = {k: v[0] for k, v in parsed_params.items()}
        else:
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
        elif action == "listModels":
            self.handle_list_models()
        elif action == "fetchUrl":
            self.handle_fetch_url(payload)
        elif action == "runAutoApply":
            self.handle_run_auto_apply(payload)
        else:
            self.send_error_response(400, f"Unknown action: {action}")

    def handle_get_profiles(self):
        try:
            profiles_data = db.read_file("database/profiles.json")
            self.send_json_response({"success": True, "profiles": profiles_data})
        except Exception as e:
            self.send_error_response(500, f"Failed to read profiles database: {str(e)}")

    def handle_get_sources(self):
        try:
            sources_data = db.read_file("database/sources.json")
            self.send_json_response({"success": True, "sources": sources_data})
        except Exception as e:
            self.send_error_response(500, f"Failed to read sources database: {str(e)}")

    def handle_add_source(self, payload):
        try:
            sources_data = db.read_file("database/sources.json")
            new_source = {
                "Organization": payload.get("org", "").strip(),
                "URL": payload.get("url", "").strip(),
                "Target Keywords": payload.get("keywords", "").strip(),
                "Exclude Keywords": payload.get("excludes", "").strip(),
                "Sector Tag": payload.get("sector", "All").strip()
            }
            sources_data.append(new_source)
            db.write_file("database/sources.json", sources_data, message="feat: add scraper source")
            self.send_json_response({"success": True})
        except Exception as e:
            self.send_error_response(500, f"Failed to add source: {str(e)}")

    def handle_update_status(self, payload):
        job_id = payload.get("jobId")
        new_status = payload.get("status")
        if not job_id:
            self.send_error_response(400, "Missing jobId")
            return

        try:
            jobs_data = db.read_file("database/jobs.json")
            updated = False
            for job in jobs_data:
                if job.get("id") == job_id:
                    job["userStatus"] = new_status
                    updated = True
                    break

            if updated:
                db.write_file("database/jobs.json", jobs_data, message=f"chore: update job {job_id} status to {new_status}")
                self.send_json_response({"success": True, "jobId": job_id, "newStatus": new_status})
            else:
                self.send_json_response({"success": False, "error": "Job not found"})
        except Exception as e:
            self.send_error_response(500, f"Failed to update status: {str(e)}")

    def handle_batch_upsert_jobs(self, payload):
        incoming_jobs = payload.get("jobs", [])
        try:
            jobs_data = db.read_file("database/jobs.json")
            jobs_map = {job["id"]: job for job in jobs_data if "id" in job}
            updated_count = 0
            appended_count = 0

            for job in incoming_jobs:
                job_id = job.get("id")
                if not job_id:
                    continue

                if job_id in jobs_map:
                    existing_job = jobs_map[job_id]
                    user_status = job.get("userStatus") or existing_job.get("userStatus") or ""
                    existing_job.update(job)
                    existing_job["userStatus"] = user_status
                    updated_count += 1
                else:
                    jobs_data.append(job)
                    jobs_map[job_id] = job
                    appended_count += 1

            db.write_file("database/jobs.json", jobs_data, message=f"chore: batch upsert {len(incoming_jobs)} jobs")
            self.send_json_response({
                "success": True,
                "updated": updated_count,
                "appended": appended_count
            })
        except Exception as e:
            self.send_error_response(500, f"Failed to batch upsert jobs: {str(e)}")

    def handle_run_auto_apply(self, payload):
        job_url = payload.get("url")
        candidate = payload.get("candidate")
        if not job_url or not candidate:
            self.send_error_response(400, "url and candidate are required")
            return
            
        # If running locally (not Vercel), fall back to local subprocess
        if not db.is_vercel:
            try:
                import subprocess
                python_exec = os.path.join(db.base_dir, "test_venv", "bin", "python3")
                script_path = os.path.join(db.base_dir, "auto_apply.py")
                
                result = subprocess.run([python_exec, script_path, job_url, candidate, "--autonomous"], 
                                        cwd=db.base_dir, capture_output=True, text=True)
                if result.returncode == 0:
                    self.send_json_response({"success": True, "output": result.stdout, "local": True})
                else:
                    self.send_error_response(500, f"Auto-Applier failed: {result.stderr}")
            except Exception as e:
                self.send_error_response(500, f"Error running local auto-applier: {str(e)}")
            return
            
        # If on Vercel, dispatch to GitHub Actions
        if not db.github_token:
            self.send_error_response(500, "GITHUB_TOKEN is missing. Cannot dispatch background bot.")
            return
            
        try:
            url = f"https://api.github.com/repos/{db.repo}/dispatches"
            req = urllib.request.Request(url, method="POST")
            req.add_header("Authorization", f"token {db.github_token}")
            req.add_header("Accept", "application/vnd.github.v3+json")
            req.add_header("User-Agent", "family-jobs-api")
            
            body = {
                "event_type": "run_auto_apply",
                "client_payload": {
                    "url": job_url,
                    "candidate": candidate
                }
            }
            req.data = json.dumps(body).encode("utf-8")
            req.add_header("Content-Type", "application/json")
            
            with urllib.request.urlopen(req, timeout=10) as res:
                pass # A successful dispatch returns 204 No Content
                
            self.send_json_response({
                "success": True, 
                "output": "Vercel successfully dispatched background GitHub Action to run Playwright."
            })
        except Exception as e:
            self.send_error_response(500, f"Failed to dispatch GitHub Action: {str(e)}")

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
        # Try each key x model combination until one works
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
                    with urllib.request.urlopen(req, timeout=30) as response:
                        response_bytes = response.read()
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.send_header("Content-Length", str(len(response_bytes)))
                        self.end_headers()
                        self.wfile.write(response_bytes)
                        return  # Success — stop here
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

        self.send_json_response({"error": f"All Gemini API keys/models exhausted. Last error: {last_error}. Please try again later or check https://ai.dev/rate-limit"})

    def handle_list_models(self):
        gemini_api_key = os.environ.get("GEMINI_API_KEY")
        if not gemini_api_key:
            self.send_error_response(500, "GEMINI_API_KEY environment variable is not configured on Vercel.")
            return

        results = {}
        for version in ["v1beta", "v1"]:
            url = f"https://generativelanguage.googleapis.com/{version}/models?key={gemini_api_key}"
            req = urllib.request.Request(url, method="GET")
            try:
                with urllib.request.urlopen(req, timeout=10) as response:
                    res_json = json.loads(response.read().decode("utf-8"))
                    results[version] = [m.get("name") for m in res_json.get("models", [])]
            except Exception as e:
                results[version] = f"Error: {str(e)}"
        
        self.send_json_response({"success": True, "models": results})

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
            with urllib.request.urlopen(req, timeout=15) as response:
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
