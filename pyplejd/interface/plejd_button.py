import asyncio

from .plejd_device import PlejdInput, PlejdDeviceType
from ..ble import LastData
from ..ble.debug import rec_log

# Threshold between a single and a long press, and also how long we
# wait for a release before declaring a press "long" on our own: the
# mesh's release packet for a press frequently never arrives at all
# (confirmed live against a real mains-powered puck - lost roughly 1 in
# 3-4 presses during testing), so classifying long press only once a
# release shows up would mean long presses regularly go unreported.
# Firing long_press from a timeout the instant this threshold passes -
# independent of whether a release ever follows - makes it reliable
# either way. A genuine short tap's release reliably does arrive well
# under this (observed ~135-400ms), so the timeout never fires for
# those.
LONG_PRESS_THRESHOLD = 0.5


class PlejdButton(PlejdInput):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outputType = PlejdDeviceType.BUTTON
        self._press_time = None
        self._long_press_fired = False
        self._cancel_long_press_timer = lambda: None

    @property
    def button_id(self):
        return self.settings.input

    def _notify(self, button, action, click_type):
        rec_log(f"BUTTON button={button} {action=} {click_type=}", self.address)
        for listener in self._listeners:
            listener(
                {
                    **self._state,
                    "button": button,
                    "action": action,
                    "click_type": click_type,
                }
            )

    def _long_press_timeout(self, button):
        self._cancel_long_press_timer = lambda: None
        self._long_press_fired = True
        self._notify(button, "long_press", "long_press")

    async def parse_lastdata(self, data: LastData):
        match data.command:
            case LastData.CMD_EVENT_FIRED:
                addr = int(data.payload[0])
                button = int(data.payload[1])
                if not (addr == self.deviceAddress and button == self.settings.input):
                    return
                action = "press"
                if len(data.payload) == 3 and data.payload[2] == 0:
                    action = "release"

                # Any fresh event for this button (press or release)
                # supersedes a still-pending long-press timeout from
                # whatever came before it.
                self._cancel_long_press_timer()

                if action == "press":
                    self._press_time = asyncio.get_running_loop().time()
                    self._long_press_fired = False
                    loop = asyncio.get_running_loop()
                    self._cancel_long_press_timer = loop.call_at(
                        loop.time() + LONG_PRESS_THRESHOLD,
                        self._long_press_timeout,
                        button,
                    ).cancel
                    # No HA-facing event for a bare press - see event.py
                    # for why only release/single_press/long_press are
                    # surfaced there.
                    return

                # action == "release"
                click_type = None
                if self._long_press_fired:
                    # Already reported as long_press via the timeout -
                    # this release just confirms it finally let go,
                    # nothing new to classify.
                    pass
                elif self._press_time is not None:
                    duration = asyncio.get_running_loop().time() - self._press_time
                    click_type = (
                        "long_press"
                        if duration > LONG_PRESS_THRESHOLD
                        else "single_press"
                    )
                self._press_time = None
                self._long_press_fired = False
                self._notify(button, "release", click_type)
            case _:
                return
