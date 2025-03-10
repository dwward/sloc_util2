import requests
from datetime import datetime
from dateutil.relativedelta import relativedelta
import configparser
import os
import collections
import urllib3

# Suppress SSL verification warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Load token from environment variable
TOKEN = os.environ.get("GITHUB_PAT")
if not TOKEN:
    raise ValueError("GITHUB_PAT environment variable not set.")

# Load configuration with fallback support
config = configparser.ConfigParser(allow_no_value=True, inline_comment_prefixes=('#', ';'))
config.read('config.properties')

# GitHub API setup
GITHUB_URL = config.get('DEFAULT', 'github_url', fallback='https://github.com/api/v3')

# Report settings
TIME_RANGE = config.get('DEFAULT', 'time_range', fallback='')
LAST_X_MONTHS = config.getint('DEFAULT', 'last_x_months', fallback=6)
USE_ORG_REPOS = config.getboolean('DEFAULT', 'use_org_repos', fallback=False)
ORGANIZATION = config.get('DEFAULT', 'organization', fallback='')
REPOS_FILE = config.get('DEFAULT', 'repos_file', fallback='repos.txt')
IGNORE_NO_EXTENSION = config.getboolean('DEFAULT', 'ignore_no_extension', fallback=False)

# Debug settings
DEBUG_MODE = config.getboolean('DEFAULT', 'debug_mode', fallback=False)
DEBUG_DEV = config.get('DEFAULT', 'debug_dev', fallback='')
DEBUG_REPO = config.get('DEFAULT', 'debug_repo', fallback='')

# Branches to analyze (hardcoded for now)
TARGET_BRANCHES = ['main', 'develop']

# Language mapping
LANGUAGE_MAP = {
    "py": "Python",
    "js": "JavaScript",
    "ts": "TypeScript",
    "java": "Java",
    "cpp": "C++",
    "c": "C",
    "h": "C Header",
    "cs": "C#",
    "rb": "Ruby",
    "go": "Go",
    "rs": "Rust",
    "php": "PHP",
    "html": "HTML",
    "css": "CSS",
    "md": "Markdown",
    "json": "JSON",
    "yaml": "YAML",
    "yml": "YAML",
    "sh": "Shell",
    "no_extension": "Unknown"
}

# Helper functions
def load_file_lines(file_path):
    """Load lines from a file, ignoring comments starting with # or ;."""
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
            raise ValueError(f"Invalid time_range format in config.properties. Use YYYY-MM-DD:YYYY-MM-DD. Error: {e}")
    else:
        end = datetime.now()
        start = end - relativedelta(months=LAST_X_MONTHS)
        since = start.strftime('%Y-%m-%dT00:00:00Z')
        until = end.strftime('%Y-%m-%dT23:59:59Z')
        return since, until

def probe_repositories(repos):
    """Probe each repository to check if it exists and is accessible."""
    valid_repos = []
    for repo in repos:
        url = f"{GITHUB_URL}/repos/{repo}"
        try:
            response = requests.head(url, headers=HEADERS, verify=False)
            response.raise_for_status()
            valid_repos.append(repo)
        except requests.exceptions.RequestException as e:
            print(f"Skipping repository '{repo}': {e}")
    return valid_repos

def get_org_repos(org):
    repos = []
    url = f"{GITHUB_URL}/orgs/{org}/repos?per_page=100"
    while url:
        response = requests.get(url, headers=HEADERS, verify=False)
        response.raise_for_status()
        repos.extend([repo['full_name'] for repo in response.json()])
        url = response.links.get('next', {}).get('url')
    return repos

def get_commits(repo, author, since, until):
    """Fetch commits for an author across specified branches."""
    commits = []
    seen_shas = set()  # Avoid duplicates across branches
    for branch in TARGET_BRANCHES:
        url = f"{GITHUB_URL}/repos/{repo}/commits?author={author}&sha={branch}&since={since}&until={until}&per_page=100"
        while url:
            try:
                response = requests.get(url, headers=HEADERS, verify=False)
                response.raise_for_status()
                branch_commits = response.json()
                for commit in branch_commits:
                    sha = commit["sha"]
                    if sha not in seen_shas:  # Skip duplicates
                        commits.append(commit)
                        seen_shas.add(sha)
                url = response.links.get('next', {}).get('url')
            except requests.exceptions.RequestException as e:
                print(f"Warning: Could not fetch commits for branch '{branch}' in '{repo}': {e}")
                break  # Move to next branch if this one fails
    if DEBUG_MODE:
        print(f"Fetched {len(commits)} unique commits for {author} in {repo} across {TARGET_BRANCHES}")
    return commits

def get_commit_details(repo, sha):
    url = f"{GITHUB_URL}/repos/{repo}/commits/{sha}"
    response = requests.get(url, headers=HEADERS, verify=False)
    response.raise_for_status()
    return response.json()

