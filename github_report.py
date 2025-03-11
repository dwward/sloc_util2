import requests
from datetime import datetime
from dateutil.relativedelta import relativedelta
import configparser
import os
import collections
import argparse
import urllib3

### PARALLELIZATION CHANGE: Import threading and concurrent.futures for parallel execution
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# Parse Access Token from either an environment variable or a parameter
TOKEN = os.environ.get("GITHUB_PAT")

if not TOKEN:
    parser = argparse.ArgumentParser(description="GitHub Enterprise Commit Report Generator")
    parser.add_argument("--token", required=False, help="GitHub Personal Access Token")
    args = parser.parse_args()
    TOKEN = args.token  # Use token from command-line argument

if not TOKEN:
    raise ValueError("Personal Access Token is not set.  Set GITHUB_PAT as environment variable, or pass as parameter using '--token <token>' ")

# Load configuration (excluding token)
config = configparser.ConfigParser(allow_no_value=True, inline_comment_prefixes=('#', ';'))
config.read('config.properties')

# Supress SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning) # TODO: put this in an error log

# GitHub API setup
GITHUB_URL = config.get('DEFAULT', 'github_url')
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"}

# Report settings
TIME_RANGE = config.get('DEFAULT', 'time_range', fallback='')
LAST_X_MONTHS = config.getint('DEFAULT', 'last_x_months')
USE_ORG_REPOS = config.getboolean('DEFAULT', 'use_org_repos')
ORGANIZATION = config.get('DEFAULT', 'organization') if USE_ORG_REPOS else None
DEVS_FILE = config.get('DEFAULT', 'devs_file')
REPOS_FILE = config.get('DEFAULT', 'repos_file')
DISABLE_SSL = config.get('DEFAULT', 'disable_ssl')
TARGET_BRANCHES = config.get('DEFAULT', 'branches', fallback='main').split(',')
IGNORE_NO_EXTENSION = config.getboolean('DEFAULT', 'ignore_no_extension', fallback=False)
SHOW_REPO_STATS = config.getboolean('DEFAULT', 'show_repo_states', fallback=False)
PER_REPO = config.getboolean('DEFAULT', 'show_repo_stats', fallback=True)

# Debug settings
DEBUG_MODE = config.getboolean('DEFAULT', 'debug_mode')
DEBUG_DEV = config.get('DEFAULT', 'debug_dev')
DEBUG_REPO = config.get('DEFAULT', 'debug_repo')

# Language mapping (extension to language name)
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

# -------------------------------------------------
# Loads lines from devs/repos file and ignore comments
# -------------------------------------------------
def load_file_lines(file_path):
    with open(file_path, 'r') as f:
        return [line.strip() for line in f if line.strip() and not line.strip().startswith(('#',  ';'))]

# ----------------------------------------------------
# Parse date ranges for the query from properties
# ----------------------------------------------------
def get_time_range():
    """Parse and validate the time range from config."""
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
    """Check if each is accessible"""
    valid_repos = []
    for repo in repos:
        url = f"{GITHUB_URL}/repos/{repo}"
        try:
            # HEAD request, minimal transfer
            response = requests.head(url, headers=HEADERS, verify=False) # TODO: Make this a flag, and find SSL fix
            response.raise_for_status()
            valid_repos.append(repo)
        except requests.exceptions.RequestException as e:
            print(f"\nSkipping repository '{repo}': {e}")
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
                response = requests.get(url, headers=HEADERS, verify=False, timeout=(3.0, 10.0))
                response.raise_for_status()
                branch_commits = response.json()
                for commit in branch_commits:
                    sha = commit["sha"]
                    if sha not in seen_shas:  # Skip duplicates
                        commits.append(commit)
                        seen_shas.add(sha)
                url = response.links.get('next', {}).get('url')
            except requests.exceptions.RequestException as e:
                #print(f"Warning: Could not fetch commits for branch '{branch}' in '{repo}': {e}")  # TODO: error log
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
            if file["filename"].startswith("."):
                continue
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

