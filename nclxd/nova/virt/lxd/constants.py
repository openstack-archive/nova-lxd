from oslo.utils import units

from nova.compute import power_state

MAX_CONSOLE_BYTES = 100 * units.Ki

LXD_POWER_STATES = {
    'RUNNING': power_state.RUNNING,
    'STOPPED': power_state.SHUTDOWN,
    'STARTING': power_state.BUILDING,
    'STOPPING': power_state.SHUTDOWN,
    'ABORTING': power_state.CRASHED,
    'FREEZING': power_state.PAUSED,
    'FROZEN': power_state.SUSPENDED,
    'THAWED': power_state.PAUSED,
    'PENDING': power_state.BUILDING,
    'UNKNOWN': power_state.NOSTATE
}
