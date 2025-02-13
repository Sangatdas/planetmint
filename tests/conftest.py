# Copyright © 2020 Interplanetary Database Association e.V.,
# Planetmint and IPDB software contributors.
# SPDX-License-Identifier: (Apache-2.0 AND CC-BY-4.0)
# Code is Apache-2.0 and docs are CC-BY-4.0

"""Fixtures and setup / teardown functions

Tasks:
1. setup test database before starting the tests
2. delete test database after running the tests
"""
import json
import os
import random
import tempfile
import codecs
import pytest

from ipld import marshal, multihash
from collections import namedtuple
from logging import getLogger
from logging.config import dictConfig

from planetmint.backend.connection import Connection
from planetmint.backend.tarantool.sync_io.connection import TarantoolDBConnection
from transactions.common import crypto
from transactions.common.transaction_mode_types import BROADCAST_TX_COMMIT
from planetmint.abci.utils import key_from_base64
from planetmint.backend import schema, query
from transactions.common.crypto import key_pair_from_ed25519_key, public_key_from_ed25519_key
from planetmint.abci.block import Block
from planetmint.abci.rpc import MODE_LIST
from tests.utils import gen_vote
from planetmint.config import Config
from transactions.types.elections.validator_election import ValidatorElection  # noqa
from tendermint.abci import types_pb2 as types
from tendermint.crypto import keys_pb2

TEST_DB_NAME = "planetmint_test"

USER2_SK, USER2_PK = crypto.generate_key_pair()

# Test user. inputs will be created for this user. Cryptography Keys
USER_PRIVATE_KEY = "8eJ8q9ZQpReWyQT5aFCiwtZ5wDZC4eDnCen88p3tQ6ie"
USER_PUBLIC_KEY = "JEAkEJqLbbgDRAtMm8YAjGp759Aq2qTn9eaEHUj2XePE"


@pytest.fixture
def init_chain_request():
    pk = codecs.decode(b"VAgFZtYw8bNR5TMZHFOBDWk9cAmEu3/c6JgRBmddbbI=", "base64")
    val_a = types.ValidatorUpdate(power=10, pub_key=keys_pb2.PublicKey(ed25519=pk))
    return types.RequestInitChain(validators=[val_a])


def pytest_addoption(parser):
    from planetmint.backend.connection import BACKENDS

    backends = ", ".join(BACKENDS.keys())
    parser.addoption(
        "--database-backend",
        action="store",
        default=os.environ.get("PLANETMINT_DATABASE_BACKEND", "tarantool_db"),
        help="Defines the backend to use (available: {})".format(backends),
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "bdb(): Mark the test as needing Planetmint."
        "Planetmint will be configured such that the database and tables are available for an "
        "entire test session."
        "You need to run a backend (e.g. MongoDB) "
        "prior to running tests with this marker. You should not need to restart the backend "
        "in between tests runs since the test infrastructure flushes the backend upon session end.",
    )
    config.addinivalue_line(
        "markers",
        "abci(): Mark the test as needing a running ABCI server in place. Use this marker"
        "for tests that require a running Tendermint instance. Note that the test infrastructure"
        "has no way to reset Tendermint data upon session end - you need to do it manually."
        "Setup performed by this marker includes the steps performed by the bdb marker.",
    )


@pytest.fixture(autouse=True)
def _bdb_marker(request):
    if request.keywords.get("bdb", None):
        request.getfixturevalue("_bdb")


@pytest.fixture(autouse=True)
def _restore_config(_configure_planetmint):
    config_before_test = Config().init_config("tarantool_db")  # noqa


@pytest.fixture(scope="session")
def _configure_planetmint(request):
    from planetmint import config_utils

    test_db_name = TEST_DB_NAME
    # Put a suffix like _gw0, _gw1 etc on xdist processes
    xdist_suffix = getattr(request.config, "slaveinput", {}).get("slaveid")
    if xdist_suffix:
        test_db_name = "{}_{}".format(TEST_DB_NAME, xdist_suffix)

    # backend = request.config.getoption('--database-backend')
    backend = "tarantool_db"

    config = {"database": Config().get_db_map(backend), "tendermint": Config()._private_real_config["tendermint"]}
    config["database"]["name"] = test_db_name
    config = config_utils.env_config(config)
    config_utils.set_config(config)


@pytest.fixture(scope="session")
def _setup_database(_configure_planetmint):  # TODO Here is located setup database
    from planetmint.config import Config

    print("Initializing test db")
    dbname = Config().get()["database"]["name"]
    conn = Connection()

    schema.drop_database(conn, dbname)
    schema.init_database(conn, dbname)
    print("Finishing init database")

    yield

    print("Deleting `{}` database".format(dbname))
    schema.drop_database(conn, dbname)

    print("Finished deleting `{}`".format(dbname))


