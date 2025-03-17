from importlib.metadata import version
from multirun.core import run_multiprocess
from multirun.main import main

__version__ = version("pymultirun")
__all__ = ["main", "run_multiprocess", "__version__"]
