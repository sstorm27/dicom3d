import multiprocessing
import sys

from dicom3d.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
