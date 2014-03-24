"""glymur - read, write, and interrogate JPEG 2000 files
"""
import sys

from glymur import version
__version__ = version.version

from .jp2k import Jp2k
from .jp2dump import jp2dump