@pytest.fixture
def _bdb(_setup_database):
    from transactions.common.memoize import to_dict, from_dict
    from transactions.common.transaction import Transaction
    from .utils import flush_db
    from planetmint.config import Config

    conn = Connection()
    conn.close()
    conn.connect()
    yield
    dbname = Config().get()["database"]["name"]
    flush_db(conn, dbname)

    to_dict.cache_clear()
    from_dict.cache_clear()
    Transaction._input_valid.cache_clear()


# We need this function to avoid loading an existing
# conf file located in the home of the user running
# the tests. If it's too aggressive we can change it
# later.
@pytest.fixture
def ignore_local_config_file(monkeypatch):
    def mock_file_config(filename=None):
        return {}

    monkeypatch.setattr("planetmint.config_utils.file_config", mock_file_config)


@pytest.fixture
def reset_logging_config():
    # root_logger_level = getLogger().level
    root_logger_level = "DEBUG"
    dictConfig({"version": 1, "root": {"level": "NOTSET"}})
    yield
    getLogger().setLevel(root_logger_level)


@pytest.fixture
def user_sk():
    return USER_PRIVATE_KEY


@pytest.fixture
def user_pk():
    return USER_PUBLIC_KEY


@pytest.fixture
def user2_sk():
    return USER2_SK


@pytest.fixture
def user2_pk():
    return USER2_PK


@pytest.fixture
def alice():
    from transactions.common.crypto import generate_key_pair

    return generate_key_pair()


@pytest.fixture
def bob():
    from transactions.common.crypto import generate_key_pair

    return generate_key_pair()


@pytest.fixture
def bob_privkey(bob):
    return bob.private_key


@pytest.fixture
def bob_pubkey(carol):
    return bob.public_key


@pytest.fixture
def carol():
    from transactions.common.crypto import generate_key_pair

    return generate_key_pair()


@pytest.fixture
def carol_privkey(carol):
    return carol.private_key


@pytest.fixture
def carol_pubkey(carol):
    return carol.public_key


@pytest.fixture
def merlin():
    from transactions.common.crypto import generate_key_pair

    return generate_key_pair()


@pytest.fixture
def abci_fixture():
    from tendermint.abci import types_pb2

    return types_pb2


@pytest.fixture
def test_models():
    from planetmint.model.dataaccessor import DataAccessor

    return DataAccessor()


@pytest.fixture
def test_validator():
    from planetmint.application import Validator

    return Validator()


@pytest.fixture
def test_abci_rpc():
    from planetmint.abci.rpc import ABCI_RPC

    return ABCI_RPC()


@pytest.fixture
def b():
    from planetmint.application import Validator

    validator = Validator()
    validator.models.connection.close()
    validator.models.connection.connect()
    return validator


@pytest.fixture
def eventqueue_fixture():
    from multiprocessing import Queue

    return Queue()


@pytest.fixture
def b_mock(b, network_validators):
    b.models.get_validators = mock_get_validators(network_validators)
    return b


def mock_get_validators(network_validators):
    def validator_set(height):
        validators = []
        for public_key, power in network_validators.items():
            validators.append({"public_key": {"type": "ed25519-base64", "value": public_key}, "voting_power": power})
        return validators

    return validator_set


@pytest.fixture
def create_tx(alice, user_pk):
    from transactions.types.assets.create import Create

    name = f"I am created by the create_tx fixture. My random identifier is {random.random()}."
    assets = [{"data": multihash(marshal({"name": name}))}]
    return Create.generate([alice.public_key], [([user_pk], 1)], assets=assets)


@pytest.fixture
def signed_create_tx(alice, create_tx):
    return create_tx.sign([alice.private_key])


@pytest.fixture
def posted_create_tx(b, signed_create_tx, test_abci_rpc):
    res = test_abci_rpc.post_transaction(
        MODE_LIST, test_abci_rpc.tendermint_rpc_endpoint, signed_create_tx, BROADCAST_TX_COMMIT
    )
    assert res.status_code == 200
    return signed_create_tx


@pytest.fixture
def signed_transfer_tx(signed_create_tx, user_pk, user_sk):
    from transactions.types.assets.transfer import Transfer

    inputs = signed_create_tx.to_inputs()
    tx = Transfer.generate(inputs, [([user_pk], 1)], asset_ids=[signed_create_tx.id])
    return tx.sign([user_sk])


