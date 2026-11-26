import sys

from dicom3d.app import main

# garda e necesara: procesele auxiliare ale segmentarii AI (multiprocessing "spawn",
# implicit pe Windows) reimporta modulul principal si ar porni inca o fereastra
if __name__ == "__main__":
    sys.exit(main())
