# Copyright © 2020 Interplanetary Database Association e.V.,
# Planetmint and IPDB software contributors.
# SPDX-License-Identifier: (Apache-2.0 AND CC-BY-4.0)
# Code is Apache-2.0 and docs are CC-BY-4.0

import json
import base58
import pytest

from unittest.mock import Mock, patch
from planetmint_cryptoconditions import Ed25519Sha256
from ipld import multihash, marshal
from hashlib import sha3_256

from transactions.common import crypto
from transactions.common.transaction import Transaction
from transactions.types.assets.create import Create
from transactions.types.assets.compose import Compose
from transactions.types.assets.decompose import Decompose
from transactions.types.assets.transfer import Transfer
from transactions.common.transaction_mode_types import (
    BROADCAST_TX_COMMIT,
    BROADCAST_TX_ASYNC,
    BROADCAST_TX_SYNC,
)
from transactions.common.transaction import (
    Input,
    TransactionLink,
)
from transactions.common.utils import _fulfillment_from_details
from transactions.common.crypto import generate_key_pair

TX_ENDPOINT = "/api/v1/transactions/"


@pytest.mark.abci
def test_get_transaction_endpoint(client, posted_create_tx):
    res = client.get(TX_ENDPOINT + posted_create_tx.id)
    assert posted_create_tx.to_dict() == res.json
    assert res.status_code == 200


def test_get_transaction_returns_404_if_not_found(client, b):
    res = client.get(TX_ENDPOINT + "123")
    assert res.status_code == 404

    res = client.get(TX_ENDPOINT + "123/")
    assert res.status_code == 404


@pytest.mark.abci
def test_post_create_transaction_endpoint(b, client):
    user_priv, user_pub = crypto.generate_key_pair()

    tx = Create.generate([user_pub], [([user_pub], 1)])
    tx = tx.sign([user_priv])

    res = client.post(TX_ENDPOINT, data=json.dumps(tx.to_dict()))

    assert res.status_code == 202

    assert res.json["inputs"][0]["owners_before"][0] == user_pub
    assert res.json["outputs"][0]["public_keys"][0] == user_pub


@pytest.mark.abci
@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize(
    "language,expected_status_code",
    [
        ("danish", 202),
        ("dutch", 202),
        ("english", 202),
        ("finnish", 202),
        ("french", 202),
        ("german", 202),
        ("hungarian", 202),
        ("italian", 202),
        ("norwegian", 202),
        ("portuguese", 202),
        ("romanian", 202),
        ("none", 202),
        ("russian", 202),
        ("spanish", 202),
        ("swedish", 202),
        ("turkish", 202),
        ("da", 202),
        ("nl", 202),
        ("en", 202),
        ("fi", 202),
        ("fr", 202),
        ("de", 202),
        ("hu", 202),
        ("it", 202),
        ("nb", 202),
        ("pt", 202),
        ("ro", 202),
        ("ru", 202),
        ("es", 202),
        ("sv", 202),
        ("tr", 202),
        ("any", 400),
    ],
)
@pytest.mark.language
def test_post_create_transaction_with_language(b, client, nested, language, expected_status_code):
    from planetmint.backend.localmongodb.connection import LocalMongoDBConnection

    if isinstance(b.models.connection, LocalMongoDBConnection):
        user_priv, user_pub = crypto.generate_key_pair()
        lang_obj = {"language": language}

        if nested:
            asset = {"root": lang_obj}
        else:
            asset = lang_obj
        assets = [{"data": multihash(marshal(asset))}]
        tx = Create.generate([user_pub], [([user_pub], 1)], assets=assets)
        tx = tx.sign([user_priv])
        res = client.post(TX_ENDPOINT, data=json.dumps(tx.to_dict()))
        assert res.status_code == expected_status_code
        if res.status_code == 400:
            expected_error_message = (
                "Invalid transaction (ValidationError): MongoDB does not support "
                'text search for the language "{}". If you do not understand this '
                'error message then please rename key/field "language" to something '
                'else like "lang".'
            ).format(language)
            assert res.json["message"] == expected_error_message


