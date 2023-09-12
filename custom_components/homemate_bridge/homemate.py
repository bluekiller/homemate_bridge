"""A demonstration 'hub' that connects several devices."""
from __future__ import annotations
import socketserver
import json
import time
import struct
import binascii
import random
import string
import logging
import base64

from hexdump import hexdump
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from .const import (
    DATA_HANDLER_COVER,
    DATA_HANDLER_LIGHT,
    DATA_HANDLER_QUEUES,
    DATA_HANDLERS,
)

from .const import DOMAIN
from homeassistant.const import CONF_DEVICES

_LOGGER = logging.getLogger(__name__)
MAGIC = bytes([0x68, 0x64])
ID_UNSET = b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"

# Commands that the server sends, don't send an ACK when we see the switch ACK
CMD_SERVER_SENDS = [15, 98]


class HomematePacket:
    """
    The homemate packet format.
    """

    def __init__(self, data, keys):
        self.raw = data

        try:
            # Check the magic bytes
            self.magic = data[0:2]
            assert self.magic == MAGIC

            # Check the 'length' field
            self.length = struct.unpack(">H", data[2:4])[0]
            assert self.length == len(data)

            # Check the packet type
            self.packet_type = data[4:6]
            assert self.packet_type == bytes([0x70, 0x6B]) or self.packet_type == bytes(
                [0x64, 0x6B]
            )

            # Check the CRC32
            self.crc = binascii.crc32(data[42:]) & 0xFFFFFFFF
            data_crc = struct.unpack(">I", data[6:10])[0]
            assert self.crc == data_crc
        except AssertionError:
            _LOGGER.error("Bad packet:")
            hexdump(data)
            raise

        self.switch_id = data[10:42]

        self.json_payload = self.decrypt_payload(keys[self.packet_type[0]], data[42:])

    @staticmethod
    def decrypt_payload(key, encrypted_payload):
        """Decrypt the payload."""

        decryptor = Cipher(
            algorithms.AES(key), modes.ECB(), backend=default_backend()
        ).decryptor()

        data = decryptor.update(encrypted_payload)

        unpadder = padding.PKCS7(128).unpadder()
        unpad = unpadder.update(data)
        unpad += unpadder.finalize()

        # sometimes payload has an extra trailing null
        if unpad[-1] == 0x00:
            unpad = unpad[:-1]
        return json.loads(unpad.decode("utf-8"))

    @staticmethod
    def encrypt_payload(key, payload):
        """Encrypt the payload."""

        data = payload.encode("utf-8")

        padder = padding.PKCS7(128).padder()
        padded_data = padder.update(data)
        padded_data += padder.finalize()

        encryptor = Cipher(
            algorithms.AES(key), modes.ECB(), backend=default_backend()
        ).encryptor()

        encrypted_payload = encryptor.update(padded_data)
        return encrypted_payload

    @staticmethod
    def build_packet(packet_type, key, switch_id, payload):
        """Build the homemate packet"""
        encrypted_payload = HomematePacket.encrypt_payload(key, json.dumps(payload))
        crc = struct.pack(">I", binascii.crc32(encrypted_payload) & 0xFFFFFFFF)
        length = struct.pack(
            ">H",
            len(encrypted_payload) + len(MAGIC + packet_type + crc + switch_id) + 2,
        )

        packet = MAGIC + length + packet_type + crc + switch_id + encrypted_payload
        return packet


