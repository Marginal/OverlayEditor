# This file is part of glymur, a Python interface for accessing JPEG 2000.
#
# http://glymur.readthedocs.org
#
# Copyright 2013 John Evans
#
# License:  MIT

import sys
import numpy as np

from .lib import openjpeg as opj
from .lib import openjp2 as opj2

# Do not change the format of this next line!  Doing so risks breaking
# setup.py
version = "0.5.10"
version_tuple = version.split('.')


if opj.OPENJPEG is None and opj2.OPENJP2 is None:
    openjpeg_version = '0.0.0'
elif opj2.OPENJP2 is None:
    openjpeg_version = opj.version()
else:
    openjpeg_version = opj2.version()

openjpeg_version_tuple = openjpeg_version.split('.')

__doc__ = """\
This is glymur **%s**

* OPENJPEG version:  **%s**
""" % (version, openjpeg_version)

info = """\
Summary of glymur configuration
-------------------------------

glymur        %s
OPENJPEG      %s
Python        %s
sys.platform  %s
sys.maxsize   %s
numpy         %s
""" % (version,
       openjpeg_version,
       sys.version,
       sys.platform,
       'maxsize' in dir(sys) and sys.maxsize or sys.maxint,
       np.__version__)