@pytest.fixture
def double_spend_tx(signed_create_tx, carol_pubkey, user_sk):
    from transactions.types.assets.transfer import Transfer

    inputs = signed_create_tx.to_inputs()
    tx = Transfer.generate(inputs, [([carol_pubkey], 1)], asset_ids=[signed_create_tx.id])
    return tx.sign([user_sk])


def _get_height(b):
    maybe_block = b.models.get_latest_block()
    return 0 if maybe_block is None else maybe_block["height"]


@pytest.fixture
def inputs(user_pk, b, alice):
    from transactions.types.assets.create import Create

    # create blocks with transactions for `USER` to spend
    for height in range(1, 4):
        transactions = [
            Create.generate(
                [alice.public_key], [([user_pk], 1)], metadata=multihash(marshal({"data": f"{random.random()}"}))
            ).sign([alice.private_key])
            for _ in range(10)
        ]
        tx_ids = [tx.id for tx in transactions]
        block = Block(app_hash="hash" + str(height), height=height, transactions=tx_ids)
        b.models.store_block(block._asdict())
        b.models.store_bulk_transactions(transactions)


@pytest.fixture
def db_config():
    return Config().get()["database"]


@pytest.fixture
def db_host(db_config):
    return db_config["host"]


@pytest.fixture
def db_port(db_config):
    return db_config["port"]


@pytest.fixture
def db_name(db_config):
    return db_config["name"]


@pytest.fixture
def db_conn():
    conn = Connection()
    conn.close()
    conn.connect()
    return conn


@pytest.fixture
def db_context(db_config, db_host, db_port, db_name, db_conn):
    DBContext = namedtuple("DBContext", ("config", "host", "port", "name", "conn"))
    return DBContext(
        config=db_config,
        host=db_host,
        port=db_port,
        name=db_name,
        conn=db_conn,
    )


@pytest.fixture
def tendermint_host():
    return os.getenv("PLANETMINT_TENDERMINT_HOST", "localhost")


@pytest.fixture
def tendermint_port():
    return int(os.getenv("PLANETMINT_TENDERMINT_PORT", 26657))


@pytest.fixture
def tendermint_ws_url(tendermint_host, tendermint_port):
    return "ws://{}:{}/websocket".format(tendermint_host, tendermint_port)


@pytest.fixture(autouse=True)
def _abci_http(request):
    if request.keywords.get("abci", None):
        request.getfixturevalue("abci_http")


@pytest.fixture
def abci_http(_setup_database, _configure_planetmint, abci_server, tendermint_host, tendermint_port):
    import requests
    import time

    for i in range(300):
        try:
            uri = "http://{}:{}/abci_info".format(tendermint_host, tendermint_port)
            requests.get(uri)
            return True

        except requests.exceptions.RequestException:
            pass
        time.sleep(1)

    return False


@pytest.fixture(scope="session")
def event_loop():
    import asyncio

    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def abci_server():
    from abci.server import ABCIServer

    # from tendermint.abci import types_pb2 as types_v0_34_11
    from planetmint.abci.application_logic import ApplicationLogic
    from planetmint.utils import Process

    app = ABCIServer(app=ApplicationLogic())
    abci_proxy = Process(name="ABCI", target=app.run)
    yield abci_proxy.start()
    abci_proxy.terminate()


@pytest.fixture
def wsserver_config():
    return Config().get()["wsserver"]


@pytest.fixture
def wsserver_scheme(wsserver_config):
    return wsserver_config["advertised_scheme"]


@pytest.fixture
def wsserver_host(wsserver_config):
    return wsserver_config["advertised_host"]


@pytest.fixture
def wsserver_port(wsserver_config):
    return wsserver_config["advertised_port"]


@pytest.fixture
def wsserver_base_url(wsserver_scheme, wsserver_host, wsserver_port):
    return "{}://{}:{}".format(wsserver_scheme, wsserver_host, wsserver_port)


