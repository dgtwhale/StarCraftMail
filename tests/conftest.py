import logging
import sys

# Redirect log file to stdout during testing so CI does not need /var/log
logging.FileHandler = lambda f, *a, **kw: logging.StreamHandler(sys.stdout)
