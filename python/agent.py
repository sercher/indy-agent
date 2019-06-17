""" Module defining Agent class and related methods
"""
import asyncio
import base64
import json
import struct
import time
import traceback
from typing import Optional

import aiohttp
import socket
from indy import wallet, did, error, crypto, pairwise

import indy_sdk_utils as utils
from python_agent_utils.messages.message import Message
from router.family_router import FamilyRouter
from serializer.json_serializer import JSONSerializer as Serializer


class WalletConnectionException(Exception):
    pass


class Agent:
    """ Agent class storing all needed elements for agent operation.
    """
    def __init__(self, hostname=None, port=None):
        self.owner = None
        self.wallet_handle = None
        self.endpoint = None
        self.endpoint_vk = None
        self.ui_token = None
        self.pool_handle = None
        self.ui_socket = None
        self.initialized = False
        self.modules = {}
        self.family_router = FamilyRouter()
        self.message_queue = asyncio.Queue()
        self.admin_key = None
        self.agent_admin_key = None
        self.outbound_admin_message_queue = asyncio.Queue()
        self.offer_endpoint = None
        self.hostname = hostname
        self.port = port
        self.init_endpoint()

    def register_module(self, module):
        self.modules[module.FAMILY] = module(self)
        self.family_router.register(module.FAMILY, self.modules[module.FAMILY])

    def init_endpoint(self):
        if not self.hostname:
            self.hostname = socket.gethostbyname(socket.gethostname())
        self.endpoint = self.offer_endpoint = 'http://' + self.hostname
        self.endpoint += ':' + str(self.port) + '/indy' if self.port else '/indy'
        self.offer_endpoint += ':' + str(self.port) + '/offer' if self.port else '/offer'

    async def route_message_to_module(self, message):
        return await self.family_router.route(message)

    async def handle_incoming(self):
        try:
            wire_msg_bytes = await self.message_queue.get()

            msg = await self.unpack_wire_msg(wire_msg_bytes)
            if msg:
                return await self.route_message_to_module(msg)
        except Exception as e:
            print("\n\n--- Message Processing failed --- \n\n")
            traceback.print_exc()

    async def start(self):
        """ Message processing loop task.
        """
        while True:
            await self.handle_incoming()

    async def connect_wallet(self, agent_name, passphrase, ephemeral=False):
        """ Create if not already exists and open wallet.
        """

        self.owner = agent_name
        wallet_suffix = "wallet"
        if ephemeral:
            wallet_suffix = "ephemeral_wallet"
        wallet_name = '{}-{}'.format(self.owner, wallet_suffix)

        wallet_config = json.dumps({"id": wallet_name})
        wallet_credentials = json.dumps({"key": passphrase})

        # Handle ephemeral wallets
        if ephemeral:
            try:
                await wallet.delete_wallet(wallet_config, wallet_credentials)
                print("Removing ephemeral wallet.")
            except error.IndyError as e:
                if e.error_code is error.ErrorCode.WalletNotFoundError:
                    pass  # This is ok, and expected.
                else:
                    print("Unexpected Indy Error: {}".format(e))
            except Exception as e:
                print(e)
        # pylint: disable=bare-except

        try:
            await wallet.create_wallet(wallet_config, wallet_credentials)
        except error.IndyError as e:
            if e.error_code is error.ErrorCode.WalletAlreadyExistsError:
                pass  # This is ok, and expected.
            else:
                print("Unexpected Indy Error: {}".format(e))
        except Exception as e:
            print(e)

        try:
            if self.wallet_handle:
                await wallet.close_wallet(self.wallet_handle)

            self.wallet_handle = await wallet.open_wallet(
                wallet_config,
                wallet_credentials
            )

            (_, self.endpoint_vk) = await did.create_and_store_my_did(self.wallet_handle, "{}")

            self.initialized = True

        except Exception as e:
            print(e)
            print("Could not open wallet!")

            raise WalletConnectionException

    async def disconnect_wallet(self):
        """ Close the wallet and set back state to non initialised.
        """
        if self.wallet_handle:
            await wallet.close_wallet(self.wallet_handle)
        self.initialized = False
        self.owner = ''
        self.wallet_handle = None

    async def sign_agent_message_field(self, field_value, my_vk):
        timestamp_bytes = struct.pack(">Q", int(time.time()))

        sig_data_bytes = timestamp_bytes + json.dumps(field_value).encode('ascii')
        sig_data = base64.urlsafe_b64encode(sig_data_bytes).decode('ascii')

        signature_bytes = await crypto.crypto_sign(
            self.wallet_handle,
            my_vk,
            sig_data_bytes
        )
        signature = base64.urlsafe_b64encode(
            signature_bytes
        ).decode('ascii')

        return {
            "@type": "did:sov:BzCbsNYhMrjHiqZDTUASHg;spec/signature/1.0/ed25519Sha512_single",
            "signer": my_vk,
            "sig_data": sig_data,
            "signature": signature
        }

    async def unpack_and_verify_signed_agent_message_field(self, signed_field):
        signature_bytes = base64.urlsafe_b64decode(signed_field['signature'].encode('ascii'))
        sig_data_bytes = base64.urlsafe_b64decode(signed_field['sig_data'].encode('ascii'))
        sig_verified = await crypto.crypto_verify(
            signed_field['signer'],
            sig_data_bytes,
            signature_bytes
        )
        data_bytes = base64.urlsafe_b64decode(signed_field['sig_data'])
        timestamp = struct.unpack(">Q", data_bytes[:8])
        fieldjson = data_bytes[8:]
        return json.loads(fieldjson), sig_verified

    async def unpack_agent_message(self, wire_msg_bytes):
        if isinstance(wire_msg_bytes, str):
            wire_msg_bytes = bytes(wire_msg_bytes, 'utf-8')
        unpacked = json.loads(
            await crypto.unpack_message(
                self.wallet_handle,
                wire_msg_bytes
            )
        )

        from_key = None
        from_did = None
        if 'sender_verkey' in unpacked:
            from_key = unpacked['sender_verkey']
            from_did = await utils.did_for_key(self.wallet_handle, unpacked['sender_verkey'])

        to_key = unpacked['recipient_verkey']
        to_did = await utils.did_for_key(self.wallet_handle, unpacked['recipient_verkey'])

        msg = Serializer.deserialize(unpacked['message'])

        msg.context = {
            'from_did': from_did,  # Could be None
            'to_did': to_did,  # Could be None
            'from_key': from_key,  # Could be None
            'to_key': to_key
        }
        return msg

    async def send_message_to_agent(self, to_did, msg: Message):
        print("Sending:", msg)
        their_did = to_did

        pairwise_info = json.loads(await pairwise.get_pairwise(self.wallet_handle, their_did))
        pairwise_meta = json.loads(pairwise_info['metadata'])

        my_did = pairwise_info['my_did']
        their_endpoint = pairwise_meta['their_endpoint']
        their_vk = pairwise_meta['their_vk']

        my_vk = await did.key_for_local_did(self.wallet_handle, my_did)

        await self.send_message_to_endpoint_and_key(their_vk, their_endpoint, msg, my_vk)

    # used directly when sending to an endpoint without a known did
    async def send_message_to_endpoint_and_key(self, their_ver_key, their_endpoint,
                                               msg, my_ver_key=None):
        # If my_ver_key is omitted, anoncrypt is used inside pack.
        wire_message = await crypto.pack_message(
            self.wallet_handle,
            Serializer.serialize(msg).decode('utf-8'),
            [their_ver_key],
            my_ver_key
        )

        async with aiohttp.ClientSession() as session:
            headers = {
                'content-type': 'application/ssi-agent-wire'
            }
            async with session.post(their_endpoint, data=wire_message, headers=headers) as resp:
                if resp.status != 202:
                    print(resp.status)
                    print(await resp.text())

    async def setup_admin(self, admin_key):
        self.admin_key = admin_key
        self.agent_admin_key = await crypto.create_key(self.wallet_handle, '{}')
        print("Admin key: ", self.agent_admin_key)

    async def send_admin_message(self, msg: Message):
        if self.agent_admin_key and self.admin_key:
            msg = await crypto.pack_message(
                self.wallet_handle,
                Serializer.serialize(msg).decode('utf-8'),
                [self.admin_key],
                self.agent_admin_key
            )
            msg = msg.decode('ascii')
        else:
            msg = msg.as_json()

        await self.outbound_admin_message_queue.put(msg)

    async def unpack_wire_msg(self, wire_msg) -> Optional:
        # Try to unpack message assuming it's not encrypted
        msg = ""
        try:
            msg = Serializer.deserialize(wire_msg)
        except Exception as e:
            print("Message encrypted, attempting to unpack...")

        # TODO: More graceful checking here
        # (This is an artifact of the provisional wire format and connection protocol)
        if not isinstance(msg, Message) or "@type" not in msg:
            # Message IS encrypted so unpack it
            try:
                msg = await self.unpack_agent_message(wire_msg)
            except Exception as e:
                print('Failed to unpack message: {}\n\nError: {}'.format(wire_msg, e))
                traceback.print_exc()
                return None

        return msg