@pytest.fixture
def unspent_output_0():
    return {
        "amount": 1,
        "asset_id": "e897c7a0426461a02b4fca8ed73bc0debed7570cf3b40fb4f49c963434225a4d",
        "condition_uri": "ni:///sha-256;RmovleG60-7K0CX60jjfUunV3lBpUOkiQOAnBzghm0w?fpt=ed25519-sha-256&cost=131072",
        "fulfillment_message": '{"asset":{"data":{"hash":"06e47bcf9084f7ecfd2a2a2ad275444a"}},"id":"e897c7a0426461a02b4fca8ed73bc0debed7570cf3b40fb4f49c963434225a4d","inputs":[{"fulfillment":"pGSAIIQT0Jm6LDlcSs9coJK4Q4W-SNtsO2EtMtQJ04EUjBMJgUAXKIqeaippbF-IClhhZNNaP6EIZ_OgrVQYU4mH6b-Vc3Tg-k6p-rJOlLGUUo_w8C5QgPHNRYFOqUk2f1q0Cs4G","fulfills":null,"owners_before":["9taLkHkaBXeSF8vrhDGFTAmcZuCEPqjQrKadfYGs4gHv"]}],"metadata":null,"operation":"CREATE","outputs":[{"amount":"1","condition":{"details":{"public_key":"6FDGsHrR9RZqNaEm7kBvqtxRkrvuWogBW2Uy7BkWc5Tz","type":"ed25519-sha-256"},"uri":"ni:///sha-256;RmovleG60-7K0CX60jjfUunV3lBpUOkiQOAnBzghm0w?fpt=ed25519-sha-256&cost=131072"},"public_keys":["6FDGsHrR9RZqNaEm7kBvqtxRkrvuWogBW2Uy7BkWc5Tz"]},{"amount":"2","condition":{"details":{"public_key":"AH9D7xgmhyLmVE944zvHvuvYWuj5DfbMBJhnDM4A5FdT","type":"ed25519-sha-256"},"uri":"ni:///sha-256;-HlYmgwwl-vXwE52IaADhvYxaL1TbjqfJ-LGn5a1PFc?fpt=ed25519-sha-256&cost=131072"},"public_keys":["AH9D7xgmhyLmVE944zvHvuvYWuj5DfbMBJhnDM4A5FdT"]},{"amount":"3","condition":{"details":{"public_key":"HpmSVrojHvfCXQbmoAs4v6Aq1oZiZsZDnjr68KiVtPbB","type":"ed25519-sha-256"},"uri":"ni:///sha-256;xfn8pvQkTCPtvR0trpHy2pqkkNTmMBCjWMMOHtk3WO4?fpt=ed25519-sha-256&cost=131072"},"public_keys":["HpmSVrojHvfCXQbmoAs4v6Aq1oZiZsZDnjr68KiVtPbB"]}],"version":"1.0"}',  # noqa: E501
        # noqa
        "output_index": 0,
        "transaction_id": "e897c7a0426461a02b4fca8ed73bc0debed7570cf3b40fb4f49c963434225a4d",
    }


@pytest.fixture
def unspent_output_1():
    return {
        "amount": 2,
        "asset_id": "e897c7a0426461a02b4fca8ed73bc0debed7570cf3b40fb4f49c963434225a4d",
        "condition_uri": "ni:///sha-256;-HlYmgwwl-vXwE52IaADhvYxaL1TbjqfJ-LGn5a1PFc?fpt=ed25519-sha-256&cost=131072",
        "fulfillment_message": '{"asset":{"data":{"hash":"06e47bcf9084f7ecfd2a2a2ad275444a"}},"id":"e897c7a0426461a02b4fca8ed73bc0debed7570cf3b40fb4f49c963434225a4d","inputs":[{"fulfillment":"pGSAIIQT0Jm6LDlcSs9coJK4Q4W-SNtsO2EtMtQJ04EUjBMJgUAXKIqeaippbF-IClhhZNNaP6EIZ_OgrVQYU4mH6b-Vc3Tg-k6p-rJOlLGUUo_w8C5QgPHNRYFOqUk2f1q0Cs4G","fulfills":null,"owners_before":["9taLkHkaBXeSF8vrhDGFTAmcZuCEPqjQrKadfYGs4gHv"]}],"metadata":null,"operation":"CREATE","outputs":[{"amount":"1","condition":{"details":{"public_key":"6FDGsHrR9RZqNaEm7kBvqtxRkrvuWogBW2Uy7BkWc5Tz","type":"ed25519-sha-256"},"uri":"ni:///sha-256;RmovleG60-7K0CX60jjfUunV3lBpUOkiQOAnBzghm0w?fpt=ed25519-sha-256&cost=131072"},"public_keys":["6FDGsHrR9RZqNaEm7kBvqtxRkrvuWogBW2Uy7BkWc5Tz"]},{"amount":"2","condition":{"details":{"public_key":"AH9D7xgmhyLmVE944zvHvuvYWuj5DfbMBJhnDM4A5FdT","type":"ed25519-sha-256"},"uri":"ni:///sha-256;-HlYmgwwl-vXwE52IaADhvYxaL1TbjqfJ-LGn5a1PFc?fpt=ed25519-sha-256&cost=131072"},"public_keys":["AH9D7xgmhyLmVE944zvHvuvYWuj5DfbMBJhnDM4A5FdT"]},{"amount":"3","condition":{"details":{"public_key":"HpmSVrojHvfCXQbmoAs4v6Aq1oZiZsZDnjr68KiVtPbB","type":"ed25519-sha-256"},"uri":"ni:///sha-256;xfn8pvQkTCPtvR0trpHy2pqkkNTmMBCjWMMOHtk3WO4?fpt=ed25519-sha-256&cost=131072"},"public_keys":["HpmSVrojHvfCXQbmoAs4v6Aq1oZiZsZDnjr68KiVtPbB"]}],"version":"1.0"}',  # noqa: E501
        # noqa
        "output_index": 1,
        "transaction_id": "e897c7a0426461a02b4fca8ed73bc0debed7570cf3b40fb4f49c963434225a4d",
    }