@pytest.mark.abci
@pytest.mark.parametrize("field", ["asset", "metadata"])
@pytest.mark.parametrize(
    "value,err_key,expected_status_code",
    [
        ({"bad.key": "v"}, "bad.key", 400),
        ({"$bad.key": "v"}, "$bad.key", 400),
        ({"$badkey": "v"}, "$badkey", 400),
        ({"bad\x00key": "v"}, "bad\x00key", 400),
        ({"good_key": {"bad.key": "v"}}, "bad.key", 400),
        ({"good_key": "v"}, "good_key", 202),
    ],
)
def test_post_create_transaction_with_invalid_key(b, client, field, value, err_key, expected_status_code):
    from planetmint.backend.localmongodb.connection import LocalMongoDBConnection

    user_priv, user_pub = crypto.generate_key_pair()

    if isinstance(b.models.connection, LocalMongoDBConnection):
        if field == "asset":
            tx = Create.generate([user_pub], [([user_pub], 1)], assets=value)
        elif field == "metadata":
            tx = Create.generate([user_pub], [([user_pub], 1)], metadata=value)
        tx = tx.sign([user_priv])
        res = client.post(TX_ENDPOINT, data=json.dumps(tx.to_dict()))

        assert res.status_code == expected_status_code

        if res.status_code == 400:
            expected_error_message = (
                'Invalid transaction (ValidationError): Invalid key name "{}" '
                "in {} object. The key name cannot contain characters "
                '".", "$" or null characters'
            ).format(err_key, field)
            assert res.json["message"] == expected_error_message


@pytest.mark.abci
@patch("planetmint.web.views.base.logger")
def test_post_create_transaction_with_invalid_id(mock_logger, b, client):
    from transactions.common.exceptions import InvalidHash

    user_priv, user_pub = crypto.generate_key_pair()

    tx = Create.generate([user_pub], [([user_pub], 1)])
    tx = tx.sign([user_priv]).to_dict()
    tx["id"] = "abcd" * 16

    res = client.post(TX_ENDPOINT, data=json.dumps(tx))
    expected_status_code = 400
    expected_error_message = (
        "Invalid transaction ({}): The transaction's id '{}' isn't equal to "
        "the hash of its body, i.e. it's not valid."
    ).format(InvalidHash.__name__, tx["id"])
    assert res.status_code == expected_status_code
    assert res.json["message"] == expected_error_message
    # TODO change the loglevel to DEBUG for this test case to enable the following 3 asserts
    # assert mock_logger.error.called
    # assert "HTTP API error: %(status)s - %(method)s:%(path)s - %(message)s" in mock_logger.error.call_args[0]
    # assert {
    #    "message": expected_error_message,
    #    "status": expected_status_code,
    #    "method": "POST",
    #    "path": TX_ENDPOINT,
    # } in mock_logger.error.call_args[0]
    # TODO put back caplog based asserts once possible
    # assert caplog.records[0].args['status'] == expected_status_code
    # assert caplog.records[0].args['message'] == expected_error_message


