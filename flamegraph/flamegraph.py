#!/usr/bin/env python3

import sys
import time
import os.path
import argparse
import threading
import traceback
import collections

def get_thread_name(ident):
  for th in threading.enumerate():
    if th.ident == ident:
      return th.getName()
  return str(ident) # couldn't find, return something useful anyways

def create_flamegraph_entry(thread_id, frame, collapse_recursion=False):
  threadname = get_thread_name(thread_id)

  # [1:] to skip first frame which is in this program
  if collapse_recursion:
    ret = []
    last = None
    for fn, ln, fun, text in traceback.extract_stack(frame)[1:]:
      if last != fun:
        ret.append('%s`%s' % (threadname, fun))
      last = fun
    return ';'.join(ret)

  return ';'.join('%s`%s' % (threadname, fun)
      for fn, ln, fun, text in traceback.extract_stack(frame)[1:])

class ProfileThread(threading.Thread):
  def __init__(self, fd, interval, collapse_recursion=False):
    threading.Thread.__init__(self, name="FlameGraph Thread")
    self.daemon = False

    self._fd = fd
    self._interval = interval
    self._collapse_recursion = collapse_recursion

    self._stats = collections.defaultdict(int)

    self._keeprunning = True
    self._stopevent = threading.Event()
  
  def run(self):
    my_thread = threading.get_ident()
    while self._keeprunning:
      for thread_id, frame in sys._current_frames().items():
        if thread_id == my_thread:
          continue
        #traceback.print_stack(frame, file=self._fd)
        entry = create_flamegraph_entry(thread_id, frame, self._collapse_recursion)
        self._stats[entry] += 1
        #self._fd.write('%f %s\n' % (time.clock(), entry))
        self._stopevent.wait(self._interval)  # basically a sleep for x seconds unless someone asked to stop

    for key in sorted(self._stats.keys()):
      self._fd.write('%s %d\n' % (key, self._stats[key]))
    self._fd.close()

  def num_frames(self, unique=False):
    if unique:
      return len(self._stats)
    else:
      return sum(self._stats.values())

  def stop(self):
    self._keeprunning = False
    self._stopevent.set()

def main():
  parser = argparse.ArgumentParser(prog='python -m flamegraph', description="Sample python stack frames for use with FlameGraph")
  parser.add_argument('script_file', metavar='script.py', type=str,
      help='Script to profile')
  parser.add_argument('script_args', metavar='[arguments...]', type=str, nargs=argparse.REMAINDER,
      help='Arguments for script')
  parser.add_argument('-o', '--output', nargs='?', type=argparse.FileType('w'), default=sys.stderr,
      help='Save stats to file. If not specified default is to stderr')
  parser.add_argument('-i', '--interval', type=float, nargs='?', default=0.001,
      help='Interval in seconds for collection of stackframes (default: %(default)ss)')
  parser.add_argument('-c', '--collapse-recursion', action='store_true', 
      help='Collapse simple recursion (function calls itself) into one stack frame in output')
  
  args = parser.parse_args()
  print(args)

  thread = ProfileThread(args.output, args.interval, args.collapse_recursion)

  if not os.path.isfile(args.script_file):
    parser.error('Script file does not exist: ' + args.script_file)

  sys.argv = [args.script_file] + args.script_args
  sys.path.insert(0, os.path.dirname(args.script_file))
  script_compiled = compile(open(args.script_file, 'rb').read(), args.script_file, 'exec')
  script_globals = {'__name__': '__main__', '__file__': args.script_file, '__package__': None}

  start_time = time.clock()
  thread.start()

  try:
    # exec docs say globals and locals should be same dictionary else treated as class context
    exec(script_compiled, script_globals, script_globals) 
  finally:
    thread.stop()
    thread.join()
    print('Elapsed Time: %2.2f seconds.  Collected %d stack frames (%d unique)'
        % (time.clock() - start_time, thread.num_frames(), thread.num_frames(unique=True)))

if __name__ == '__main__':
  main()