@pytest.fixture
def unspent_output_2():
    return {
        "amount": 3,
        "asset_id": "e897c7a0426461a02b4fca8ed73bc0debed7570cf3b40fb4f49c963434225a4d",
        "condition_uri": "ni:///sha-256;xfn8pvQkTCPtvR0trpHy2pqkkNTmMBCjWMMOHtk3WO4?fpt=ed25519-sha-256&cost=131072",
        "fulfillment_message": '{"asset":{"data":{"hash":"06e47bcf9084f7ecfd2a2a2ad275444a"}},"id":"e897c7a0426461a02b4fca8ed73bc0debed7570cf3b40fb4f49c963434225a4d","inputs":[{"fulfillment":"pGSAIIQT0Jm6LDlcSs9coJK4Q4W-SNtsO2EtMtQJ04EUjBMJgUAXKIqeaippbF-IClhhZNNaP6EIZ_OgrVQYU4mH6b-Vc3Tg-k6p-rJOlLGUUo_w8C5QgPHNRYFOqUk2f1q0Cs4G","fulfills":null,"owners_before":["9taLkHkaBXeSF8vrhDGFTAmcZuCEPqjQrKadfYGs4gHv"]}],"metadata":null,"operation":"CREATE","outputs":[{"amount":"1","condition":{"details":{"public_key":"6FDGsHrR9RZqNaEm7kBvqtxRkrvuWogBW2Uy7BkWc5Tz","type":"ed25519-sha-256"},"uri":"ni:///sha-256;RmovleG60-7K0CX60jjfUunV3lBpUOkiQOAnBzghm0w?fpt=ed25519-sha-256&cost=131072"},"public_keys":["6FDGsHrR9RZqNaEm7kBvqtxRkrvuWogBW2Uy7BkWc5Tz"]},{"amount":"2","condition":{"details":{"public_key":"AH9D7xgmhyLmVE944zvHvuvYWuj5DfbMBJhnDM4A5FdT","type":"ed25519-sha-256"},"uri":"ni:///sha-256;-HlYmgwwl-vXwE52IaADhvYxaL1TbjqfJ-LGn5a1PFc?fpt=ed25519-sha-256&cost=131072"},"public_keys":["AH9D7xgmhyLmVE944zvHvuvYWuj5DfbMBJhnDM4A5FdT"]},{"amount":"3","condition":{"details":{"public_key":"HpmSVrojHvfCXQbmoAs4v6Aq1oZiZsZDnjr68KiVtPbB","type":"ed25519-sha-256"},"uri":"ni:///sha-256;xfn8pvQkTCPtvR0trpHy2pqkkNTmMBCjWMMOHtk3WO4?fpt=ed25519-sha-256&cost=131072"},"public_keys":["HpmSVrojHvfCXQbmoAs4v6Aq1oZiZsZDnjr68KiVtPbB"]}],"version":"1.0"}',  # noqa: E501
        # noqa
        "output_index": 2,
        "transaction_id": "e897c7a0426461a02b4fca8ed73bc0debed7570cf3b40fb4f49c963434225a4d",
    }


@pytest.fixture
def unspent_outputs(unspent_output_0, unspent_output_1, unspent_output_2):
    return unspent_output_0, unspent_output_1, unspent_output_2


@pytest.fixture
def tarantool_client(db_context):  # TODO Here add TarantoolConnectionClass
    return TarantoolDBConnection(host=db_context.host, port=db_context.port)


@pytest.fixture
def utxo_collection(tarantool_client, _setup_database):
    return tarantool_client.get_space("utxos")


@pytest.fixture
def dummy_unspent_outputs():
    return [
        {"transaction_id": "a", "output_index": 0},
        {"transaction_id": "a", "output_index": 1},
        {"transaction_id": "b", "output_index": 0},
    ]


