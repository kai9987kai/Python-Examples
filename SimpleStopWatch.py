# Author: OMKAR PATHAK
# This script helps to build a simple stopwatch application using Python's time module.

import time
import sys

# Handle Python 2/3 compatibility for input
try:
    input = raw_input
except NameError:
    pass

print('========================================')
print('           SIMPLE STOPWATCH             ')
print('========================================')
print('Press ENTER to start.')
print('Press Ctrl + C to stop and show final time.')
print('========================================')

starttime = None

try:
    input()
    starttime = time.time()
    print('Stopwatch started... Press Ctrl + C to stop.')
    while True:
        elapsed_time = time.time() - starttime
        mins, secs = divmod(elapsed_time, 60)
        hours, mins = divmod(mins, 60)
        time_str = f"{int(hours):02d}:{int(mins):02d}:{secs:04.1f}"
        print(f'Time Elapsed: {time_str}', end="\r")
        sys.stdout.flush()
        time.sleep(0.1)
except KeyboardInterrupt:
    print('\n\nStopwatch Stopped!')
    if starttime is not None:
        endtime = time.time()
        total_time = endtime - starttime
        mins, secs = divmod(total_time, 60)
        hours, mins = divmod(mins, 60)
        print(f'Total Time: {int(hours):02d}:{int(mins):02d}:{secs:05.2f} seconds')
    else:
        print('Stopwatch was not started.')

