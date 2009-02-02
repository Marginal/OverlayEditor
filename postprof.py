import pstats
import os.path
import sys

#sys.stdout=open(os.path.splitext(sys.argv[1])[0]+'.txt','a')
s=pstats.Stats(sys.argv[1])
s.strip_dirs()
s.sort_stats('cumulative','time','nfl')
s.print_stats()
s.print_callers()
