import math
import struct
import tkinter as tk
import unittest

from vertisea_plot_v7 import (
    TYPE_BATTERY_VOLTAGE, TYPE_CURRENT_STATS, TYPE_RPM, VertiSeaGUI,
)


class ChargingPlotTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.gui = VertiSeaGUI(self.root)

    def tearDown(self):
        self.root.destroy()

    def stats(self, timestamp, age, charge, integration, samples):
        return struct.pack(
            '<BHHHfffII', TYPE_CURRENT_STATS, timestamp, age, 50,
            charge, 20, integration, samples, 0,
        )

    def test_interval_current_power_and_battery(self):
        self.gui.buffer.extend(
            struct.pack('<BHH', TYPE_BATTERY_VOLTAGE, 100, 3200)
            + self.stats(100, 1, 2, 1, 800)
            + self.stats(200, 2, 6, 2, 1600)
        )
        self.gui._update_once()
        self.assertAlmostEqual(self.gui.charging_current_data[-1], 4)
        self.assertAlmostEqual(self.gui.charging_power_data[-1], 12.8)
        self.assertEqual(list(self.gui.battery_voltage_data), [3.2])
        for axis in (self.gui.charging_current_ax, self.gui.charging_power_ax,
                     self.gui.battery_ax):
            self.assertFalse(axis.get_autoscaley_on())

    def test_five_hz_interval_means_and_history(self):
        self.gui.buffer.extend(
            struct.pack('<BHH', TYPE_BATTERY_VOLTAGE, 100, 4000)
            + self.stats(100, 1, 10, 1, 600)
            + self.stats(120, 1, 46, 1.2, 720)
            + self.stats(140, 1, 70, 1.4, 840)
        )
        self.gui._update_once()
        self.assertAlmostEqual(self.gui.charging_current_data[-2], 180, places=3)
        self.assertAlmostEqual(self.gui.charging_current_data[-1], 120, places=3)
        self.assertAlmostEqual(self.gui.charging_power_data[-2], 720, places=3)
        self.assertAlmostEqual(self.gui.charging_power_data[-1], 480, places=3)
        self.assertAlmostEqual(self.gui.charging_time_data[-1]
                               - self.gui.charging_time_data[-2], 0.2)
        self.assertGreaterEqual(self.gui.charging_time_data.maxlen, 301)

    def test_reset_gap_and_stale_voltage(self):
        self.gui.buffer.extend(
            struct.pack('<BHH', TYPE_BATTERY_VOLTAGE, 100, 3200)
            + self.stats(100, 1, 2, 1, 800)
            + self.stats(200, 2, 6, 2, 1600)
            + self.stats(300, 0, 0, 0, 0)
            + self.stats(400, 1, 3, 1, 800)
            + self.stats(800, 5, 15, 5, 4000)
        )
        self.gui._update_once()
        self.assertTrue(math.isnan(self.gui.charging_current_data[-3]))
        self.assertEqual(self.gui.charging_current_data[-2], 3)
        self.assertTrue(math.isnan(self.gui.charging_power_data[-2]))
        self.assertTrue(math.isnan(self.gui.charging_current_data[-1]))

    def test_fixed_limits_and_shared_time(self):
        self.gui.buffer.extend(struct.pack('<BHH', TYPE_RPM, 10000, 1200))
        self.gui._update_once()
        self.assertTrue(all(axis.get_xlim() == (40, 100) for axis in self.gui._plot_axes))
        for axis, limits in (
            (self.gui.imu_ax, (-60, 60)), (self.gui.stab_ax, (-60, 60)),
            (self.gui.mech_ax, (-60, 60)), (self.gui.mech_ax2, (0, 1800)),
            (self.gui.charging_current_ax, (0, 200)),
            (self.gui.charging_power_ax, (0, 800)), (self.gui.battery_ax, (0, 4)),
        ):
            self.assertEqual(axis.get_ylim(), limits)

    def test_pause_keeps_receiving_and_resume_restores_view(self):
        self.gui.buffer.extend(struct.pack('<BHH', TYPE_RPM, 10000, 1000))
        self.gui._update_once()
        self.gui.toggle_pause()
        self.gui.buffer.extend(struct.pack('<BHH', TYPE_RPM, 11000, 1400))
        self.gui._update_once()
        self.gui._update_once()
        self.assertEqual(self.gui.rpm_data[-1], 1400)
        self.assertEqual(self.gui.rpm_var.get(), '1000 RPM')
        self.assertEqual(self.gui.mech_line_rpm.get_ydata()[-1], 1000)
        self.gui.toggle_pause()
        self.assertEqual(self.gui.rpm_var.get(), '1400 RPM')
        self.assertEqual(self.gui.mech_line_rpm.get_ydata()[-1], 1400)
        self.assertTrue(all(axis.get_xlim() == (50, 110) for axis in self.gui._plot_axes))


if __name__ == '__main__':
    unittest.main()