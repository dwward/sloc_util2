



import requests
from datetime import datetime
from dateutil.relativedelta import relativedelta
import configparser
import os
import collections
import argparse
import urllib3
import json

# Parse Access Token
TOKEN = os.environ.get("GITHUB_PAT")
if not TOKEN:
    parser = argparse.ArgumentParser(description="GitHub Enterprise Commit Report Generator")
    parser.add_argument("--token", required=False, help="GitHub Personal Access Token")
    args = parser.parse_args()
    TOKEN = args.token
if not TOKEN:
    raise ValueError("Personal Access Token is not set. Set GITHUB_PAT or use '--token <token>'")

# Load configuration
config = configparser.ConfigParser(allow_no_value=True, inline_comment_prefixes=('#', ';'))
config.read('config.properties')

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# GitHub API setup
GITHUB_URL = config.get('DEFAULT', 'github_url')
GRAPHQL_URL = GITHUB_URL.replace('/api/v3', '/api/graphql')
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"}

# Report settings
TIME_RANGE = config.get('DEFAULT', 'time_range', fallback='')
LAST_X_MONTHS = config.getint('DEFAULT', 'last_x_months')
USE_ORG_REPOS = config.getboolean('DEFAULT', 'use_org_repos')
ORGANIZATION = config.get('DEFAULT', 'organization') if USE_ORG_REPOS else None
DEVS_FILE = config.get('DEFAULT', 'devs_file')
REPOS_FILE = config.get('DEFAULT', 'repos_file')
DISABLE_SSL = config.getboolean('DEFAULT', 'disable_ssl', fallback=True)
TARGET_BRANCHES = config.get('DEFAULT', 'branches', fallback='main').split(',')
IGNORE_NO_EXTENSION = config.getboolean('DEFAULT', 'ignore_no_extension', fallback=False)
SHOW_REPO_STATS = config.getboolean('DEFAULT', 'show_repo_states', fallback=False)
PER_REPO = config.getboolean('DEFAULT', 'show_repo_stats', fallback=True)

# Debug settings
DEBUG_MODE = config.getboolean('DEFAULT', 'debug_mode')
DEBUG_DEV = config.get('DEFAULT', 'debug_dev')
DEBUG_REPO = config.get('DEFAULT', 'debug_repo')

# Language mapping
LANGUAGE_MAP = {
    "py": "Python", "js": "JavaScript", "ts": "TypeScript", "java": "Java",
    "cpp": "C++", "c": "C", "h": "C Header", "cs": "C#", "rb": "Ruby",
    "go": "Go", "rs": "Rust", "php": "PHP", "html": "HTML", "css": "CSS",
    "md": "Markdown", "json": "JSON", "yaml": "YAML", "yml": "YAML",
    "sh": "Shell", "no_extension": "Unknown"
}

# Global session
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

# In-memory cache
COMMITS_CACHE = {}

def load_file_lines(file_path):
    with open(file_path, 'r') as f:
        return [line.strip() for line in f if line.strip() and not line.strip().startswith(('#', ';'))]

def get_time_range():
    if TIME_RANGE:
        try:
            start, end = TIME_RANGE.split(':')
            datetime.strptime(start, '%Y-%m-%d')
            datetime.strptime(end, '%Y-%m-%d')
            since = f"{start}T00:00:00Z"
            until = f"{end}T23:59:59Z"
            return since, until
        except ValueError as e:
            raise ValueError(f"Invalid time_range format: {e}")
    else:
        end = datetime.now()
        start = end - relativedelta(months=LAST_X_MONTHS)
        since = start.strftime('%Y-%m-%dT00:00:00Z')
        until = end.strftime('%Y-%m-%dT23:59:59Z')
        return since, until

def probe_repositories(repos):
    valid_repos = []
    for repo in repos:
        url = f"{GITHUB_URL}/repos/{repo}"
        try:
            response = SESSION.head(url, verify=not DISABLE_SSL)
            response.raise_for_status()
            valid_repos.append(repo)
        except requests.exceptions.RequestException as e:
            print(f"\nSkipping repository '{repo}': {e}")
    return valid_repos

def get_org_repos(org):
    repos = []
    url = f"{GITHUB_URL}/orgs/{org}/repos?per_page=100"
    while url:
        response = SESSION.get(url, verify=not DISABLE_SSL)
        response.raise_for_status()
        repos.extend([repo['full_name'] for repo in response.json()])
        url = response.links.get('next', {}).get('url')
    return repos

def get_commits_graphql(repos, author, since, until):
    """Fetch commits for an author across multiple repositories using GraphQL."""
    cache_key = (tuple(repos), author, since, until)
    if