def analyze_commits(repo, author, since, until):
    commits = get_commits(repo, author, since, until)
    file_type_stats = collections.defaultdict(lambda: {
        "additions": 0, "deletions": 0, "changes": 0,
        "modifications": 0, "added": 0, "removed": 0, "renamed": 0
    })
    per_repo_stats = {repo: collections.defaultdict(lambda: {
        "additions": 0, "deletions": 0, "changes": 0,
        "modifications": 0, "added": 0, "removed": 0, "renamed": 0
    })}

    for commit in commits:
        sha = commit["sha"]
        commit_data = get_commit_details(repo, sha)
        for file in commit_data.get("files", []):
            ext = file["filename"].split(".")[-1] if "." in file["filename"] else "no_extension"
            # Skip files without extensions if configured
            if IGNORE_NO_EXTENSION and ext == "no_extension":
                continue
            additions = file.get("additions", 0)
            deletions = file.get("deletions", 0)
            changes = file.get("changes", 0)
            status = file.get("status", "")

            # Update line stats
            file_type_stats[ext]["additions"] += additions
            file_type_stats[ext]["deletions"] += deletions
            file_type_stats[ext]["changes"] += changes
            per_repo_stats[repo][ext]["additions"] += additions
            per_repo_stats[repo][ext]["deletions"] += deletions
            per_repo_stats[repo][ext]["changes"] += changes

            # Update file status counts
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

def generate_report(devs, repos, since, until, per_repo=False):
    report = {}
    for dev in devs:
        report[dev] = {
            "total": {"additions": 0, "deletions": 0, "changes": 0, "modifications": 0, "added": 0, "removed": 0, "renamed": 0},
            "by_file_type": collections.defaultdict(lambda: {
                "additions": 0, "deletions": 0, "changes": 0, "modifications": 0, "added": 0, "removed": 0, "renamed": 0
            })
        }
        # Only initialize by_repo if per_repo is True
        if per_repo:
            report[dev]["by_repo"] = collections.defaultdict(lambda: collections.defaultdict(lambda: {
                "additions": 0, "deletions": 0, "changes": 0, "modifications": 0, "added": 0, "removed": 0, "renamed": 0
            }))

        for repo in repos:
            file_stats, repo_stats = analyze_commits(repo, dev, since, until)
            for ext, stats in file_stats.items():
                for key in stats:
                    report[dev]["by_file_type"][ext][key] += stats[key]
                    report[dev]["total"][key] += stats[key]
            # Only aggregate by_repo if per_repo is True
            if per_repo:
                for repo_name, ext_stats in repo_stats.items():
                    for ext, stats in ext_stats.items():
                        for key in stats:
                            report[dev]["by_repo"][repo_name][ext][key] += stats[key]
    return report


def print_cloc_style_report(report, per_repo=False):
    for dev, data in report.items():
        print(f"\n{'='*100}")
        print(f"Developer: {dev}")
        print(f"{'='*100}")
        print(f"{'Language':<20} {'Modifications':<15} {'Added':<10} {'Removed':<10} {'Renamed':<10} {'Line Adds':<10} {'Line Dels':<10} {'Line Changes':<15}")
        print(f"{'-'*20} {'-'*15} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*15}")
        for ext, stats in data["by_file_type"].items():
            lang = LANGUAGE_MAP.get(ext, ext)
            print(f"{lang:<20} {stats['modifications']:<15} {stats['added']:<10} {stats['removed']:<10} {stats['renamed']:<10} {stats['additions']:<10} {stats['deletions']:<10} {stats['changes']:<15}")
        print(f"{'-'*20} {'-'*15} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*15}")
        print(f"{'SUM':<20} {data['total']['modifications']:<15} {data['total']['added']:<10} {data['total']['removed']:<10} {data['total']['renamed']:<10} {data['total']['additions']:<10} {data['total']['deletions']:<10} {data['total']['changes']:<15}")
        if per_repo:
            print(f"\n{'-'*100}")
            print(f"    By Repository:")
            print(f"    {'-'*96}")
            for repo, ext_stats in data["by_repo"].items():
                print(f"\n    Repository: {repo}")
                print(f"    {'Language':<20} {'Modifications':<15} {'Added':<10} {'Removed':<10} {'Renamed':<10} {'Line Adds':<10} {'Line Dels':<10} {'Line Changes':<15}")
                print(f"    {'-'*20} {'-'*15} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*15}")
                for ext, stats in ext_stats.items():
                    lang = LANGUAGE_MAP.get(ext, ext)
                    print(f"    {lang:<20} {stats['modifications']:<15} {stats['added']:<10} {stats['removed']:<10} {stats['renamed']:<10} {stats['additions']:<10} {stats['deletions']:<10} {stats['changes']:<15}")


# Main execution
if __name__ == "__main__":
    since, until = get_time_range()
    devs = load_file_lines("devs.txt")
    repos = get_org_repos(ORGANIZATION) if USE_ORG_REPOS else load_file_lines(REPOS_FILE)

    # Probe repositories first
    print("Probing repositories...")
    valid_repos = probe_repositories(repos)
    if not valid_repos:
        print("No valid repositories found. Exiting.")
        exit(1)
    print(f"Found {len(valid_repos)} valid repositories: {', '.join(valid_repos)}")

    if DEBUG_MODE:
        devs = [DEBUG_DEV] if DEBUG_DEV else devs[:1]
        repos = [DEBUG_REPO] if DEBUG_REPO in valid_repos else valid_repos[:1]
        print(f"Debug Mode: Testing {devs[0]} on {repos[0]}")

    print(f"Generating report for {since} to {until} across branches {TARGET_BRANCHES}")
    report = generate_report(devs, valid_repos, since, until, per_repo=True)
    print_cloc_style_report(report, per_repo=True)
