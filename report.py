import requests
from datetime import datetime
from dateutil.relativedelta import relativedelta
import configparser
import os
import collections
import argparse
import urllib3
import json
import re

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
REPO_BATCH_SIZE = config.getint('DEFAULT', 'repo_batch_size', fallback=10)  # New config option

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
            response = SESSION.head(url, verify=not DISABLE_SSL, timeout=(5.0, 30.0))
            response.raise_for_status()
            valid_repos.append(repo)
        except requests.exceptions.RequestException as e:
            print(f"\nSkipping repository '{repo}': {e}")
    return valid_repos

def get_org_repos(org):
    repos = []
    url = f"{GITHUB_URL}/orgs/{org}/repos?per_page=100"
    while url:
        response = SESSION.get(url, verify=not DISABLE_SSL, timeout=(5.0, 30.0))
        response.raise_for_status()
        repos.extend([repo['full_name'] for repo in response.json()])
        url = response.links.get('next', {}).get('url')
    return repos

def validate_token():
    """Validate the token with a simple GraphQL query."""
    query = "query { viewer { login } }"
    try:
        response = SESSION.post(GRAPHQL_URL, json={"query": query}, verify=not DISABLE_SSL, timeout=(5.0, 30.0))
        response.raise_for_status()
        data = response.json()
        print(f"Token validated successfully. User: {data['data']['viewer']['login']}")
    except requests.exceptions.HTTPError as e:
        print(f"Token validation failed: {e}")
        if 'response' in locals():
            print(f"Status Code: {response.status_code}")
            print(f"Response Text: {response.text}")
        raise
    except requests.exceptions.RequestException as e:
        print(f"Unexpected error during token validation: {e}")
        raise