@pytest.fixture
def utxoset(dummy_unspent_outputs, utxo_collection):
    from uuid import uuid4

    num_rows_before_operation = utxo_collection.select().rowcount
    for utxo in dummy_unspent_outputs:
        res = utxo_collection.insert((uuid4().hex, utxo["transaction_id"], utxo["output_index"], utxo))
        assert res
    num_rows_after_operation = utxo_collection.select().rowcount
    assert num_rows_after_operation == num_rows_before_operation + 3
    return dummy_unspent_outputs, utxo_collection


@pytest.fixture
def network_validators(node_keys):
    validator_pub_power = {}
    voting_power = [8, 10, 7, 9]
    for pub, priv in node_keys.items():
        validator_pub_power[pub] = voting_power.pop()

    return validator_pub_power


@pytest.fixture
def network_validators58(network_validators):
    network_validators_base58 = {}
    for p, v in network_validators.items():
        p = public_key_from_ed25519_key(key_from_base64(p))
        network_validators_base58[p] = v

    return network_validators_base58


@pytest.fixture
def node_key(node_keys):
    (pub, priv) = list(node_keys.items())[0]
    return key_pair_from_ed25519_key(key_from_base64(priv))


@pytest.fixture
def ed25519_node_keys(node_keys):
    (pub, priv) = list(node_keys.items())[0]
    node_keys_dict = {}
    for pub, priv in node_keys.items():
        key = key_pair_from_ed25519_key(key_from_base64(priv))
        node_keys_dict[key.public_key] = key

    return node_keys_dict


@pytest.fixture
def node_keys():
    return {
        "zL/DasvKulXZzhSNFwx4cLRXKkSM9GPK7Y0nZ4FEylM=": "cM5oW4J0zmUSZ/+QRoRlincvgCwR0pEjFoY//ZnnjD3Mv8Nqy8q6VdnOFI0XDHhwtFcqRIz0Y8rtjSdngUTKUw==",
        "GIijU7GBcVyiVUcB0GwWZbxCxdk2xV6pxdvL24s/AqM=": "mdz7IjP6mGXs6+ebgGJkn7kTXByUeeGhV+9aVthLuEAYiKNTsYFxXKJVRwHQbBZlvELF2TbFXqnF28vbiz8Cow==",
        "JbfwrLvCVIwOPm8tj8936ki7IYbmGHjPiKb6nAZegRA=": "83VINXdj2ynOHuhvSZz5tGuOE5oYzIi0mEximkX1KYMlt/Csu8JUjA4+by2Pz3fqSLshhuYYeM+IpvqcBl6BEA==",
        "PecJ58SaNRsWJZodDmqjpCWqG6btdwXFHLyE40RYlYM=": "uz8bYgoL4rHErWT1gjjrnA+W7bgD/uDQWSRKDmC8otc95wnnxJo1GxYlmh0OaqOkJaobpu13BcUcvITjRFiVgw==",
    }


@pytest.fixture
def priv_validator_path(node_keys):
    (public_key, private_key) = list(node_keys.items())[0]
    priv_validator = {
        "address": "84F787D95E196DC5DE5F972666CFECCA36801426",
        "pub_key": {"type": "AC26791624DE60", "value": public_key},
        "last_height": 0,
        "last_round": 0,
        "last_step": 0,
        "priv_key": {"type": "954568A3288910", "value": private_key},
    }
    fd, path = tempfile.mkstemp()
    socket = os.fdopen(fd, "w")
    json.dump(priv_validator, socket)
    socket.close()
    return path


@pytest.fixture
def bad_validator_path(node_keys):
    (public_key, private_key) = list(node_keys.items())[1]
    priv_validator = {
        "address": "84F787D95E196DC5DE5F972666CFECCA36801426",
        "pub_key": {"type": "AC26791624DE60", "value": public_key},
        "last_height": 0,
        "last_round": 0,
        "last_step": 0,
        "priv_key": {"type": "954568A3288910", "value": private_key},
    }
    fd, path = tempfile.mkstemp()
    socket = os.fdopen(fd, "w")
    json.dump(priv_validator, socket)
    socket.close()
    return path


@pytest.fixture
def validators(b, node_keys):
    from planetmint.backend import query
    import time

    def timestamp():  # we need this to force unique election_ids for setup and teardown of fixtures
        return str(time.time())

    height = get_block_height(b)

    original_validators = b.models.get_validators()

    (public_key, private_key) = list(node_keys.items())[0]

    validator_set = [
        {
            "address": "F5426F0980E36E03044F74DD414248D29ABCBDB2",
            "public_key": {"value": public_key, "type": "ed25519-base64"},
            "voting_power": 10,
        }
    ]

    validator_update = {"validators": validator_set, "height": height + 1, "election_id": f"setup_at_{timestamp()}"}

    query.store_validator_set(b.models.connection, validator_update)

    yield

    height = get_block_height(b)

    validator_update = {
        "validators": original_validators,
        "height": height,
        "election_id": f"teardown_at_{timestamp()}",
    }

    query.store_validator_set(b.models.connection, validator_update)


