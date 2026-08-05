"""Main entry point for the expense tracker bot."""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from bot import main

if __name__ == "__main__":
    main()
