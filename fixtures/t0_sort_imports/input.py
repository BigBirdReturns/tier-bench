import sys, os
import json,time,datetime
from collections import defaultdict
import math
import typing as t

def main():
    data = {"argv0": os.path.basename(sys.argv[0]), "x": 2}
    print(json.dumps(data, sort_keys=True))

if __name__ == "__main__":
    main()
