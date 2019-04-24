import pytest
from test_suite.tests import expect_message, pack, unpack, sign_field, get_verified_data_from_signed_field, expect_silence
from indy import did
from test_suite.tests.connection import Connection
from test_suite.tests.did_doc import DIDDoc


expect_message_timeout = 30


@pytest.mark.asyncio
async def test_connection_started_by_tested_agent(config, wallet_handle, transport):
    invite_url = input('Input generated connection invite: ')

    invite_msg = Connection.Invite.parse(invite_url)

    print("\nReceived Invite:\n", invite_msg.pretty_print())

    # Create my information for connection
    (my_did, my_vk) = await did.create_and_store_my_did(wallet_handle, '{}')

    # Send Connection Request to inviter
    request = Connection.Request.build(
        'test-connection-started-by-tested-agent',
        my_did,
        my_vk,
        config.endpoint
    )

    print("\nSending Request:\n", request.pretty_print())

    await transport.send(
        invite_msg['serviceEndpoint'],
        await pack(
            wallet_handle,
            my_vk,
            invite_msg['recipientKeys'][0],
            request
        )
    )

    # Wait for response
    print("Awaiting response from tested agent...")
    response_bytes = await expect_message(transport, expect_message_timeout)

    response = await unpack(
        wallet_handle,
        response_bytes,
        expected_to_vk=my_vk
    )

    Connection.Response.validate_pre_sig(response)
    print("\nReceived Response (pre signature verification):\n", response.pretty_print())

    response['connection'] = await get_verified_data_from_signed_field(response['connection~sig'])

    Connection.Response.validate(response, request.id)
    print("\nReceived Response (post signature verification):\n", response.pretty_print())


async def get_connection_started_by_suite(config, wallet_handle, transport, label=None):
    if label is None:
        label = 'test-suite'

    connection_key = await did.create_key(wallet_handle, '{}')

    invite_str = Connection.Invite.build(label, connection_key, config.endpoint)

    print("\n\nInvitation encoded as URL: ", invite_str)

    print("Awaiting request from tested agent...")
    request_bytes = await expect_message(transport, expect_message_timeout) # A little extra time to copy-pasta

    request = await unpack(
        wallet_handle,
        request_bytes,
        expected_to_vk=connection_key
    )

    Connection.Request.validate(request)
    print("\nReceived request:\n", request.pretty_print())

    (their_did, their_vk, their_endpoint) = Connection.Request.parse(request)

    (my_did, my_vk) = await did.create_and_store_my_did(wallet_handle, '{}')

    response = Connection.Response.build(request.id, my_did, my_vk, config.endpoint)
    print("\nSending Response (pre signature packing):\n", response.pretty_print())

    response['connection~sig'] = await sign_field(wallet_handle, connection_key, response['connection'])
    del response['connection']
    print("\nSending Response (post signature packing):\n", response.pretty_print())

    await transport.send(
        their_endpoint,
        await pack(
            wallet_handle,
            my_vk,
            their_vk,
            response
        )
    )

    return {
        'my_did': my_did,
        'my_vk': my_vk,
        'their_did': their_did,
        'their_vk': their_vk,
        'their_endpoint': their_endpoint
    }


@pytest.mark.asyncio
async def test_connection_started_by_suite(config, wallet_handle, transport):
    await get_connection_started_by_suite(config, wallet_handle, transport, 'test-connection-started-by-suite')


@pytest.mark.asyncio
async def test_bad_connection_request_by_testing_agent(config, wallet_handle, transport):
    invite_url = input('Input generated connection invite: ')
    #invite_url = 'http://127.0.1.1:3001/indy?c_i=eyJAdHlwZSI6ICJkaWQ6c292OkJ6Q2JzTlloTXJqSGlxWkRUVUFTSGc7c3BlYy9jb25uZWN0aW9ucy8xLjAvaW52aXRhdGlvbiIsICJsYWJlbCI6ICIxIiwgInJlY2lwaWVudEtleXMiOiBbIjU1bk10cVBoUWFFV0ZicTMycnQ0M2NWcEtLd2ZnZ0pwUkFDc0VlVHZwQWh4Il0sICJzZXJ2aWNlRW5kcG9pbnQiOiAiaHR0cDovLzEyNy4wLjEuMTozMDAxL2luZHkiLCAiQGlkIjogIjNjYTNjOGNiLWJhNjYtNDQ4Ni1hYmE3LTY3M2NiOTg5MzAzOSJ9'

    invite_msg = Connection.Invite.parse(invite_url)

    print("\nReceived Invite:\n", invite_msg.pretty_print())

    # Create my information for connection
    (my_did, my_vk) = await did.create_and_store_my_did(wallet_handle, '{}')

    # Send a bad Connection Request to inviter by removing the DID from requst
    request = Connection.Request.build(
        'test-connection-started-by-tested-agent',
        my_did,
        my_vk,
        config.endpoint
    )

    request[Connection.CONNECTION].pop(DIDDoc.DID_DOC)

    print("\nSending Request:\n", request.pretty_print())

    await transport.send(
        invite_msg['serviceEndpoint'],
        await pack(
            wallet_handle,
            my_vk,
            invite_msg['recipientKeys'][0],
            request
        )
    )

    # Wait for response
    print("Awaiting response from tested agent...")
    await expect_silence(transport, expect_message_timeout)
