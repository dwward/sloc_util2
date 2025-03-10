github_report/
├── config.properties  # Configuration file
├── devs.txt          # List of developers
├── repos.txt         # List of repositories
├── github_report.py  # Main script (already provided)
└── requirements.txt  # Dependencies (unchanged)


Ranged Call
```
# GitHub Enterprise Configuration
github_url = https://github.mycompany.com/api/v3
token = ghp_abcdefghijklmnopqrstuvwxyz1234567890

# Report Settings
time_range = 2024-06-01:2024-12-31  # Ranged call from June 1, 2024, to December 31, 2024
last_x_months = 6                    # Ignored since time_range is set
use_org_repos = False
organization =

# File Paths
devs_file = devs.txt
repos_file = repos.txt

# Debugging
debug_mode = False
debug_dev =
debug_repo =
```

