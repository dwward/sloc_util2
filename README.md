# sloc_util2

curl -H "Authorization: token YOUR_GITHUB_TOKEN" \
     -H "Accept: application/vnd.github.v3+json" \
     "https://GITHUB_ENTERPRISE_URL/api/v3/repos/OWNER/REPO/commits?author=DEVELOPER_USERNAME"


curl -H "Authorization: token YOUR_GITHUB_TOKEN" \
     -H "Accept: application/vnd.github.v3+json" \
     "https://GITHUB_ENTERPRISE_URL/api/v3/repos/OWNER/REPO/commits/COMMIT_SHA"

{
  "files": [
    {
      "filename": "src/main/java/App.java",
      "additions": 10,
      "deletions": 2,
      "changes": 12
    }
  ]
}


import requests

GITHUB_TOKEN = "YOUR_GITHUB_TOKEN"
GITHUB_URL = "https://GITHUB_ENTERPRISE_URL/api/v3"
ORG = "YOUR_ORG"
DEVELOPER = "DEVELOPER_USERNAME"

headers = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

def get_repos():
    """Get all repositories in the organization."""
    url = f"{GITHUB_URL}/orgs/{ORG}/repos"
    response = requests.get(url, headers=headers)
    return [repo["name"] for repo in response.json()]

def get_commits(repo):
    """Get commits by a developer in a repo."""
    url = f"{GITHUB_URL}/repos/{ORG}/{repo}/commits?author={DEVELOPER}"
    response = requests.get(url, headers=headers)
    return response.json()

def get_commit_details(repo, sha):
    """Get commit details for a given commit SHA."""
    url = f"{GITHUB_URL}/repos/{ORG}/{repo}/commits/{sha}"
    response = requests.get(url, headers=headers)
    return response.json()

def main():
    report = []
    for repo in get_repos():
        commits = get_commits(repo)
        for commit in commits:
            sha = commit["sha"]
            details = get_commit_details(repo, sha)
            for file in details.get("files", []):
                report.append({
                    "repo": repo,
                    "commit_sha": sha,
                    "filename": file["filename"],
                    "changes": file["changes"],
                    "file_type": file["filename"].split(".")[-1] if "." in file["filename"] else "unknown"
                })

    import pandas as pd
    df = pd.DataFrame(report)
    print(df)
    df.to_csv("developer_commit_report.csv", index=False)

if __name__ == "__main__":
    main()
