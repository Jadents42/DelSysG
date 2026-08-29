# Rui Santos & Sara Santos - Random Nerd Tutorials
# Complete project details:
# https://RandomNerdTutorials.com/raspberry-pi-pico-stepper-motor-micropython/
#
# Adapted to CircuitPython using board + digitalio only

import time
import board
import digitalio


class OutputPin:
    """Wrapper to provide a .value(0/1) interface"""
    def __init__(self, pin):
        self.pin = digitalio.DigitalInOut(pin)
        self.pin.direction = digitalio.Direction.OUTPUT
        self.pin.value = False

    def value(self, val):
        self.pin.value = bool(val)


class Motor:
    stepms = 10

    # To be defined by subclasses
    maxpos = 0
    states = []

    def __init__(self, p1, p2, p3, p4, stepms=None):
        self.pins = [
            OutputPin(p1),
            OutputPin(p2),
            OutputPin(p3),
            OutputPin(p4),
        ]

        if stepms is not None:
            self.stepms = stepms

        self._state = 0
        self._pos = 0

    def __repr__(self):
        return f"<{self.__class__.__name__} @ {self.pos}>"

    @property
    def pos(self):
        return self._pos
    
    def release(self):
        for pin in self.pins:
            pin.value(0)

    def reset(self):
        self._pos = 0

    def set_height(self, h):
        self._pos = h/25 * self.maxpos # 25 mm per revolution

    def get_height(self):
        return self._pos / self.maxpos * 25  # 25 mm per revolution

    def _step(self, dir):
        state = self.states[self._state]

        for i, val in enumerate(state):
            self.pins[i].value(val)

        self._state = (self._state + dir) % len(self.states)
        self._pos = (self._pos + dir) % self.maxpos

    def step(self, steps):
        direction = 1 if steps >= 0 else -1
        steps = abs(steps)

        for _ in range(steps):
            start = time.monotonic_ns()

            self._step(direction)

            elapsed_ms = (time.monotonic_ns() - start) / 1_000_000
            delay_ms = max(0, self.stepms - elapsed_ms)
            time.sleep(delay_ms / 1000)

    def step_until(self, target, dir=None):
        if not (0 <= target <= self.maxpos):
            raise ValueError(target)

        if dir is None:
            dir = 1 if target > self._pos else -1
            if abs(target - self._pos) > self.maxpos / 2:
                dir = -dir

        while self._pos != target:
            self.step(dir)

    def step_until_angle(self, angle, dir=None):
        if not (0 <= angle <= 360):
            raise ValueError(angle)

        target = int(angle / 360 * self.maxpos)
        self.step_until(target, dir)

    def step_degrees(self, degrees):
        if not (0 <= degrees <= 360):
            raise ValueError("Degrees should be between 0 and 360")

        steps_to_take = int(degrees / 360 * self.maxpos)
        self.reset()
        self.step(steps_to_take)

    def step_until_height(self, height, dir=-1):
        if not (0 <= height <= 25):
            raise ValueError(height)

        target = int(height / 25 * self.maxpos)
        self.step_until(target, dir)
        #self.release()


class FullStepMotor(Motor):
    stepms = 6
    maxpos = 2048
    states = [
        [1, 1, 0, 0],
        [0, 1, 1, 0],
        [0, 0, 1, 1],
        [1, 0, 0, 1],
    ]


class HalfStepMotor(Motor):
    stepms = 3
    maxpos = 4096
    states = [
        [1, 0, 0, 0],
        [1, 1, 0, 0],
        [0, 1, 0, 0],
        [0, 1, 1, 0],
        [0, 0, 1, 0],
        [0, 0, 1, 1],
        [0, 0, 0, 1],
        [1, 0, 0, 1],
    ]


# ---------------------------
# Example usage
# ---------------------------
if __name__ == "__main__":
    motor = FullStepMotor(
        board.D12,
        board.D16,
        board.D20,
        board.D21
    )

    motor.reset()
    time.sleep(1)
    motor.step_until_angle(90, -1)
    motor.step_until_height(5)  # Move to 5 mm
    time.sleep(1)
    motor.step_until_height(2)  # Move back to 0 mm
    motor.release()

    #motor.step_until_angle(90, -1)
    #motor.release()
