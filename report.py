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
    if cache_key in COMMITS_CACHE:
        print(f"Cache hit for {author} across {len(repos)} repos")
        return COMMITS_CACHE[cache_key]

    print(f"Fetching GraphQL data for {author} across {len(repos)} repos...")
    query_parts = []
    variables = {"since": since, "until": until}
    for i, repo in enumerate(repos):
        org, repo_name = repo.split('/')
        query_parts.append(
            f'repo{i}: repository(owner: "{org}", name: "{repo_name}") {{\n'
            f'  refs(refPrefix: "refs/heads/", first: {len(TARGET_BRANCHES)}, query: "{" ".join(TARGET_BRANCHES)}") {{\n'
            f'    nodes {{\n'
            f'      target {{\n'
            f'        ... on Commit {{\n'
            f'          history(first: 100, since: $since, until: $until) {{\n'
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
            f'            pageInfo {{ endCursor, hasNextPage }}\n'
            f'          }}\n'
            f'        }}\n'
            f'      }}\n'
            f'    }}\n'
            f'  }}\n'
            f'}}'
        )
    query = "query($since: GitTimestamp!, $until: GitTimestamp!) {\n" + "\n".join(query_parts) + "\n}"

    try:
        response = SESSION.post(GRAPHQL_URL, json={"query": query, "variables": variables}, verify=not DISABLE_SSL, timeout=(0.5, 10.0))
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"GraphQL request failed for {author}: {e}")
        print(f"Response text: {response.text}")
        return {}

    data = response.json()
    print(f"GraphQL Response for {author}: {json.dumps(data, indent=2)}")

    commits_by_repo = {}
    for i, repo in enumerate(repos):
        repo_key = f"repo{i}"
        repo_data = data.get("data", {}).get(repo_key, {})
        commits_by_repo[repo] = []
        for ref in repo_data.get("refs", {}).get("nodes", []):
            history = ref.get("target", {}).get("history", {}).get("nodes", [])
            for commit in history:
                commit_login = commit.get("author", {}).get("user", {}).get("login", "")
                commit_email = commit.get("author", {}).get("email", "")
                commit_name = commit.get("author", {}).get("name", "")
                if DEBUG_MODE:
                    print(f"Commit in {repo}: login={commit_login}, email={commit_email}, name={commit_name}")
                # Match author by login, email, or email username
                if (commit_login == author or 
                    commit_email == author or 
                    (commit_email and commit_email.split('@')[0] == author)):
                    commit_data = {
                        "sha": commit["oid"],
                        "stats": {
                            "additions": commit.get("additions", 0),
                            "deletions": commit.get("deletions", 0),
                            "total": commit.get("changedFilesIfAvailable", 0)
                        },
                        "files": []  # Placeholder; fetch with REST
                    }
                    commits_by_repo[repo].append(commit_data)

    COMMITS_CACHE[cache_key] = commits_by_repo
    total_commits = sum(len(commits) for commits in commits_by_repo.values())
    print(f"Fetched {total_commits} unique commits for {author} across {len(repos)} repositories")
    return commits_by_repo

def get_commit_details(repo, sha):
    url = f"{GITHUB_URL}/repos/{repo}/commits/{sha}"
    response = SESSION.get(url, verify=not DISABLE_SSL)
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
            file_type_stats[ext]["deletions"] += deletions
            file_type_stats[ext]["changes"] += changes
            per_repo_stats[repo][ext]["additions"] += additions
            per_repo_stats[repo][ext]["deletions"] += deletions
            per_repo_stats[repo][ext]["changes"] += changes

            if status == "modified":
                file_type_stats[ext]["modifications"] += 1
                per_repo_stats[repo][ext]["modifications"] += 1
            elif status == "added":
                file_type_stats[ext]["added"] += 1
                per_repo_stats[repo][ext]["added"] += 1
            elif status == "removed":
                file_type_stats[ext]["removed"] += 1
                per_repo_stats[repo][ext]["removed"] += 1
            elif status == "renamed":
                file_type_stats[ext]["renamed"] += 1
                per_repo_stats[repo][ext]["renamed"] += 1

    return file_type_stats, per_repo_stats

def generate_report(devs, repos, since, until, per_repo=PER_REPO):
    report = {}
    for dev in devs:
        report[dev] = {
            "total": {"additions": 0, "deletions": 0, "changes": 0, "modifications": 0, "added": 0, "removed": 0, "renamed": 0},
            "by_file_type": collections.defaultdict(lambda: {
                "additions": 0, "deletions": 0, "changes": 0, "modifications": 0, "added": 0, "removed": 0, "renamed": 0
            })
        }
        if per_repo:
            report[dev]["by_repo"] = collections.defaultdict(lambda: collections.defaultdict(lambda: {
                "additions": 0, "deletions": 0, "changes": 0, "modifications": 0, "added": 0, "removed": 0, "renamed": 0
            }))

        commits_by_repo = get_commits_graphql(repos, dev, since, until)
        for repo in repos:
            file_stats, repo_stats = analyze...
