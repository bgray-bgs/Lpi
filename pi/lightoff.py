from gpiozero import LED

light = LED(18, active_high=True, initial_value=True)

# Disable automatic cleanup on exit
light._pin.close = lambda: None

light.off()
print("Light turned OFF (latched)")
