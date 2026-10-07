import asyncio

from .plejd_device import PlejdInput, PlejdDeviceType
from ..ble import LastData
from ..ble.debug import rec_log

# Press-to-release duration above this is a long press. Confirmed live
# against a real mains-powered Plejd puck: a deliberate quick tap
# reliably released well under 500ms (observed ~135-400ms), and a
# deliberate hold-for-dim gesture released well over it (observed
# >10s, with no distinct "still held" packets in between - just a
# single press/release pair with a longer gap) - so a single duration
# threshold cleanly separates the two without any extra protocol
# support needed.
LONG_PRESS_THRESHOLD = 0.5


class PlejdButton(PlejdInput):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outputType = PlejdDeviceType.BUTTON
        self._press_time = None

    @property
    def button_id(self):
        return self.settings.input

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

                click_type = None
                if action == "press":
                    self._press_time = asyncio.get_running_loop().time()
                elif action == "release" and self._press_time is not None:
                    duration = asyncio.get_running_loop().time() - self._press_time
                    click_type = (
                        "long_press"
                        if duration > LONG_PRESS_THRESHOLD
                        else "single_press"
                    )
                    self._press_time = None

                rec_log(
                    f"BUTTON {addr=} {button=} {action=} {click_type=}", self.address
                )

                for listener in self._listeners:
                    listener(
                        {
                            **self._state,
                            "button": button,
                            "action": action,
                            "click_type": click_type,
                        }
                    )
            case _:
                return
