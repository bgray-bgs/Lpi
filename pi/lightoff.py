#!/usr/bin/env python3
# LPI Relay Control
# Version: 1.0.1
# Last updated: 2026-01-27

from gpiozero import LED

light = LED(18, active_high=True, initial_value=True)

# Keep GPIO latched after exit
light._pin.close = lambda: None

light.off()
print("Override OFF")