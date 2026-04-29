"""Entry point for running pega_xml_downloader as a module via python -m."""

import sys

from pega_xml_downloader.main import main

if __name__ == "__main__":
    sys.exit(main())
