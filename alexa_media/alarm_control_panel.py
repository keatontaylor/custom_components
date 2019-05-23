#!/usr/bin/env python
# -*- coding: utf-8 -*-
#  SPDX-License-Identifier: Apache-2.0
"""
Alexa Devices Alarm Control Panel using Guard Mode.

For more details about this platform, please refer to the documentation at
https://community.home-assistant.io/t/echo-devices-alexa-as-media-player-testers-needed/58639
"""
import logging
from typing import List  # noqa pylint: disable=unused-import
from homeassistant import util

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanel
)
from homeassistant.const import (
    STATE_ALARM_ARMED_AWAY, STATE_ALARM_ARMED_HOME,
    STATE_ALARM_DISARMED)

from . import (
    DOMAIN as ALEXA_DOMAIN,
    DATA_ALEXAMEDIA,
    MIN_TIME_BETWEEN_SCANS, MIN_TIME_BETWEEN_FORCED_SCANS,
    hide_email)

_LOGGER = logging.getLogger(__name__)

DEPENDENCIES = [ALEXA_DOMAIN]

def setup_platform(hass, config, add_devices_callback,
                   discovery_info=None):
    """Set up the Alexa alarm control panel platform."""
    devices = []  # type: List[AlexaAlarmControlPanel]
    for account, account_dict in (hass.data[DATA_ALEXAMEDIA]
                                  ['accounts'].items()):
        alexa_client = AlexaAlarmControlPanel(account_dict['login_obj'],
                                              hass)  \
                                              # type: AlexaAlarmControlPanel
        devices.append(alexa_client)
        (hass.data[DATA_ALEXAMEDIA]
         ['accounts']
         [account]
         ['entities']
         ['alarm_control_panel']) = alexa_client
    _LOGGER.debug("Adding %s", devices)
    add_devices_callback(devices, True)
    return True


class AlexaAlarmControlPanel(AlarmControlPanel):
    """Implementation of Alexa Media Player alarm control panel."""

    def __init__(self, login, hass):
        """Initialize the Alexa device."""
        from alexapy import AlexaAPI
        # Class info
        self._login = login
        self.alexa_api = AlexaAPI(self, login)
        self.alexa_api_session = login.session
        self.account = hide_email(login.email)
        self.hass = hass

        # Guard info
        self._appliance_id = None
        self._guard_entity_id = None
        self._friendly_name = "Alexa Guard"
        self._state = None
        self._should_poll = False
        self._attrs = {}

        data = self.alexa_api.get_guard_details(self._login)
        guard_dict = (data['locationDetails']
                      ['locationDetails']['Default_Location']
                      ['amazonBridgeDetails']['amazonBridgeDetails']
                      ['LambdaBridge_AAA/OnGuardSmartHomeBridgeService']
                      ['applianceDetails']['applianceDetails'])
        for key, value in guard_dict.items():
            if value['modelName'] == "REDROCK_GUARD_PANEL":
                self._appliance_id = value['applianceId']
                self._guard_entity_id = value['entityId']
                self._friendly_name += " " + self._appliance_id[-5:]
                _LOGGER.debug("Discovered Alexa Guard %s: %s %s",
                              self._friendly_name,
                              self._appliance_id,
                              self._guard_entity_id)
        # Register event handler on bus
        hass.bus.listen(('{}_{}'.format(ALEXA_DOMAIN,
                                        hide_email(login.email)))[0:32],
                        self._handle_event)
        self.refresh(no_throttle=True)

    def _handle_event(self, event):
        """Handle websocket events.

        Used instead of polling.
        """
        self.refresh()

    @util.Throttle(MIN_TIME_BETWEEN_SCANS, MIN_TIME_BETWEEN_FORCED_SCANS)
    def refresh(self):
        """Update device data.

        This is a per device refresh and for many Alexa devices can result in
        many refreshes from each individual device. This will call the
        AlexaAPI directly.

        Args:
        device (json): A refreshed device json from Amazon. For efficiency,
                       an individual device does not refresh if it's reported
                       as offline.
        """
        import json
        _LOGGER.debug("%s: Refreshing %s", self.account, self.name)
        state = None
        state_json = self.alexa_api.get_guard_state(self._login,
                                                    self._appliance_id)
        # _LOGGER.debug("%s: state_json %s", self.account, state_json)
        if state_json['deviceStates']:
            cap = state_json['deviceStates'][0]['capabilityStates']
            # _LOGGER.debug("%s: cap %s", self.account, cap)
            for item_json in cap:
                item = json.loads(item_json)
                # _LOGGER.debug("%s: item %s", self.account, item)
                if item['name'] == 'armState':
                    state = item['value']
                    # _LOGGER.debug("%s: state %s", self.account, state)
        elif state_json['errors']:
            _LOGGER.debug("%s: Error refreshing alarm_control_panel %s: %s",
                          self.account,
                          self.name,
                          json.dumps(state_json['errors']))
        if state is None:
            return
        if state == "ARMED_AWAY":
            self._state = STATE_ALARM_ARMED_AWAY
        elif state == "ARMED_STAY":
            self._state = STATE_ALARM_DISARMED
        else:
            self._state = STATE_ALARM_DISARMED
        _LOGGER.debug("%s: Alarm State: %s", self.account, self.state)

    def alarm_disarm(self, code=None):
        """Send disarm command.

        We use the arm_home state as Alexa does not have disarm state.
        """
        self.alarm_arm_home()
        self.schedule_update_ha_state()

    def alarm_arm_home(self, code=None):
        """Send arm home command."""
        self.alexa_api.set_guard_state(self._login,
                                       self._guard_entity_id,
                                       "ARMED_STAY")
        self.refresh(no_throttle=True)
        self.schedule_update_ha_state()


    def alarm_arm_away(self, code=None):
        """Send arm away command."""
        self.alexa_api.set_guard_state(self._login,
                                       self._guard_entity_id,
                                       "ARMED_AWAY")
        self.refresh(no_throttle=True)
        self.schedule_update_ha_state()

    @property
    def unique_id(self):
        """Return the unique ID."""
        return self._guard_entity_id

    @property
    def name(self):
        """Return the name of the device."""
        return self._friendly_name

    @property
    def state(self):
        """Return the state of the device."""
        return self._state

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return self._attrs

    @property
    def should_poll(self):
        """Return the polling state."""
        return self._should_poll or not (self.hass.data[DATA_ALEXAMEDIA]
                                         ['accounts'][self._login.email]
                                         ['websocket'])