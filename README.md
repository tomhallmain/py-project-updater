# py-project-updater

A Python tool for managing pip installations across multiple Python subprojects in a composite repository.

## Problem Statement

An extendible project repository exists, and the extensions contained inside not only have their own git indexes, but also have varying degrees of up-to-date status, and sometimes clash with the main project's dependencies. What is the fastest way to update the repository to the highest possible dependency version of each required package, and can a state diagram be presented to the user in a readable and helpful manner?

This tool addresses this challenge by:

- **Discovering subprojects** with their own `requirements.txt` files or Git repositories
- **Managing Git operations** to keep subprojects up-to-date
- **Installing dependencies** in the correct virtual environment
- **Detecting version conflicts** between main project and subprojects
- **Providing clear summaries** of what changes would be made (test mode) or have been made

## Features

- 🔍 **Automatic subproject discovery** - Finds all subprojects with `requirements.txt` or `.git` directories
- 🔄 **Git repository management** - Updates, fetches, and checks status of subproject repositories
- 📦 **Dependency installation** - Installs packages from subproject requirements in the correct virtual environment
- ⚠️ **Conflict detection** - Identifies version conflicts between main project and subprojects
- 🧪 **Test mode** - Preview changes before executing them
- 📊 **Comprehensive reporting** - Detailed summaries of operations, conflicts, and unique packages

## Installation

### From source

```bash
git clone <repository-url>
cd py-project-updater
pip install -e .
```

### Development installation

For development with testing and linting tools:

```bash
pip install -e ".[dev]"
# or
pip install -e . -r requirements-dev.txt
```

## Usage

### Basic usage

```bash
python -m py_project_updater --root-path /path/to/project --env-path /path/to/venv
```

### Test mode (default)

By default, the tool runs in test mode, showing what changes would be made without actually executing them:

```bash
python -m py_project_updater --root-path ./my-project --env-path ./venv
```

### Execute mode

To actually make changes (update Git repos, install packages):

```bash
python -m py_project_updater --root-path ./my-project --env-path ./venv --execute
```

### Git-only mode

Only perform Git operations, skip pip installations:

```bash
python -m py_project_updater --root-path ./my-project --env-path ./venv --git-only
```

### Advanced options

```bash
python -m py_project_updater \
    --root-path ./my-project \
    --env-path ./venv \
    --max-depth 4 \
    --ignore subproject1 \
    --ignore subproject2 \
    --log-level DEBUG \
    --log-file custom.log
```

### Command-line options

| Option | Description | Default |
|--------|-------------|---------|
| `--root-path PATH` | Root directory containing subprojects | **Required** |
| `--env-path PATH` | Path to Python virtual environment | **Required** |
| `--execute` | Actually make changes (default: test mode) | Test mode |
| `--git-only` | Only perform Git operations, skip pip | False |
| `--max-depth N` | Maximum depth to search for subprojects | 3 |
| `--ignore NAME` | Subproject names to ignore (repeatable) | None |
| `--log-level LEVEL` | Logging level (DEBUG\|INFO\|WARNING\|ERROR\|CRITICAL) | INFO |
| `--log-file PATH` | Log file path | `py_project_updater_<root_name>.log` |

## Project Structure

```
py-project-updater/
├── src/
│   └── py_project_updater/
│       ├── __init__.py
│       ├── __main__.py          # python -m py_project_updater
│       ├── cli.py                # CLI argument parsing
│       ├── config.py             # Configuration defaults
│       ├── orchestration.py      # SubprojectManager
│       ├── models/               # Data structures
│       │   ├── package.py        # Package model
│       │   ├── subproject.py     # SubprojectInfo, OperationResult
│       │   └── version.py        # Version, VersionSpecifier
│       ├── services/             # Domain logic
│       │   ├── finder.py         # SubprojectFinder
│       │   ├── git.py            # GitManager
│       │   ├── github_commit.py  # GitHubCommitChecker
│       │   ├── pip_installer.py  # PipInstaller
│       │   └── version_comparator.py
│       └── reporting/            # Test mode & summaries
│           └── test_mode.py      # TestModeManager
└── tests/                        # Test suite
    ├── conftest.py
    ├── test_models/
    ├── test_services/
    ├── test_reporting/
    └── test_integration/
```

## Testing

The project includes a comprehensive test suite covering:

- **Models**: Version compatibility, package parsing
- **Services**: Subproject discovery, Git operations, pip installation, version comparison
- **Reporting**: Test mode summaries and operation logging
- **Integration**: End-to-end workflows

### Running tests

```bash
# Install test dependencies
pip install -e ".[dev]"

# Run all tests
pytest

# Run with coverage
pytest --cov=py_project_updater --cov-report=html

# Run specific test file
pytest tests/test_models/test_version.py -v
```

## How It Works

1. **Discovery**: Scans the root directory for subprojects (directories with `requirements.txt` or `.git`)
2. **Analysis**: Parses requirements files and checks Git repository status
3. **Git Operations**: Updates or fetches changes for each subproject repository
4. **Dependency Resolution**: Compares package versions between main project and subprojects
5. **Installation**: Installs packages in the specified virtual environment
6. **Reporting**: Generates a comprehensive summary of operations, conflicts, and changes

## Requirements

- Python >= 3.9
- `packaging` library (for version parsing)
- Git (for repository operations)
- pip (for package installation)

## Development

### Setup

```bash
# Clone the repository
git clone <repository-url>
cd py-project-updater

# Install in development mode
pip install -e ".[dev]"
```

### Code quality

The project uses:
- **pytest** for testing
- **ruff** for linting
- **mypy** for type checking

Run linting and type checking:

```bash
ruff check src/
mypy src/
```

## License

[Add your license here]

## Contributing

[Add contribution guidelines here]
