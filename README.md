# GitHub Report Generator

## Purpose

The GitHub Report Generator is a Python tool designed to analyze commit activity in GitHub Enterprise repositories. It provides detailed statistics on developer contributions across specified branches ("main" and "develop"), including line additions, deletions, changes, and file-level actions (modifications, additions, removals, renames). The tool is portable, configurable, and optimized for offline use, making it ideal for teams needing to assess code contributions without internet access.

Key features:
- Aggregates commit stats by file type and optionally by repository.
- Excludes dot-prefixed files (e.g., `.gitignore`, `.codeowners`) for cleaner reports.
- Supports custom time ranges or a default lookback period.
- Probes repositories for validity before processing.
- Configurable via a properties file for flexibility.

## Installation

### Prerequisites
- No internet connection required after initial setup.
- Python 3.6+ (optional, only if not using the executable).

### Option 1: Portable Executable (Recommended)
1. Download: Obtain the pre-built executable package (`github_report.zip`) from the release page.
2. Extract: Unzip to a folder (e.g., `github_report/`).
   - Contains: `github_report` (Linux/macOS) or `github_report.exe` (Windows), `config.properties`, `devs.txt`, `repos.txt`.
3. Run: Double-click the executable or use the terminal (see Usage).

### Option 2: Source with Virtual Environment
1. Download: Get `github_report_source.zip`.
2. Extract: Unzip to a folder (e.g., `github_report_source/`).
3. Activate Environment:
   - Linux/macOS: `source myenv/bin/activate`
   - Windows: `myenv\Scripts\activate`
4. Run: `python github_report.py` (see Usage).

### Dependencies
- Bundled: `requests==2.31.0`, `python-dateutil==2.8.2`.
- No external installation needed; all dependencies are included.

## Usage Examples

### Basic Run (Executable)
Run the report with default settings:
[CODE BLOCK]
# Linux/macOS
./github_report
[CODE BLOCK]
[CODE BLOCK]
# Windows
github_report.exe
[CODE BLOCK]
- Uses `config.properties`, `devs.txt`, and `repos.txt` in the same directory.

### Custom Configuration
Edit `config.properties` to disable repo-level reporting:
[CODE BLOCK]
per_repo = False
[CODE BLOCK]
Then run:
[CODE BLOCK]
./github_report
[CODE BLOCK]

### Debug Mode
Set `debug_mode = True` in `config.properties` and specify a developer/repo:
[CODE BLOCK]
debug_mode = True
debug_dev = alice
debug_repo = myorg/project1
[CODE BLOCK]
Run:
[CODE BLOCK]
./github_report
[CODE BLOCK]

## Property Configurations

The `config.properties` file allows customization. Place it in the same directory as the executable or script. Example:
[CODE BLOCK]
[DEFAULT]
github_url = https://github.mycompany.com/api/v3
time_range = 2024-06-01:2024-12-31
last_x_months = 6
use_org_repos = False
organization = myorg
repos_file = repos.txt
debug_mode = False
debug_dev = alice
debug_repo = myorg/project1
per_repo = True
[CODE BLOCK]

| Property            | Description                                      | Default Value              |
|---------------------|--------------------------------------------------|----------------------------|
| `github_url`        | GitHub Enterprise API URL                       | `https://github.com/api/v3`|
| `time_range`        | Date range (YYYY-MM-DD:YYYY-MM-DD)              | `""` (uses `last_x_months`)|
| `last_x_months`     | Months to look back if no `time_range`          | `6`                        |
| `use_org_repos`     | Fetch all repos from an org (True/False)        | `False`                    |
| `organization`      | Org name (if `use_org_repos=True`)              | `""`                       |
| `repos_file`        | File listing repositories                       | `repos.txt`                |
| `debug_mode`        | Enable debug mode (True/False)                  | `False`                    |
| `debug_dev`         | Single developer for debug mode                 | `""`                       |
| `debug_repo`        | Single repo for debug mode                      | `""`                       |
| `per_repo`          | Generate repo-level report (True/False)         | `True`                     |

