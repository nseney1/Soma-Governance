"""Allow `python3 -m soma_cli` when the soma script is not on PATH (BUG-041)."""
import sys

from soma_cli.cli import main

sys.exit(main())
