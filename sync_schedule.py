"""Synchronization timing policy; no I/O, threads, credentials or snapshots."""
import time


class Deadlines:
    def __init__(self, clock=None):
        self.clock = clock if clock is not None else time
        self.targets = {}

    def due(self, key, target):
        # Convert each changed persisted wall target once, then ignore wall jumps.
        current = self.targets.get(key)
        if current is None or current[0] != target:
            current = (target, self.clock.monotonic() + max(0, target - self.clock.time()))
            self.targets[key] = current
        return self.clock.monotonic() >= current[1]


def restore_upload_schedule(schedule, interval):
    """Retain a saved target unless the interval changed or the target is absent."""
    result = dict(schedule)
    if result.get('interval') != interval or 'next_at' not in result:
        result['next_at'] = result.get('last_attempt_at', result['started_at']) + interval
    result['interval'] = interval
    return result


def upload_decision(has_pending, manual, retry_at, next_at, due):
    if not has_pending:
        return 'no_data'
    if retry_at and not due('upload-retry', retry_at):
        return 'backoff'
    if not manual and not retry_at and not due('upload', next_at):
        return 'waiting'
    return 'ready'


def network_backoff(failures):
    return min(600, 60 * 2 ** min(max(failures - 1, 0), 4))


def scheduler_backoff(category, consecutive_errors):
    if category != 'internal':
        return 5
    return min(60, 5 * 2 ** min(max(consecutive_errors - 1, 0), 4))
