#!/usr/bin/python3

# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU Lesser General Public License as published by the Free
# Software Foundation; either version 3 of the License, or (at your option) any
# later version.  See http://www.gnu.org/copyleft/lgpl.html for the full text
# of the license.

# Based on the file https://raw.githubusercontent.com/martinpitt/python-dbusmock/b4ea4e0/tests/test_networkmanager.py
# from python-dbusmock

import unittest
import sys
import subprocess
import dbus
import dbusmock
import os

from time import sleep

import plumbum
from plumbum import FG, BG

from plumbum.cmd import curl
python = plumbum.local["env/bin/python"]
pac4cli = python["main.py"]

from dbusmock.templates.networkmanager import DeviceState
from dbusmock.templates.networkmanager import NM80211ApSecurityFlags
from dbusmock.templates.networkmanager import InfrastructureMode
from dbusmock.templates.networkmanager import NMActiveConnectionState
from dbusmock.templates.networkmanager import (MANAGER_IFACE,
                                               SETTINGS_OBJ, SETTINGS_IFACE)


class TestProxyConfigurations(dbusmock.DBusTestCase):
    '''Test different ways of establishing the proxy'''

    @classmethod
    def setUpClass(klass):
        klass.start_system_bus()
        klass.dbus_con = klass.get_dbus(True)
        os.environ['G_DEBUG'] = 'fatal-warnings,fatal-criticals'

    def setUp(self):
        (self.p_mock, self.obj_networkmanager) = self.spawn_server_template(
            'networkmanager',
            {'NetworkingEnabled': True, 'WwanEnabled': False},
            stdout=subprocess.PIPE)
        self.dbusmock = dbus.Interface(self.obj_networkmanager,
                                       dbusmock.MOCK_IFACE)
        self.settings = dbus.Interface(
            self.dbus_con.get_object(MANAGER_IFACE, SETTINGS_OBJ),
            SETTINGS_IFACE)

    def tearDown(self):
        self.p_mock.terminate()
        self.p_mock.wait()

    def test_direct_proxy(self):
        proxy = pac4cli["-F", "DIRECT", "-p", "23128"] & BG
        sleep(3)
        try:
            with plumbum.local.env(http_proxy="localhost:23128"):
                curl("http://www.booking.com")
                self.assertTrue(True)
        finally:
            proxy.proc.kill()

    def test_proxied_proxy(self):
        proxy1 = pac4cli["-F", "DIRECT", "-p", "23128"] & BG
        proxy2 = pac4cli["-F", "PROXY localhost:23128", "-p", "23129"] & BG

        sleep(3)
        try:
            with plumbum.local.env(http_proxy="localhost:23129"):
                curl("http://www.booking.com")
                self.assertTrue(True)
        finally:
            proxy2.proc.kill()
            proxy1.proc.kill()

    def test_proxy_from_dhcp_wpad(self):
        # set up mock dbus with dhcp settings
        wifi1 = self.dbusmock.AddWiFiDevice('mock_WiFi1', 'wlan0',
                                            DeviceState.ACTIVATED)
        ap1 = self.dbusmock.AddAccessPoint(
            wifi1, 'Mock_AP1', 'The_SSID', '00:23:F8:7E:12:BB',
            InfrastructureMode.NM_802_11_MODE_INFRA, 2425, 5400, 82,
            NM80211ApSecurityFlags.NM_802_11_AP_SEC_KEY_MGMT_PSK)
        con1 = self.dbusmock.AddWiFiConnection(wifi1, 'Mock_Con1', 'The_SSID', '')
        active_con1 = self.dbusmock.AddActiveConnection(
            [wifi1], con1, ap1, 'Mock_Active1',
            NMActiveConnectionState.NM_ACTIVE_CONNECTION_STATE_ACTIVATED)

        self.dbusmock.AddObject(
            '/org/freedesktop/NetworkManager/DHCP4Config/1',
            'org.freedesktop.NetworkManager.DHCP4Config',
            {
                'Options': {
                    'wpad': 'http://localhost:8080/wpad.dat',
                },
            },
            [],
        )
        conn_obj = dbus.Interface(
            self.dbus_con.get_object("org.freedesktop.NetworkManager", con1),
            dbusmock.MOCK_IFACE,
        )
        conn_obj.AddProperty(
            'org.freedesktop.NetworkManager.Connection.Active',
            'Dhcp4Config',
            '/org/freedesktop/NetworkManager/DHCP4Config/1',
        )

        # server for wpad.dat
        with plumbum.local.cwd("test/wpadserver"):
            static_server = python["-m", "http.server", "-p", "8080"] & BG
        # mock upstream proxy
        proxy1 = pac4cli["-F", "DIRECT", "-p", "23128"] & BG
        # proxy getting its config from DHCP
        proxy2 = pac4cli["-p", "23129"] & BG

        sleep(3)
        try:
            with plumbum.local.env(http_proxy="localhost:23129"):
                curl("http://www.booking.com")
                curl("http://www.google.com")
                self.assertTrue(True)
        finally:
            proxy2.proc.kill()
            proxy1.proc.kill()
            static_server.proc.kill()


if __name__ == '__main__':
    unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))