### Input Files
- devs.txt: List of developers (one per line, comments with `#` or `;` ignored).
[CODE BLOCK]
alice
bob
# charlie
[CODE BLOCK]
- repos.txt: List of repositories (one per line, comments ignored).
[CODE BLOCK]
myorg/project1
myorg/project2
# myorg/deprecated
[CODE BLOCK]

## Bonus: Screenshot Examples

### Screenshot 1: Full Report with `per_repo=True`
Description: Terminal output showing a complete report for "alice" with both file-type and repository-level stats.
[CODE BLOCK]
====================================================================================================
Developer: alice
====================================================================================================
Language             Modifications   Added      Removed    Renamed    Line Adds  Line Dels  Line Changes   
-------------------- --------------- ---------- ---------- ---------- ---------- ---------- ---------------
Python              2               1          0          0          80         40         120            
Markdown            1               0          1          0          20         10         30             
-------------------- --------------- ---------- ---------- ---------- ---------- ---------- ---------------
SUM                 3               1          1          0          100        50         150            
----------------------------------------------------------------------------------------------------
    By Repository:
    ------------------------------------------------------------------------------------------------

    Repository: myorg/project1
    Language             Modifications   Added      Removed    Renamed    Line Adds  Line Dels  Line Changes   
    -------------------- --------------- ---------- ---------- ---------- ---------- ---------- ---------------
    Python              2               1          0          0          80         40         120            
    Markdown            1               0          1          0          20         10         30             
[CODE BLOCK]
Caption: "Full report showing contributions across 'main' and 'develop' branches, including per-repository breakdown."

### Screenshot 2: Minimal Report with `per_repo=False`
Description: Terminal output with only file-type stats, omitting the repository section.
[CODE BLOCK]
====================================================================================================
Developer: alice
====================================================================================================
Language             Modifications   Added      Removed    Renamed    Line Adds  Line Dels  Line Changes   
-------------------- --------------- ---------- ---------- ---------- ---------- ---------- ---------------
Python              2               1          0          0          80         40         120            
Markdown            1               0          1          0          20         10         30             
-------------------- --------------- ---------- ---------- ---------- ---------- ---------- ---------------
SUM                 3               1          1          0          100        50         150            
[CODE BLOCK]
Caption: "Condensed report with `per_repo=False`, faster execution by skipping repository-level details."

### Screenshot 3: Debug Mode
Description: Terminal with debug output for a single developer and repo.
[CODE BLOCK]
Probing repositories...
Found 1 valid repositories: myorg/project1
Debug Mode: Testing alice on myorg/project1
Generating report for 2024-06-01T00:00:00Z to 2024-12-31T23:59:59Z across branches ['main', 'develop']
Fetched 5 unique commits for alice in myorg/project1 across ['main', 'develop']
====================================================================================================
Developer: alice
====================================================================================================
Language             Modifications   Added      Removed    Renamed    Line Adds  Line Dels  Line Changes   
-------------------- --------------- ---------- ---------- ---------- ---------- ---------- ---------------
Python              2               1          0          0          80         40         120            
-------------------- --------------- ---------- ---------- ---------- ---------- ---------- ---------------
SUM                 2               1          0          0          80         40         120            
[CODE BLOCK]
Caption: "Debug mode output focusing on 'alice' in 'myorg/project1', showing commit count."

## Notes
- Personal Access Token: Set `GITHUB_PAT` environment variable with your GitHub Enterprise token:
[CODE BLOCK]
export GITHUB_PAT=your_token_here
[CODE BLOCK]
- Portability: The executable includes all dependencies; config files are editable by users in the same folder.
- Exclusions: Dot-prefixed files (e.g., `.gitignore`) are automatically excluded from stats.

Enjoy analyzing your team’s contributions offline! For issues or feature requests, please contact the maintainer.