@pytest.mark.abci
@patch("planetmint.web.views.base.logger")
def test_post_create_transaction_with_invalid_signature(mock_logger, b, client):
    from transactions.common.exceptions import InvalidSignature

    user_priv, user_pub = crypto.generate_key_pair()

    tx = Create.generate([user_pub], [([user_pub], 1)]).to_dict()
    tx["inputs"][0]["fulfillment"] = 64 * "0"
    tx["id"] = sha3_256(
        json.dumps(
            tx,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode(),
    ).hexdigest()

    res = client.post(TX_ENDPOINT, data=json.dumps(tx))
    expected_status_code = 400
    expected_error_message = ("Invalid transaction ({}): Fulfillment URI " "couldn't been parsed").format(
        InvalidSignature.__name__
    )
    assert res.status_code == expected_status_code
    assert res.json["message"] == expected_error_message
    # TODO change the loglevel to DEBUG for this test case to enable the following 3 asserts
    # assert mock_logger.error.called
    # assert "HTTP API error: %(status)s - %(method)s:%(path)s - %(message)s" in mock_logger.error.call_args[0]
    # assert {
    #    "message": expected_error_message,
    #    "status": expected_status_code,
    #    "method": "POST",
    #    "path": TX_ENDPOINT,
    # } in mock_logger.error.call_args[0]
    # TODO put back caplog based asserts once possible
    # assert caplog.records[0].args['status'] == expected_status_code
    # assert caplog.records[0].args['message'] == expected_error_message


@pytest.mark.abci
def test_post_create_transaction_with_invalid_structure(client):
    res = client.post(TX_ENDPOINT, data="{}")
    assert res.status_code == 400


@pytest.mark.abci
@patch("planetmint.web.views.base.logger")
def test_post_create_transaction_with_invalid_schema(mock_logger, client):
    user_priv, user_pub = crypto.generate_key_pair()
    tx = Create.generate([user_pub], [([user_pub], 1)]).to_dict()
    del tx["version"]
    ed25519 = Ed25519Sha256(public_key=base58.b58decode(user_pub))
    message = json.dumps(
        tx,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    ed25519.sign(message, base58.b58decode(user_priv))
    tx["inputs"][0]["fulfillment"] = ed25519.serialize_uri()
    tx["id"] = sha3_256(
        json.dumps(
            tx,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode(),
    ).hexdigest()
    res = client.post(TX_ENDPOINT, data=json.dumps(tx))
    expected_status_code = 400
    expected_error_message = (
        # "Invalid transaction schema: 'version' is a required property"
        "Invalid transaction (KeyError): 'version'"
    )
    assert res.status_code == expected_status_code
    assert res.json["message"] == expected_error_message
    # TODO change the loglevel to DEBUG for this test case to enable the following 3 asserts
    # assert mock_logger.error.called
    # assert "HTTP API error: %(status)s - %(method)s:%(path)s - %(message)s" in mock_logger.error.call_args[0]
    # assert {
    #    "message": expected_error_message,
    #    "status": expected_status_code,
    #    "method": "POST",
    #    "path": TX_ENDPOINT,
    # } in mock_logger.error.call_args[0]
    # TODO put back caplog based asserts once possible
    # assert caplog.records[0].args['status'] == expected_status_code
    # assert caplog.records[0].args['message'] == expected_error_message


@pytest.mark.abci
@pytest.mark.parametrize(
    "exc,msg",
    (
        ("AmountError", "Do the math again!"),
        ("DoubleSpend", "Nope! It is gone now!"),
        ("InvalidHash", "Do not smoke that!"),
        ("InvalidSignature", "Falsche Unterschrift!"),
        ("ValidationError", "Create and transfer!"),
        ("InputDoesNotExist", "Hallucinations?"),
        ("TransactionOwnerError", "Not yours!"),
        ("ValidationError", "?"),
    ),
)
@patch("planetmint.web.views.base.logger")
def test_post_invalid_transaction(
    mock_logger,
    client,
    exc,
    msg,
):
    from transactions.common import exceptions

    exc_cls = getattr(exceptions, exc)

    def mock_validation(self_, tx, skip_schema_validation=True):
        raise exc_cls(msg)

    with patch.object(Transaction, "from_dict", mock_validation):
        res = client.post(TX_ENDPOINT, data=json.dumps({}))
        expected_status_code = 400
        expected_error_message = "Invalid transaction ({}): {}".format(exc, msg)
        assert res.status_code == expected_status_code
        assert res.json["message"] == "Invalid transaction ({}): {}".format(exc, msg)
        # TODO change the loglevel to DEBUG for this test case to enable the following 3 asserts
        # assert mock_logger.error.called
        # assert "HTTP API error: %(status)s - %(method)s:%(path)s - %(message)s" in mock_logger.error.call_args[0]
        # assert {
        #    "message": expected_error_message,
        #    "status": expected_status_code,
        #    "method": "POST",
        #    "path": TX_ENDPOINT,
        # } in mock_logger.error.call_args[0]
        # TODO put back caplog based asserts once possible
        # assert caplog.records[2].args['status'] == expected_status_code
        # assert caplog.records[2].args['message'] == expected_error_message


@pytest.mark.abci
def test_post_transfer_transaction_endpoint(client, user_pk, user_sk, posted_create_tx):
    transfer_tx = Transfer.generate(posted_create_tx.to_inputs(), [([user_pk], 1)], asset_ids=[posted_create_tx.id])
    transfer_tx = transfer_tx.sign([user_sk])

    res = client.post(TX_ENDPOINT, data=json.dumps(transfer_tx.to_dict()))
    assert res.status_code == 202

    assert res.json["inputs"][0]["owners_before"][0] == user_pk
    assert res.json["outputs"][0]["public_keys"][0] == user_pk


@pytest.mark.abci
def test_post_invalid_transfer_transaction_returns_400(client, user_pk, posted_create_tx):
    from transactions.common.exceptions import InvalidSignature

    transfer_tx = Transfer.generate(posted_create_tx.to_inputs(), [([user_pk], 1)], asset_ids=[posted_create_tx.id])
    transfer_tx._hash()

    res = client.post(TX_ENDPOINT, data=json.dumps(transfer_tx.to_dict()))
    expected_status_code = 400
    expected_error_message = "Invalid transaction ({}): {}".format(
        InvalidSignature.__name__, "Transaction signature is invalid."
    )
    assert res.status_code == expected_status_code
    assert res.json["message"] == expected_error_message


@pytest.mark.abci
def test_post_wrong_asset_division_transfer_returns_400(b, client, user_pk):
    from transactions.common.exceptions import AmountError

    priv_key, pub_key = crypto.generate_key_pair()

    create_tx = Create.generate(
        [pub_key], [([pub_key], 10)], assets=[{"data": multihash(marshal({"test": "asset"}))}]
    ).sign([priv_key])
    res = client.post(TX_ENDPOINT + "?mode=commit", data=json.dumps(create_tx.to_dict()))
    assert res.status_code == 202

    transfer_tx = Transfer.generate(
        create_tx.to_inputs(), [([pub_key], 20)], asset_ids=[create_tx.id]
    ).sign(  # 20 > 10
        [priv_key]
    )
    res = client.post(TX_ENDPOINT + "?mode=commit", data=json.dumps(transfer_tx.to_dict()))
    expected_error_message = (
        f"Invalid transaction ({AmountError.__name__}): "
        + "The amount used in the inputs `10` needs to be same as the amount used in the outputs `20`"
    )

    assert res.status_code == 400
    assert res.json["message"] == expected_error_message


def test_transactions_get_list_good(client):
    from functools import partial

    def get_txs_patched(conn, **args):
        """Patch `get_transactions_filtered` so that rather than return an array
        of transactions it returns an array of shims with a to_dict() method
        that reports one of the arguments passed to `get_transactions_filtered`.
        """
        return [type("", (), {"to_dict": partial(lambda a: a, arg)}) for arg in sorted(args.items())]

    asset_ids = ["1" * 64]

    with patch("planetmint.model.dataaccessor.DataAccessor.get_transactions_filtered", get_txs_patched):
        url = TX_ENDPOINT + "?asset_ids=" + ",".join(asset_ids)
        assert client.get(url).json == [
            ["asset_ids", asset_ids],
            ["last_tx", None],
            ["operation", None],
        ]
        url = TX_ENDPOINT + "?asset_ids=" + ",".join(asset_ids) + "&operation=CREATE"
        assert client.get(url).json == [
            ["asset_ids", asset_ids],
            ["last_tx", None],
            ["operation", "CREATE"],
        ]
        url = TX_ENDPOINT + "?asset_ids=" + ",".join(asset_ids) + "&last_tx=true"
        assert client.get(url).json == [
            ["asset_ids", asset_ids],
            ["last_tx", True],
            ["operation", None],
        ]


def test_transactions_get_list_bad(client):
    def should_not_be_called():
        assert False

    with patch(
        "planetmint.model.dataaccessor.DataAccessor.get_transactions_filtered",
        lambda *_, **__: should_not_be_called(),
    ):
        # Test asset id validated
        url = TX_ENDPOINT + "?asset_id=" + "1" * 63
        assert client.get(url).status_code == 400
        # Test operation validated
        url = TX_ENDPOINT + "?asset_id=" + "1" * 64 + "&operation=CEATE"
        assert client.get(url).status_code == 400
        # Test asset ID required
        url = TX_ENDPOINT + "?operation=CREATE"
        assert client.get(url).status_code == 400


@patch("requests.post")
@pytest.mark.parametrize(
    "mode",
    [
        ("", BROADCAST_TX_ASYNC),
        ("?mode=async", BROADCAST_TX_ASYNC),
        ("?mode=sync", BROADCAST_TX_SYNC),
        ("?mode=commit", BROADCAST_TX_COMMIT),
    ],
)
def test_post_transaction_valid_modes(mock_post, client, mode):
    def _mock_post(*args, **kwargs):
        return Mock(json=Mock(return_value={"result": {"code": 0}}))

    mock_post.side_effect = _mock_post

    alice = generate_key_pair()
    tx = Create.generate([alice.public_key], [([alice.public_key], 1)], assets=None).sign([alice.private_key])
    mode_endpoint = TX_ENDPOINT + mode[0]
    client.post(mode_endpoint, data=json.dumps(tx.to_dict()))
    args, kwargs = mock_post.call_args
    assert mode[1] == kwargs["json"]["method"]


@pytest.mark.abci
def test_post_transaction_invalid_mode(client):
    alice = generate_key_pair()
    tx = Create.generate([alice.public_key], [([alice.public_key], 1)], assets=None).sign([alice.private_key])
    mode_endpoint = TX_ENDPOINT + "?mode=nope"
    response = client.post(mode_endpoint, data=json.dumps(tx.to_dict()))
    assert "400 BAD REQUEST" in response.status
    assert 'Mode must be "async", "sync" or "commit"' == json.loads(response.data.decode("utf8"))["message"]["mode"]


def test_post_transaction_compose_valid_wo_abci(b, _bdb):
    alice = generate_key_pair()
    tx = Create.generate(
        [alice.public_key],
        [([alice.public_key], 1)],
        assets=[{"data": "QmW5GVMW98D3mktSDfWHS8nX2UiCd8gP1uCiujnFX4yK97"}],
    ).sign([alice.private_key])
    validated = b.validate_transaction(tx)
    b.models.store_bulk_transactions([validated])

    tx_obj = tx
    tx = tx.to_dict()
    compose_asset_cid = "bafkreignwcoye67vn6edp23mj4llhpzzkgyuefu7xesjzjxcv2bz3p4nfm"
    inputs_ = tx_obj.to_inputs()

    assets_ = [tx["id"], compose_asset_cid]
    compose_transaction = Compose.generate(inputs=inputs_, recipients=[([alice.public_key], 1)], assets=assets_)
    signed_compose_tx = compose_transaction.sign([alice.private_key])
    compose_dict = signed_compose_tx.to_dict()
    compose_obj = Transaction.from_dict(compose_dict)
    validated_compose = b.validate_transaction(compose_obj)
    b.models.store_bulk_transactions([validated_compose])


@pytest.mark.abci
def test_post_transaction_compose_valid(client, b):
    mode = ("?mode=commit", BROADCAST_TX_COMMIT)
    alice = generate_key_pair()
    tx = Create.generate(
        [alice.public_key],
        [([alice.public_key], 1)],
        assets=[{"data": "QmW5GVMW98D3mktSDfWHS8nX2UiCd8gP1uCiujnFX4yK97"}],
    ).sign([alice.private_key])
    mode_endpoint = TX_ENDPOINT + mode[0]
    response = client.post(mode_endpoint, data=json.dumps(tx.to_dict()))
    assert "202 ACCEPTED" in response.status
    tx_obj = tx
    tx = tx.to_dict()
    compose_asset_cid = "bafkreignwcoye67vn6edp23mj4llhpzzkgyuefu7xesjzjxcv2bz3p4nfm"
    inputs_ = tx_obj.to_inputs()

    assets_ = [tx["id"], compose_asset_cid]
    compose_transaction = Compose.generate(inputs=inputs_, recipients=[([alice.public_key], 1)], assets=assets_)
    signed_tx = compose_transaction.sign([alice.private_key])
    validated_compose = b.validate_transaction(signed_tx)
    mode_endpoint = TX_ENDPOINT + "?mode=commit"
    response = client.post(mode_endpoint, data=json.dumps(signed_tx.to_dict()))
    assert "202 ACCEPTED" in response.status


@pytest.mark.abci
def test_post_transaction_decompose_valid(client, b):
    mode = ("?mode=commit", BROADCAST_TX_COMMIT)
    alice = generate_key_pair()
    tx = Create.generate(
        [alice.public_key],
        [([alice.public_key], 1)],
        assets=[{"data": "QmW5GVMW98D3mktSDfWHS8nX2UiCd8gP1uCiujnFX4yK97"}],
    ).sign([alice.private_key])
    mode_endpoint = TX_ENDPOINT + mode[0]
    response = client.post(mode_endpoint, data=json.dumps(tx.to_dict()))
    assert "202 ACCEPTED" in response.status
    tx_obj = tx
    tx = tx.to_dict()
    inputs_ = tx_obj.to_inputs()

    assets = [
        tx["id"],
        "bafkreiawyk3ou5qzqec4ggbvrs56dv5ske2viwprf6he5wj5gr4yv5orsu",
        "bafkreibncbonglm6mi3znbrqbchk56wmgftk4gfevxqlgeif3g5jdotcka",
        "bafkreibkokzihpnnyqf3xslcievqkadf2ozkdi72wyibijih447vq42kjm",
    ]
    recipients = [([alice.public_key], 1), ([alice.public_key], 2), ([alice.public_key], 3)]
    decompose_transaction = Decompose.generate(inputs=inputs_, recipients=recipients, assets=assets)
    signed_tx = decompose_transaction.sign([alice.private_key])
    validated_decompose = b.validate_transaction(signed_tx)
    mode_endpoint = TX_ENDPOINT + "?mode=commit"
    response = client.post(mode_endpoint, data=json.dumps(signed_tx.to_dict()))
    assert "202 ACCEPTED" in response.status
