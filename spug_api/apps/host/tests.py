from django.test import SimpleTestCase

from apps.host.metrics import _parse_output


class HostMetricsParserTests(SimpleTestCase):
    def test_parses_sysfs_and_gpu_temperatures(self):
        output = '''cpu  100 0 20 800 10 0 0 0
MemTotal:       8388608 kB
MemAvailable:   4194304 kB
SwapTotal:            0 kB
SwapFree:             0 kB
SPUG_PROBE_NET
Inter-| Receive | Transmit
  eth0: 1024 0 0 0 0 0 0 0 2048 0 0 0 0 0 0 0
SPUG_PROBE_STAT2
cpu  120 0 30 850 10 0 0 0
SPUG_PROBE_NET
  eth0: 2048 0 0 0 0 0 0 0 4096 0 0 0 0 0 0 0
SPUG_PROBE_DISK
/dev/sda1 10485760 5242880 5242880 50% /
SPUG_PROBE_TEMP
Package id 0|62000
Core 0|57
invalid|999999
SPUG_PROBE_GPU
25, 1024, 8192, 71
'''

        result, _, _ = _parse_output(output)

        self.assertEqual(result['temperature']['max'], 62.0)
        self.assertEqual(result['temperature']['sensors'], [
            {'name': 'Package id 0', 'value': 62.0},
            {'name': 'Core 0', 'value': 57.0},
        ])
        self.assertEqual(result['gpu'][0]['temperature'], 71.0)

    def test_temperature_is_none_when_host_exposes_no_sensor(self):
        output = '''cpu  100 0 20 800 10 0 0 0
SPUG_PROBE_NET
SPUG_PROBE_STAT2
cpu  120 0 30 850 10 0 0 0
SPUG_PROBE_NET
SPUG_PROBE_DISK
SPUG_PROBE_TEMP
SPUG_PROBE_GPU
'''

        result, _, _ = _parse_output(output)

        self.assertIsNone(result['temperature'])
        self.assertEqual(result['gpu'], [])
