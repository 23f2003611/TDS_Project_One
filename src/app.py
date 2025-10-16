import os
import json
import time
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from github import Github
import openai

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configuration
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
SECRET_KEY = os.getenv('SECRET_KEY')
GITHUB_USERNAME = os.getenv('GITHUB_USERNAME')

# Initialize GitHub client
g = Github(GITHUB_TOKEN)
openai.api_key = OPENAI_API_KEY


@app.route('/api-endpoint', methods=['POST'])
def handle_request():
    """Main endpoint to receive task requests"""
    try:
        # Get JSON data
        data = request.get_json()
        
        # Validate secret
        if data.get('secret') != SECRET_KEY:
            return jsonify({"error": "Invalid secret"}), 403
        
        # Extract task details
        email = data.get('email')
        task = data.get('task')
        round_num = data.get('round')
        nonce = data.get('nonce')
        brief = data.get('brief')
        checks = data.get('checks', [])
        evaluation_url = data.get('evaluation_url')
        attachments = data.get('attachments', [])
        
        print(f"Received task: {task}, Round: {round_num}")
        print(f"Brief: {brief}")
        
        # Generate the app code using LLM
        app_code = generate_app_code(brief, attachments, checks)
        
        # Create unique repo name
        repo_name = f"{task}"
        
        # Create GitHub repo and deploy
        repo_url, commit_sha, pages_url = create_and_deploy_repo(
            repo_name, app_code, brief, round_num
        )
        
        # Report back to evaluation URL
        report_success = report_to_evaluation(
            evaluation_url, email, task, round_num, nonce,
            repo_url, commit_sha, pages_url
        )
        
        return jsonify({
            "status": "success",
            "repo_url": repo_url,
            "pages_url": pages_url,
            "reported": report_success
        }), 200
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({"error": str(e)}), 500


def generate_app_code(brief, attachments, checks):
    """Use OpenAI to generate app code based on brief"""
    
    # Prepare attachments info
    attachments_info = ""
    if attachments:
        attachments_info = "\n\nAttachments:\n"
        for att in attachments:
            attachments_info += f"- {att['name']}: {att['url'][:100]}...\n"
    
    # Prepare checks info
    checks_info = ""
    if checks:
        checks_info = "\n\nThe app must pass these checks:\n"
        for check in checks:
            checks_info += f"- {check}\n"
    
    prompt = f"""Generate a complete single-page HTML application based on this brief:

{brief}
{attachments_info}
{checks_info}

Requirements:
- Single HTML file with inline CSS and JavaScript
- Use CDN links for external libraries (Bootstrap, marked, highlight.js, etc.)
- Include all necessary functionality
- Make it production-ready and professional
- Handle errors gracefully

Return ONLY the HTML code, no explanations."""

    response = openai.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are an expert web developer. Generate clean, working HTML/CSS/JS code."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        max_tokens=3000
    )
    
    code = response.choices[0].message.content
    
    # Clean up code (remove markdown code blocks if present)
    if code.startswith('```'):
        code = '\n'.join(code.split('\n')[1:-1])
    
    return code


def create_and_deploy_repo(repo_name, app_code, brief, round_num):
    """Create GitHub repo, push code, and enable Pages"""
    
    user = g.get_user()
    
    # Check if repo exists
    try:
        repo = user.get_repo(repo_name)
        print(f"Repo {repo_name} already exists, updating...")
    except:
        # Create new repo
        repo = user.create_repo(
            repo_name,
            description=f"Auto-generated app - Round {round_num}",
            auto_init=False,
            private=False
        )
        print(f"Created new repo: {repo_name}")
    
    # Create/Update index.html
    try:
        contents = repo.get_contents("index.html")
        repo.update_file(
            "index.html",
            f"Update app for round {round_num}",
            app_code,
            contents.sha
        )
    except:
        repo.create_file("index.html", "Initial commit", app_code)
    
    # Create/Update README.md
    readme_content = generate_readme(brief, round_num)
    try:
        contents = repo.get_contents("README.md")
        repo.update_file("README.md", "Update README", readme_content, contents.sha)
    except:
        repo.create_file("README.md", "Add README", readme_content)
    
    # Create LICENSE (MIT)
    license_content = """MIT License

Copyright (c) 2025

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE."""
    
    try:
        contents = repo.get_contents("LICENSE")
    except:
        repo.create_file("LICENSE", "Add MIT License", license_content)
    
    # Enable GitHub Pages
    try:
        repo.create_pages_site(source={"branch": "main", "path": "/"})
    except:
        pass  # Pages might already be enabled
    
    # Get commit SHA
    commits = repo.get_commits()
    commit_sha = commits[0].sha
    
    # Construct URLs
    repo_url = repo.html_url
    pages_url = f"https://{GITHUB_USERNAME}.github.io/{repo_name}/"
    
    print(f"Deployed to: {pages_url}")
    
    return repo_url, commit_sha, pages_url


def generate_readme(brief, round_num):
    """Generate a professional README"""
    return f"""# Auto-Generated Application - Round {round_num}

## Overview
{brief}

## Setup
This is a static web application that runs directly in the browser.

## Usage
1. Visit the GitHub Pages URL
2. The application will load automatically
3. Follow the on-screen instructions

## Implementation
This application was automatically generated based on the provided brief and requirements.

### Technologies Used
- HTML5
- CSS3
- JavaScript (ES6+)
- External libraries loaded via CDN

## License
MIT License - See LICENSE file for details

## Generated
This project was automatically generated and deployed using an LLM-assisted build system.
"""


def report_to_evaluation(evaluation_url, email, task, round_num, nonce, repo_url, commit_sha, pages_url):
    """Report repo details to evaluation URL with retry logic"""
    
    payload = {
        "email": email,
        "task": task,
        "round": round_num,
        "nonce": nonce,
        "repo_url": repo_url,
        "commit_sha": commit_sha,
        "pages_url": pages_url
    }
    
    # Retry logic with exponential backoff
    delays = [1, 2, 4, 8]
    for attempt, delay in enumerate(delays + [None]):
        try:
            response = requests.post(
                evaluation_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            
            if response.status_code == 200:
                print(f"Successfully reported to evaluation URL")
                return True
            else:
                print(f"Evaluation URL returned {response.status_code}")
                
        except Exception as e:
            print(f"Error reporting (attempt {attempt + 1}): {str(e)}")
        
        if delay is not None:
            time.sleep(delay)
    
    return False


@app.route('/', methods=['GET'])
def home():
    """Home endpoint for testing"""
    return jsonify({
        "status": "running",
        "endpoint": "/api-endpoint",
        "method": "POST"
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)