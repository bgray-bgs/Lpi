from gpiozero import LED

light = LED(18, active_high=True, initial_value=False)

# Disable automatic cleanup on exit
light._pin.close = lambda: None

light.on()
print("Light turned ON (latched)")