### PARALLELIZATION CHANGE: Helper function to process a single dev-repo pair
def process_dev_repo_pair(dev, repo, since, until, per_repo):
    """Process a single developer-repo pair and return stats for merging."""
    file_stats, repo_stats = analyze_commits(repo, dev, since, until)
    dev_stats = {
        "total": {"additions": 0, "deletions": 0, "changes": 0, "modifications": 0, "added": 0, "removed": 0, "renamed": 0},
        "by_file_type": collections.defaultdict(lambda: {
            "additions": 0, "deletions": 0, "changes": 0, "modifications": 0, "added": 0, "removed": 0, "renamed": 0
        })
    }
    if per_repo:
        dev_stats["by_repo"] = collections.defaultdict(lambda: collections.defaultdict(lambda: {
            "additions": 0, "deletions": 0, "changes": 0, "modifications": 0, "added": 0, "removed": 0, "renamed": 0
        }))

    # Aggregate file stats
    for ext, stats in file_stats.items():
        for key in stats:
            dev_stats["by_file_type"][ext][key] += stats[key]
            dev_stats["total"][key] += stats[key]

    # Aggregate repo stats if per_repo is enabled
    if per_repo:
        for repo_name, ext_stats in repo_stats.items():
            for ext, stats in ext_stats.items():
                for key in stats:
                    dev_stats["by_repo"][repo_name][ext][key] += stats[key]

    return dev, dev_stats

### PARALLELIZATION CHANGE: Modified generate_report to use ThreadPoolExecutor
def generate_report(devs, repos, since, until, per_repo=PER_REPO):
    report = {}
    # Initialize report structure for each developer
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

    # Create a thread pool to process dev-repo pairs in parallel
    max_workers = min(10, len(devs) * len(repos))  # Cap at 10 or total pairs, whichever is smaller
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit tasks for each dev-repo pair
        future_to_pair = {
            executor.submit(process_dev_repo_pair, dev, repo, since, until, per_repo): (dev, repo)
            for dev in devs for repo in repos
        }

        # Collect results as they complete
        for future in as_completed(future_to_pair):
            dev, repo = future_to_pair[future]
            try:
                dev_result_dev, dev_result_stats = future.result()
                # Merge results into the shared report (critical section)
                for ext, stats in dev_result_stats["by_file_type"].items():
                    for key in stats:
                        report[dev]["by_file_type"][ext][key] += stats[key]
                        report[dev]["total"][key] += stats[key]
                if per_repo:
                    for repo_name, ext_stats in dev_result_stats["by_repo"].items():
                        for ext, stats in ext_stats.items():
                            for key in stats:
                                report[dev]["by_repo"][repo_name][ext][key] += stats[key]
            except Exception as e:
                print(f"Error processing {dev}/{repo}: {e}")  # TODO: Log this properly

    return report

def print_cloc_style_report(report, per_repo=PER_REPO):
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
    devs = load_file_lines(DEVS_FILE)
    repos = get_org_repos(ORGANIZATION) if USE_ORG_REPOS else load_file_lines(REPOS_FILE)

    # Test repo access early
    print("Probing repositories...")
    valid_repos = probe_repositories(repos)
    if not valid_repos:
        print("No valid repositories found.  Exiting.") #: Todo error log
        exit(1)
    print(f"Found { len(valid_repos) } valid repositories: {', '.join(valid_repos)}")

    if DEBUG_MODE:
        devs = [DEBUG_DEV]
        repos = [DEBUG_REPO]
        print(f"Debug Mode: Testing {DEBUG_DEV} on {DEBUG_REPO}")

    print(f"Generating report for {since} to {until} across branches {TARGET_BRANCHES}")
    report = generate_report(devs, repos, since, until)
    print_cloc_style_report(report)
