# Copyright 2015 Canonical Ltd
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

from nova.compute import power_state

LXD_POWER_STATES = {
    100: power_state.RUNNING,
    101: power_state.RUNNING,
    102: power_state.SHUTDOWN,
    103: power_state.RUNNING,
    104: power_state.SHUTDOWN,
    105: power_state.NOSTATE,
    106: power_state.NOSTATE,
    107: power_state.SHUTDOWN,
    108: power_state.CRASHED,
    109: power_state.SUSPENDED,
    110: power_state.SUSPENDED,
    111: power_state.SUSPENDED,
    200: power_state.RUNNING,
    400: power_state.CRASHED,
    401: power_state.NOSTATE
}