def get_block_height(b):
    if b.models.get_latest_block():
        height = b.models.get_latest_block()["height"]
    else:
        height = 0

    return height


@pytest.fixture
def new_validator():
    public_key = "1718D2DBFF00158A0852A17A01C78F4DCF3BA8E4FB7B8586807FAC182A535034"
    power = 1
    node_id = "fake_node_id"

    return [
        {"data": {"public_key": {"value": public_key, "type": "ed25519-base16"}, "power": power, "node_id": node_id}}
    ]


@pytest.fixture
def valid_upsert_validator_election(b_mock, node_key, new_validator):
    voters = b_mock.get_recipients_list()
    return ValidatorElection.generate([node_key.public_key], voters, new_validator, None).sign([node_key.private_key])


@pytest.fixture
def valid_upsert_validator_election_2(b_mock, node_key, new_validator):
    voters = b_mock.get_recipients_list()
    return ValidatorElection.generate([node_key.public_key], voters, new_validator, None).sign([node_key.private_key])


@pytest.fixture
def ongoing_validator_election(b, valid_upsert_validator_election, ed25519_node_keys):
    validators = b.models.get_validators(height=1)
    genesis_validators = {"validators": validators, "height": 0}
    query.store_validator_set(b.models.connection, genesis_validators)
    b.models.store_bulk_transactions([valid_upsert_validator_election])
    query.store_election(b.models.connection, valid_upsert_validator_election.id, 1, is_concluded=False)
    block_1 = Block(app_hash="hash_1", height=1, transactions=[valid_upsert_validator_election.id])
    b.models.store_block(block_1._asdict())
    return valid_upsert_validator_election


@pytest.fixture
def ongoing_validator_election_2(b, valid_upsert_validator_election_2, ed25519_node_keys):
    validators = b.models.get_validators(height=1)
    genesis_validators = {"validators": validators, "height": 0, "election_id": None}
    query.store_validator_set(b.models.connection, genesis_validators)

    b.models.store_bulk_transactions([valid_upsert_validator_election_2])
    block_1 = Block(app_hash="hash_2", height=1, transactions=[valid_upsert_validator_election_2.id])
    b.models.store_block(block_1._asdict())
    return valid_upsert_validator_election_2


@pytest.fixture
def validator_election_votes(b_mock, ongoing_validator_election, ed25519_node_keys):
    voters = b_mock.get_recipients_list()
    votes = generate_votes(ongoing_validator_election, voters, ed25519_node_keys)
    return votes


@pytest.fixture
def validator_election_votes_2(b_mock, ongoing_validator_election_2, ed25519_node_keys):
    voters = b_mock.get_recipients_list()
    votes = generate_votes(ongoing_validator_election_2, voters, ed25519_node_keys)
    return votes


def generate_votes(election, voters, keys):
    votes = []
    for voter, _ in enumerate(voters):
        v = gen_vote(election, voter, keys)
        votes.append(v)
    return votes


@pytest.fixture
def signed_2_0_create_tx():
    return {
        "inputs": [
            {
                "owners_before": ["7WaJCRqUJMZjVyQxqq8GNjkw11gacFmDAZGPLdNxfBgx"],
                "fulfills": None,
                "fulfillment": "pGSAIGC5nQ37hCCMAWIUBAJn4wVBOkHlURaWzWLjE5rTzG91gUC0Akx2m_AoPy1H6yTz7Ou2I-OGjNjWgvR5EATn8XZ1u-g91XL3CkSXXiL2sUJqDibJQJjGZjag_7fRu5_VkDUD",
            }
        ],
        "outputs": [
            {
                "public_keys": ["7WaJCRqUJMZjVyQxqq8GNjkw11gacFmDAZGPLdNxfBgx"],
                "condition": {
                    "details": {
                        "type": "ed25519-sha-256",
                        "public_key": "7WaJCRqUJMZjVyQxqq8GNjkw11gacFmDAZGPLdNxfBgx",
                    },
                    "uri": "ni:///sha-256;xtKK2YRiX7_EPF2harsf-PELcJwfHQM7jZ_YvilEOOI?fpt=ed25519-sha-256&cost=131072",
                },
                "amount": "3000",
            }
        ],
        "operation": "CREATE",
        "metadata": "QmRBri4SARi56PgB2ALFVjHsLhQDUh4jYbeiHaU94vLoxd",
        "asset": {"data": "QmW5GVMW98D3mktSDfWHS8nX2UiCd8gP1uCiujnFX4yK8n"},
        "version": "2.0",
        "id": "334014a29d99a488789c711b7dc5fceb534d1a9290b14d0270dbe6b60e2f036e",
    }


