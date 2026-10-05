import unittest
from sync_schedule import Deadlines, restore_upload_schedule, upload_decision, network_backoff, scheduler_backoff


class Clock:
    def __init__(self, wall=1000, monotonic=100):
        self.wall, self.mono = wall, monotonic
    def time(self): return self.wall
    def monotonic(self): return self.mono


class ScheduleTests(unittest.TestCase):
    def test_wall_clock_jumps_do_not_change_registered_deadline(self):
        for jump in (-10000, 10000):
            clock = Clock()
            deadlines = Deadlines(clock)
            self.assertFalse(deadlines.due('upload', 1600))
            clock.wall += jump
            clock.mono += 599
            self.assertFalse(deadlines.due('upload', 1600))
            clock.mono += 1
            self.assertTrue(deadlines.due('upload', 1600))

    def test_changed_target_and_restart(self):
        clock = Clock()
        deadlines = Deadlines(clock)
        self.assertFalse(deadlines.due('upload', 1600))
        clock.wall += 100; clock.mono += 100
        self.assertFalse(deadlines.due('upload', 1700))
        self.assertEqual(deadlines.targets['upload'][1], 800)
        restarted = Deadlines(clock)
        self.assertEqual(restarted.due('upload', 1700), False)
        self.assertTrue(restarted.due('missed', 900))

    def test_intervals_and_legacy_configuration(self):
        for interval in (60, 300, 600, 900, 1800, 3600):
            old = {'started_at': 1000, 'last_attempt_at': 1200, 'interval': 42,
                   'next_at': 1242, 'retry_at': 1555, 'failures': 3}
            restored = restore_upload_schedule(old, interval)
            self.assertEqual(restored['next_at'], 1200 + interval)
            self.assertEqual(restored['retry_at'], 1555)
            self.assertEqual(old['next_at'], 1242)
            restored['next_at'] = 9876
            self.assertEqual(restore_upload_schedule(restored, interval)['next_at'], 9876)

    def test_first_start_target(self):
        self.assertEqual(restore_upload_schedule({'started_at': 1000}, 600)['next_at'], 1600)

    def test_no_data_and_manual_does_not_bypass_backoff(self):
        due = lambda key, target: target <= 1000
        self.assertEqual(upload_decision(False, True, 2000, 900, due), 'no_data')
        self.assertEqual(upload_decision(True, True, 2000, 900, due), 'backoff')
        self.assertEqual(upload_decision(True, False, 0, 2000, due), 'waiting')
        self.assertEqual(upload_decision(True, True, 0, 2000, due), 'ready')
        self.assertEqual(upload_decision(True, False, 900, 2000, due), 'ready')

    def test_backoff_sequences_and_caps(self):
        self.assertEqual([network_backoff(n) for n in range(1, 8)], [60, 120, 240, 480, 600, 600, 600])
        self.assertEqual([scheduler_backoff('internal', n) for n in range(1, 8)], [5, 10, 20, 40, 60, 60, 60])
        self.assertEqual(scheduler_backoff('storage', 100), 5)
        self.assertEqual(scheduler_backoff('network', 100), 5)