class HomemateTCPHandler(socketserver.BaseRequestHandler):
    """
    The RequestHandler class for our server.

    It is instantiated once per connection to the server, and must
    override the handle() method to implement communication to the
    client.
    """

    _initial_keys = {
        112: base64.b64decode("a2hnZ2Q1NDg2NVNOSkhHRg=="),
    }

    def __init__(self, *args, **kwargs):
        _LOGGER.debug("New handler")
        self.switch_id = None
        self.keys = dict(self.__class__._initial_keys.items())
        self.device_name = None
        self.softwareVersion = None
        self.hardwareVersion = None
        self.language = None
        self.modelId = None
        self._switch_on = None
        self.serial = 0
        self.uid = None

        # Reports if the roller is moving up or down.
        # >0 is up, <0 is down. This very much just for demonstration.
        self.moving = 0

        self.position = 0

        self._hass_light = None
        self._hass_cover = None
        self._callbacks = set()

        super().__init__(*args, **kwargs)

    @property
    def switch_on(self):
        """Return the light status"""
        return self._switch_on

    @switch_on.setter
    def switch_on(self, value):
        """Set the light status"""
        _LOGGER.debug("New switch state: %s", value)
        self._switch_on = value

    async def order_state_change(self, new_state):
        """Send the state update request"""
        control_type = None
        state_value = None
        if "light" in new_state:
            if self._switch_on is None:
                return
            control_type = "lightingCtrl"
            state_value = new_state["light"]
        elif "cover" in new_state:
            control_type = "motorCtrl"
            state_value = new_state["cover"]

        if not control_type:
            return

        payload = {
            "uid": self.uid,
            "clientSessionId": self.switch_id.decode("utf-8"),
            "ver": "4.9.22.308",
            "clientType": 1,
            "serial": self.serial,
            "fromMq": "true",
            control_type: state_value,
            "cmd": 98,
            "debugInfo": "Android_ZhiJia365_30_4.9.22.308",
            "userName": "a387fe7994e54e0095e8666a32cfd50a",
            "deviceId": self.switch_id.decode("utf-8"),
            "respByAcc": "false",
        }

        self.serial += 1

        packet = HomematePacket.build_packet(
            packet_type=bytes([0x64, 0x6B]),
            key=self.keys[0x64],
            switch_id=self.switch_id,
            payload=payload,
        )

        # PacketLog.record(packet, PacketLog.OUT, self.keys, self.client_address[0])

        _LOGGER.debug(
            "Sending state change for %s, new state %s", self.switch_id, new_state
        )
        _LOGGER.debug("Payload: %s", payload)

        self.request.sendall(packet)

    def register_callback(self, callback) -> None:
        """Register callback, called when Roller changes state."""
        self._callbacks.add(callback)

    def remove_callback(self, callback) -> None:
        """Remove previously registered callback."""
        self._callbacks.discard(callback)

    def finish(self):
        _LOGGER.debug(
            "Close connection to %s:%s", self.client_address[0], self.client_address[1]
        )
        self.server.hass.data[DOMAIN][DATA_HANDLERS].discard(self)

    def handle(self):
        # Close the connection if the switch doesn't send anything in 30 minutes
        # See !1
        self.request.settimeout(60 * 30)

        # self.request is the TCP socket connected to the client
        _LOGGER.info(
            "Got connection from %s:%s", self.client_address[0], self.client_address[1]
        )

        self._entity_queues = self.server.hass.data[DOMAIN][DATA_HANDLER_QUEUES]
        self._device_settings = self.server.hass.data[DOMAIN][CONF_DEVICES]
        self.server.hass.data[DOMAIN][DATA_HANDLERS].add(self)

        while True:
            data = self.request.recv(1024).strip()

            if not data:
                break
            # PacketLog.record(data, PacketLog.IN, self.keys, self.client_address[0])

            packet = HomematePacket(data, self.keys)

            _LOGGER.debug("%s sent payload: %s", self.switch_id, packet.json_payload)

            # Handle the ID field
            if self.switch_id is None and packet.switch_id == ID_UNSET:
                # Generate a new ID
                _LOGGER.debug("Generating a new switch ID")
                self.switch_id = "".join(
                    random.choice(string.ascii_lowercase + string.digits)
                    for _ in range(32)
                ).encode("utf-8")
            elif self.switch_id is None:
                # Switch has already been assigned an ID, save it
                _LOGGER.debug("Reusing existing ID")
                self.switch_id = packet.switch_id

            assert "cmd" in packet.json_payload
            assert "serial" in packet.json_payload

            if packet.json_payload["cmd"] in self.cmd_handlers:
                response = self.cmd_handlers[packet.json_payload["cmd"]](packet)
            elif packet.json_payload["cmd"] not in CMD_SERVER_SENDS:
                response = self.handle_default(packet)
            else:
                response = None

            if response is not None:
                response = self.format_response(packet, response)
                _LOGGER.debug("Sending response %s", response)
                response_packet = HomematePacket.build_packet(
                    packet_type=packet.packet_type,
                    key=self.keys[packet.packet_type[0]],
                    switch_id=self.switch_id,
                    payload=response,
                )

                # PacketLog.record(
                #     response_packet, PacketLog.OUT, self.keys, self.client_address[0]
                # )

                # Sanity check: Does our own packet look valid?
                # HomematePacket(response_packet, self.keys)
                self.request.sendall(response_packet)
                _LOGGER.debug("Successfully sent response")
            if self._hass_light is None and packet.json_payload["cmd"] == 32:
                # Setup the mqtt connection once we see the initial state update
                # Otherwise, we will get the previous state too early
                # and the switch will disconnect when we try to update it
                self._hass_light = self
                self._entity_queues[DATA_HANDLER_LIGHT].sync_q.put_nowait(
                    self._hass_light
                )
            if self._hass_cover is None and packet.json_payload["cmd"] == 32:
                # Setup the mqtt connection once we see the initial state update
                # Otherwise, we will get the previous state too early
                # and the switch will disconnect when we try to update it
                self._hass_cover = self
                self._entity_queues[DATA_HANDLER_COVER].sync_q.put_nowait(
                    self._hass_cover
                )

    def format_response(self, packet, response_payload):
        """Format the response"""
        response_payload["cmd"] = packet.json_payload["cmd"]
        response_payload["serial"] = packet.json_payload["serial"]
        response_payload["status"] = 0

        if "uid" in packet.json_payload:
            response_payload["uid"] = packet.json_payload["uid"]

        return response_payload

    def handle_hello(self, packet):
        """Handle hello"""
        for _ in ["softwareVersion", "hardwareVersion", "language", "modelId"]:
            setattr(self, _, packet.json_payload.get(_, None))

        if 0x64 not in self.keys:
            key = "".join(
                random.choice(
                    string.ascii_lowercase + string.ascii_uppercase + string.digits
                )
                for _ in range(16)
            )
            self.keys[0x64] = key.encode("utf-8")
        else:
            key = self.keys[0x64].decode("utf-8")

        return {"key": key}

    def handle_default(self, packet):
        """Return empty packet"""
        # If we don't recognise the packet, just send an "ACK"
        return {}

    def handle_heartbeat(self, packet):
        """Handle heartbeat"""
        self.uid = packet.json_payload["uid"]
        return {"utc": int(time.time())}

    def handle_state_update(self, packet):
        """Handle state update"""
        # if packet.json_payload['statusType'] != 0:
        #     _LOGGER.warning("Got unknown statusType: {}".format(packet.json_payload))

        if packet.json_payload["lightingState"] == "on":
            self.switch_on = True
            _LOGGER.debug("light on")
        else:
            self.switch_on = False
            _LOGGER.debug("light off")

        if packet.json_payload["motorState"] == "goingDown":
            self.moving = -1
        elif packet.json_payload["motorState"] == "goingUp":
            self.moving = 1
        else:
            self.moving = 0

        self.position = packet.json_payload["motorPosition"]
        _LOGGER.debug("current postion: %s", self.position)
        for callback in self._callbacks:
            callback()

        return None  # No response to this packet

    def handle_handshake(self, packet):
        """Handle handshake"""

        self.uid = packet.json_payload.get("uid", None)
        self.device_name = "Homemate Device " + self.client_address[0]

        if (
            "localIp" in packet.json_payload
            and packet.json_payload["localIp"] in self._device_settings
        ):
            # By default, we try to use the source IP of the socket as a stable identifier when connecting to HA
            # This may not always be the right thing to do (ie, if there is NAT involved, like when running in docker)
            # Fortunately, the switch sends the localIP in cmd 6, which happens before the cmd 32 wait for before
            # Connecting to MQTT

            localip = packet.json_payload["localIp"]
            _LOGGER.debug(
                "Updating device name for %s, localIp=%s", self.switch_id, localip
            )
            settings = self._device_settings[localip]
            if "name" not in settings:
                self.device_name = "Homemate Device " + localip
            else:
                self.device_name = settings["name"]

        _LOGGER.debug(
            "Switch id: %s, Device name: %s", self.switch_id, self.device_name
        )
        return self.handle_default(packet)

    @property
    def cmd_handlers(self):
        """Return the command halders"""
        return {
            0: self.handle_hello,
            32: self.handle_heartbeat,
            99: self.handle_state_update,
            6: self.handle_handshake,
        }
