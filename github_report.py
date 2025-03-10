import requests
from datetime import datetime
from dateutil.relativedelta import relativedelta
import configparser
import os
import collections
import argparse

# Argument parser for command-line inputs
parser = argparse.ArgumentParser(description="GitHub Enterprise Commit Report Generator")
parser.add_argument("--token", required=True, help="GitHub Personal Access Token")
args = parser.parse_args()

# Load configuration (excluding token)
config = configparser.ConfigParser(allow_no_value=True)
config.read('config.properties')

# GitHub API setup
GITHUB_URL = config.get('DEFAULT', 'github_url')
TOKEN = args.token  # Use token from command-line argument
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"}

# Report settings
TIME_RANGE = config.get('DEFAULT', 'time_range')
LAST_X_MONTHS = config.getint('DEFAULT', 'last_x_months')
USE_ORG_REPOS = config.getboolean('DEFAULT', 'use_org_repos')
ORGANIZATION = config.get('DEFAULT', 'organization') if USE_ORG_REPOS else None
DEVS_FILE = config.get('DEFAULT', 'devs_file')
REPOS_FILE = config.get('DEFAULT', 'repos_file')

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

# Helper functions
def load_file_lines(file_path):
    with open(file_path, 'r') as f:
        return [line.strip() for line in f if line.strip()]

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

def get_org_repos(org):
    repos = []
    url = f"{GITHUB_URL}/orgs/{org}/repos?per_page=100"
    while url:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        repos.extend([repo['full_name'] for repo in response.json()])
        url = response.links.get('next', {}).get('url')
    return repos

def get_commits(repo, author, since, until):
    url = f"{GITHUB_URL}/repos/{repo}/commits?author={author}&since={since}&until={until}&per_page=100"
    print(f"Fetching commits: {url}")
    commits = []
    while url:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        commits.extend(response.json())
        url = response.links.get('next', {}).get('url')
    return commits

def get_commit_details(repo, sha):
    url = f"{GITHUB_URL}/repos/{repo}/commits/{sha}"
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    return response.json()

def analyze_commits(repo, author, since, until):
    commits = get_commits(repo, author, since, until)
    file_type_stats = collections.defaultdict(lambda: {"additions": 0, "deletions": 0, "changes": 0})
    per_repo_stats = {repo: collections.defaultdict(lambda: {"additions": 0, "deletions": 0, "changes": 0})}

    for commit in commits:
        sha = commit["sha"]
        commit_data = get_commit_details(repo, sha)
        for file in commit_data.get("files", []):
            ext = file["filename"].split(".")[-1] if "." in file["filename"] else "no_extension"
            additions = file.get("additions", 0)
            deletions = file.get("deletions", 0)
            changes = file.get("changes", 0)
            file_type_stats[ext]["additions"] += additions
            file_type_stats[ext]["deletions"] += deletions
            file_type_stats[ext]["changes"] += changes
            per_repo_stats[repo][ext]["additions"] += additions
            per_repo_stats[repo][ext]["deletions"] += deletions
            per_repo_stats[repo][ext]["changes"] += changes
    return file_type_stats, per_repo_stats

def generate_report(devs, repos, since, until, per_repo=False):
    report = {}
    for dev in devs:
        report[dev] = {
            "total": {"additions": 0, "deletions": 0, "changes": 0},
            "by_file_type": collections.defaultdict(lambda: {"additions": 0, "deletions": 0, "changes": 0}),
            "by_repo": collections.defaultdict(lambda: collections.defaultdict(lambda: {"additions": 0, "deletions": 0, "changes": 0}))
        }
        for repo in repos:
            file_stats, repo_stats = analyze_commits(repo, dev, since, until)
            for ext, stats in file_stats.items():
                for key in stats:
                    report[dev]["by_file_type"][ext][key] += stats[key]
                    report[dev]["total"][key] += stats[key]
            for repo_name, ext_stats in repo_stats.items():
                for ext, stats in ext_stats.items():
                    for key in stats:
                        report[dev]["by_repo"][repo_name][ext][key] += stats[key]
    return report

def print_cloc_style_report(report, per_repo=False):
    for dev, data in report.items():
        print(f"\n{'='*80}")
        print(f"Developer: {dev}")
        print(f"{'='*80}")
        print(f"{'Language':<20} {'Files Modified':<15} {'Added':<10} {'Deleted':<10} {'Total Changes':<15}")
        print(f"{'-'*20} {'-'*15} {'-'*10} {'-'*10} {'-'*15}")
        file_count = collections.defaultdict(int)
        for commit in data["by_repo"].values():
            for ext in commit:
                file_count[ext] += 1
        for ext, stats in data["by_file_type"].items():
            lang = LANGUAGE_MAP.get(ext, ext)
            print(f"{lang:<20} {file_count[ext]:<15} {stats['additions']:<10} {stats['deletions']:<10} {stats['changes']:<15}")
        print(f"{'-'*20} {'-'*15} {'-'*10} {'-'*10} {'-'*15}")
        total_files = sum(file_count.values())
        print(f"{'SUM':<20} {total_files:<15} {data['total']['additions']:<10} {data['total']['deletions']:<10} {data['total']['changes']:<15}")
        if per_repo:
            print(f"\n{'-'*80}")
            print("By Repository:")
            print(f"{'-'*80}")
            for repo, ext_stats in data["by_repo"].items():
                print(f"\nRepository: {repo}")
                print(f"{'Language':<20} {'Added':<10} {'Deleted':<10} {'Total Changes':<15}")
                print(f"{'-'*20} {'-'*10} {'-'*10} {'-'*15}")
                for ext, stats in ext_stats.items():
                    lang = LANGUAGE_MAP.get(ext, ext)
                    print(f"{lang:<20} {stats['additions']:<10} {stats['deletions']:<10} {stats['changes']:<15}")

# Main execution
if __name__ == "__main__":
    since, until = get_time_range()
    devs = load_file_lines(DEVS_FILE)
    repos = get_org_repos(ORGANIZATION) if USE_ORG_REPOS else load_file_lines(REPOS_FILE)

    if DEBUG_MODE:
        devs = [DEBUG_DEV]
        repos = [DEBUG_REPO]
        print(f"Debug Mode: Testing {DEBUG_DEV} on {DEBUG_REPO}")

    print(f"Generating report for {since} to {until}")
    report = generate_report(devs, repos, since, until, per_repo=True)
    print_cloc_style_report(report, per_repo=True)