@pytest.fixture
def signed_2_0_create_tx_assets():
    return {
        "inputs": [
            {
                "owners_before": ["5V4AANHTSLdQH1mEA1pohW3jMduY9xMJ1voos7gRfMQF"],
                "fulfills": None,
                "fulfillment": "pGSAIEKelMEu8AzcA9kcDLrsEXhSpZG-lf2c9CuZpzZU_ONkgUBMztcnweWqwHVfVk9Y-IRgfdh864yXYTrTKzSMy6uvNjQeLtGzKxz4gjb01NUu6WLvZBAvr0Ws4glfxKiDLjkP",
            }
        ],
        "outputs": [
            {
                "public_keys": ["5V4AANHTSLdQH1mEA1pohW3jMduY9xMJ1voos7gRfMQF"],
                "condition": {
                    "details": {
                        "type": "ed25519-sha-256",
                        "public_key": "5V4AANHTSLdQH1mEA1pohW3jMduY9xMJ1voos7gRfMQF",
                    },
                    "uri": "ni:///sha-256;M3l9yVs7ItjP-lxT7B2ta6rpRa-GHt6TBSYpy8l-IS8?fpt=ed25519-sha-256&cost=131072",
                },
                "amount": "3000",
            }
        ],
        "operation": "CREATE",
        "metadata": "QmRBri4SARi56PgB2ALFVjHsLhQDUh4jYbeiHaU94vLoxd",
        "assets": {"data": "QmW5GVMW98D3mktSDfWHS8nX2UiCd8gP1uCiujnFX4yK8n"},
        "version": "2.0",
        "id": "3e2a2c5eef5e6a0c4e1e5f8d0dc1d3d9b4f035592a9788f8bfa7d59f86d123d3",
    }


@pytest.fixture
def signed_2_0_transfer_tx():
    return {
        "inputs": [
            {
                "owners_before": ["7WaJCRqUJMZjVyQxqq8GNjkw11gacFmDAZGPLdNxfBgx"],
                "fulfills": {
                    "transaction_id": "334014a29d99a488789c711b7dc5fceb534d1a9290b14d0270dbe6b60e2f036e",
                    "output_index": 0,
                },
                "fulfillment": "pGSAIGC5nQ37hCCMAWIUBAJn4wVBOkHlURaWzWLjE5rTzG91gUBHNp8jobEyMqcIcIFl-TaAEDHRMyigDutgCIIomyVgb1a0LIk5eEpMTVP4ACxZnrVH-SIKEDHNdH4FGyBMka4B",
            }
        ],
        "outputs": [
            {
                "public_keys": ["3m1tUV5hmWPBaNQEoyFtZxFgDFiHYAYvPMzczNHwWp5v"],
                "condition": {
                    "details": {
                        "type": "ed25519-sha-256",
                        "public_key": "3m1tUV5hmWPBaNQEoyFtZxFgDFiHYAYvPMzczNHwWp5v",
                    },
                    "uri": "ni:///sha-256;4pXSmxViATpOG8Mcc0gYsa-4bjRnLk5MY06VXv_UeJA?fpt=ed25519-sha-256&cost=131072",
                },
                "amount": "50",
            },
            {
                "public_keys": ["7WaJCRqUJMZjVyQxqq8GNjkw11gacFmDAZGPLdNxfBgx"],
                "condition": {
                    "details": {
                        "type": "ed25519-sha-256",
                        "public_key": "7WaJCRqUJMZjVyQxqq8GNjkw11gacFmDAZGPLdNxfBgx",
                    },
                    "uri": "ni:///sha-256;xtKK2YRiX7_EPF2harsf-PELcJwfHQM7jZ_YvilEOOI?fpt=ed25519-sha-256&cost=131072",
                },
                "amount": "2950",
            },
        ],
        "operation": "TRANSFER",
        "metadata": "QmTjWHzypFxE8uuXJXMJQJxgAEKjoWmQimGiutmPyJ6CAB",
        "asset": {"id": "334014a29d99a488789c711b7dc5fceb534d1a9290b14d0270dbe6b60e2f036e"},
        "version": "2.0",
        "id": "e577641b0e2eb619e282f802516ce043e9d4af51dd4b6c959e18246e85cae2a6",
    }