def get_commits_graphql(repos, author, since, until):
    """Fetch commits for an author across multiple repositories using GraphQL with pagination."""
    cache_key = (tuple(repos), author, since, until)
    if cache_key in COMMITS_CACHE:
        print(f"Cache hit for {author} across {len(repos)} repos")
        return COMMITS_CACHE[cache_key]

    print(f"Fetching GraphQL data for {author} across {len(repos)} repos in batches of {REPO_BATCH_SIZE}...")
    print(f"Querying branches: {TARGET_BRANCHES}, since: {since}, until: {until}")
    commits_by_repo = {}
    
    # Process repos in batches
    for batch_start in range(0, len(repos), REPO_BATCH_SIZE):
        batch_repos = repos[batch_start:batch_start + REPO_BATCH_SIZE]
        if DEBUG_MODE and batch_start >= 5:  # Limit to 5 repos total in debug mode
            break
        
        query_parts = []
        for i, repo in enumerate(batch_repos):
            org, repo_name = repo.split('/')
            query_parts.append(
                f'repo{i}: repository(owner: "{org}", name: "{repo_name}") {{\n'
                f'  refs(refPrefix: "refs/heads/", first: 50) {{\n'
                f'    nodes {{\n'
                f'      name\n'
                f'      target {{\n'
                f'        ... on Commit {{\n'
                f'          history(first: 50, since: $since, until: $until) {{\n'
                f'            nodes {{\n'
                f'              oid\n'
                f'              additions\n'
                f'              deletions\n'
                f'              changedFilesIfAvailable\n'
                f'              committedDate\n'
                f'              author {{\n'
                f'                name\n'
                f'                email\n'
                f'                user {{\n'
                f'                  login\n'
                f'                }}\n'
                f'              }}\n'
                f'            }}\n'
                f'            pageInfo {{\n'
                f'              endCursor\n'
                f'              hasNextPage\n'
                f'            }}\n'
                f'          }}\n'
                f'        }}\n'
                f'      }}\n'
                f'    }}\n'
                f'  }}\n'
                f'}}'
            )
        query = f"query($since: GitTimestamp!, $until: GitTimestamp!) {{\n" + "\n".join(query_parts) + "\n}}"
        variables = {"since": since, "until": until}

        response = None
        try:
            response = SESSION.post(GRAPHQL_URL, json={"query": query, "variables": variables}, verify=not DISABLE_SSL, timeout=(5.0, 30.0))
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            print(f"GraphQL request failed for batch {batch_start}-{batch_start+len(batch_repos)-1}: {e}")
            if response:
                print(f"Status Code: {response.status_code}")
                print(f"Response Headers: {response.headers}")
                print(f"Response Text: {response.text}")
            else:
                print("No response received due to HTTP error")
            continue
        except requests.exceptions.Timeout as e:
            print(f"Timeout error for batch {batch_start}-{batch_start+len(batch_repos)-1}: {e}")
            continue
        except requests.exceptions.RequestException as e:
            print(f"Network error for batch {batch_start}-{batch_start+len(batch_repos)-1}: {e}")
            continue

        if not response:
            continue

        data = response.json()
        if DEBUG_MODE:
            print(f"GraphQL Response for batch {batch_start}-{batch_start+len(batch_repos)-1}: {json.dumps(data, indent=2)}")

        for i, repo in enumerate(batch_repos):
            repo_key = f"repo{i}"
            repo_data = data.get("data", {}).get(repo_key, {})
            commits_by_repo[repo] = []
            refs = repo_data.get("refs", {}).get("nodes", [])
            if not refs and DEBUG_MODE:
                print(f"No branches found in {repo}")

            for ref in refs:
                branch_name = ref.get("name", "unknown")
                if DEBUG_MODE:
                    print(f"Found branch in {repo}: {branch_name}")
                history = ref.get("target", {}).get("history", {}).get("nodes", [])
                if not history and DEBUG_MODE:
                    print(f"No commits found in {repo} on branch {branch_name} between {since} and {until}")
                for commit in history:
                    commit_login = commit.get("author", {}).get("user", {}).get("login", "")
                    commit_email_raw = commit.get("author", {}).get("email", "")
                    commit_name = commit.get("author", {}).get("name", "")
                    commit_email_match = re.search(r'<(.+?)>', commit_email_raw) if commit_email_raw else None
                    commit_email = commit_email_match.group(1) if commit_email_match else commit_email_raw
                    if DEBUG_MODE:
                        print(f"Commit in {repo}: login={commit_login or 'None'}, email_raw={commit_email_raw or 'None'}, email={commit_email or 'None'}, name={commit_name or 'None'}")
                    if (commit_login.lower() == author.lower() or 
                        (commit_email and commit_email.lower() == author.lower()) or 
                        (commit_email and commit_email.split('@')[0].lower() == author.lower())):
                        commit_data = {
                            "sha": commit["oid"],
                            "stats": {
                                "additions": commit.get("additions", 0),
                                "deletions": commit.get("deletions", 0),
                                "total": commit.get("changedFilesIfAvailable", 0)
                            },
                            "files": []
                        }
                        commits_by_repo[repo].append(commit_data)

    COMMITS_CACHE[cache_key] = commits_by_repo
    total_commits = sum(len(commits) for commits in commits_by_repo.values())
    print(f"Fetched {total_commits} unique commits for {author} across {len(repos)} repositories")
    return commits_by_repo

def get_commit_details(repo, sha):
    url = f"{GITHUB_URL}/repos/{repo}/commits/{sha}"
    response = SESSION.get(url, verify=not DISABLE_SSL, timeout=(5.0, 30.0))
    response.raise_for_status()
    return response.json()

def analyze_commits(repo, author, since, until, commits_by_repo=None):
    if commits_by_repo is None:
        commits_by_repo = get_commits_graphql([repo], author, since, until)
    
    file_type_stats = collections.defaultdict(lambda: {
        "additions": 0, "deletions": 0, "changes": 0, "modifications": 0, "added": 0, "removed": 0, "renamed": 0
    })
    per_repo_stats = {repo: collections.defaultdict(lambda: {
        "additions": 0, "deletions": 0, "changes": 0, "modifications": 0, "added": 0, "removed": 0, "renamed": 0
    })}

    commits = commits_by_repo.get(repo, [])
    for commit in commits:
        commit_data = get_commit_details(repo, commit["sha"])
        for file in commit_data.get("files", []):
            if file["filename"].startswith("."):
                continue
            ext = file["filename"].split(".")[-1] if "." in file["filename"] else "no_extension"
            if IGNORE_NO_EXTENSION and ext == "no_extension":
                continue
            additions = file.get("additions", 0)
            deletions = file.get("deletions", 0)
            changes = file.get("changes", 0)
            status = file.get("status", "")

            file_type_stats[ext]["additions"] += additions
