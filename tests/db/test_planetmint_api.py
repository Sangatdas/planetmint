# Copyright © 2020 Interplanetary Database Association e.V.,
# Planetmint and IPDB software contributors.
# SPDX-License-Identifier: (Apache-2.0 AND CC-BY-4.0)
# Code is Apache-2.0 and docs are CC-BY-4.0
import random
from unittest.mock import patch
import pytest
from base58 import b58decode
from ipld import marshal, multihash

from transactions.common import crypto
from transactions.common.transaction import TransactionLink
from transactions.common.transaction import Transaction
from transactions.types.assets.create import Create
from transactions.types.assets.transfer import Transfer
from planetmint.exceptions import CriticalDoubleSpend

pytestmark = pytest.mark.bdb


class TestBigchainApi(object):
    def test_get_spent_with_double_spend_detected(self, b, alice):
        from transactions.common.exceptions import DoubleSpend

        from planetmint.exceptions import CriticalDoubleSpend

        tx = Create.generate([alice.public_key], [([alice.public_key], 1)])
        tx = tx.sign([alice.private_key])

        b.models.store_bulk_transactions([tx])

        transfer_tx = Transfer.generate(tx.to_inputs(), [([alice.public_key], 1)], asset_ids=[tx.id])
        transfer_tx = transfer_tx.sign([alice.private_key])
        transfer_tx2 = Transfer.generate(tx.to_inputs(), [([alice.public_key], 2)], asset_ids=[tx.id])
        transfer_tx2 = transfer_tx2.sign([alice.private_key])

        with pytest.raises(DoubleSpend):
            b.validate_transaction(transfer_tx2, [transfer_tx])

        b.models.store_bulk_transactions([transfer_tx])

        with pytest.raises(DoubleSpend):
            b.validate_transaction(transfer_tx2)

        with pytest.raises(CriticalDoubleSpend):
            b.models.store_bulk_transactions([transfer_tx2])

    def test_double_inclusion(self, b, alice):
        from planetmint.backend.exceptions import OperationError
        from planetmint.backend.tarantool.sync_io.connection import TarantoolDBConnection

        tx = Create.generate([alice.public_key], [([alice.public_key], 1)])
        tx = tx.sign([alice.private_key])

        b.models.store_bulk_transactions([tx])
        if isinstance(b.models.connection, TarantoolDBConnection):
            with pytest.raises(CriticalDoubleSpend):
                b.models.store_bulk_transactions([tx])
        else:
            with pytest.raises(OperationError):
                b.models.store_bulk_transactions([tx])

    @pytest.mark.usefixtures("inputs")
    def test_non_create_input_not_found(self, b, user_pk):
        from planetmint_cryptoconditions import Ed25519Sha256
        from transactions.common.exceptions import InputDoesNotExist
        from transactions.common.transaction import Input, TransactionLink

        # Create an input for a non existing transaction
        input = Input(
            Ed25519Sha256(public_key=b58decode(user_pk)), [user_pk], TransactionLink("somethingsomething", 0)
        )
        tx = Transfer.generate([input], [([user_pk], 1)], asset_ids=["mock_asset_link"])
        with pytest.raises(InputDoesNotExist):
            b.validate_transaction(tx)

    def test_write_transaction(self, b, user_sk, user_pk, alice, create_tx):
        asset1 = {"data": "QmaozNR7DZHQK1ZcU9p7QdrshMvXqWK6gpu5rmrkPdT3L4"}

        tx = Create.generate([alice.public_key], [([alice.public_key], 1)], assets=[asset1]).sign([alice.private_key])
        b.models.store_bulk_transactions([tx])

        tx_from_db = b.models.get_transaction(tx.id)

        before = tx.to_dict()
        after = tx_from_db.to_dict()

        assert before["assets"][0] == after["assets"][0]
        before.pop("assets", None)
        after.pop("assets", None)
        assert before == after


class TestTransactionValidation(object):
    def test_non_create_input_not_found(self, b, signed_transfer_tx):
        from transactions.common.exceptions import InputDoesNotExist
        from transactions.common.transaction import TransactionLink

        signed_transfer_tx.inputs[0].fulfills = TransactionLink("c", 0)
        with pytest.raises(InputDoesNotExist):
            b.validate_transaction(signed_transfer_tx)

    @pytest.mark.usefixtures("inputs")
    def test_non_create_valid_input_wrong_owner(self, b, user_pk):
        from transactions.common.crypto import generate_key_pair
        from transactions.common.exceptions import InvalidSignature

        input_tx = b.models.fastquery.get_outputs_by_public_key(user_pk).pop()
        input_transaction = b.models.get_transaction(input_tx.txid)
        sk, pk = generate_key_pair()
        tx = Create.generate([pk], [([user_pk], 1)])
        tx.operation = "TRANSFER"
        tx.assets = [{"id": input_transaction.id}]
        tx.inputs[0].fulfills = input_tx

        with pytest.raises(InvalidSignature):
            b.validate_transaction(tx)

    @pytest.mark.usefixtures("inputs")
    def test_non_create_double_spend(self, b, signed_create_tx, signed_transfer_tx, double_spend_tx):
        from transactions.common.exceptions import DoubleSpend

        b.models.store_bulk_transactions([signed_create_tx, signed_transfer_tx])

        with pytest.raises(DoubleSpend):
            b.validate_transaction(double_spend_tx)


class TestMultipleInputs(object):
    def test_transfer_single_owner_single_input(self, b, inputs, user_pk, user_sk):
        user2_sk, user2_pk = crypto.generate_key_pair()
        tx_link = b.models.fastquery.get_outputs_by_public_key(user_pk).pop()
        input_tx = b.models.get_transaction(tx_link.txid)
        tx_converted = Transaction.from_dict(input_tx.to_dict(), True)

        tx = Transfer.generate(tx_converted.to_inputs(), [([user2_pk], 1)], asset_ids=[input_tx.id])
        tx = tx.sign([user_sk])

        # validate transaction
        b.validate_transaction(tx)
        assert len(tx.inputs) == 1
        assert len(tx.outputs) == 1

    def test_single_owner_before_multiple_owners_after_single_input(self, b, user_sk, user_pk, inputs):
        user2_sk, user2_pk = crypto.generate_key_pair()
        user3_sk, user3_pk = crypto.generate_key_pair()
        tx_link = b.models.fastquery.get_outputs_by_public_key(user_pk).pop()

        input_tx = b.models.get_transaction(tx_link.txid)
        tx_converted = Transaction.from_dict(input_tx.to_dict(), True)

        tx = Transfer.generate(tx_converted.to_inputs(), [([user2_pk, user3_pk], 1)], asset_ids=[input_tx.id])
        tx = tx.sign([user_sk])

        b.validate_transaction(tx)
        assert len(tx.inputs) == 1
        assert len(tx.outputs) == 1

    @pytest.mark.usefixtures("inputs")
    def test_multiple_owners_before_single_owner_after_single_input(self, b, user_sk, user_pk, alice):
        user2_sk, user2_pk = crypto.generate_key_pair()
        user3_sk, user3_pk = crypto.generate_key_pair()

        tx = Create.generate([alice.public_key], [([user_pk, user2_pk], 1)])
        tx = tx.sign([alice.private_key])
        b.models.store_bulk_transactions([tx])

        owned_input = b.models.fastquery.get_outputs_by_public_key(user_pk).pop()
        input_tx = b.models.get_transaction(owned_input.txid)
        input_tx_converted = Transaction.from_dict(input_tx.to_dict(), True)

        transfer_tx = Transfer.generate(input_tx_converted.to_inputs(), [([user3_pk], 1)], asset_ids=[input_tx.id])
        transfer_tx = transfer_tx.sign([user_sk, user2_sk])

        # validate transaction
        b.validate_transaction(transfer_tx)
        assert len(transfer_tx.inputs) == 1
        assert len(transfer_tx.outputs) == 1

    @pytest.mark.usefixtures("inputs")
    def test_multiple_owners_before_multiple_owners_after_single_input(self, b, user_sk, user_pk, alice):
        user2_sk, user2_pk = crypto.generate_key_pair()
        user3_sk, user3_pk = crypto.generate_key_pair()
        user4_sk, user4_pk = crypto.generate_key_pair()

        tx = Create.generate([alice.public_key], [([user_pk, user2_pk], 1)])
        tx = tx.sign([alice.private_key])
        b.models.store_bulk_transactions([tx])

        # get input
        tx_link = b.models.fastquery.get_outputs_by_public_key(user_pk).pop()
        tx_input = b.models.get_transaction(tx_link.txid)
        input_tx_converted = Transaction.from_dict(tx_input.to_dict(), True)

        tx = Transfer.generate(input_tx_converted.to_inputs(), [([user3_pk, user4_pk], 1)], asset_ids=[tx_input.id])
        tx = tx.sign([user_sk, user2_sk])

        b.validate_transaction(tx)
        assert len(tx.inputs) == 1
        assert len(tx.outputs) == 1

    def test_get_owned_ids_single_tx_single_output(self, b, user_sk, user_pk, alice):
        user2_sk, user2_pk = crypto.generate_key_pair()

        tx = Create.generate([alice.public_key], [([user_pk], 1)])
        tx = tx.sign([alice.private_key])
        b.models.store_bulk_transactions([tx])

        owned_inputs_user1 = b.models.fastquery.get_outputs_by_public_key(user_pk)
        owned_inputs_user2 = b.models.fastquery.get_outputs_by_public_key(user2_pk)
        assert owned_inputs_user1 == [TransactionLink(tx.id, 0)]
        assert owned_inputs_user2 == []

        tx_transfer = Transfer.generate(tx.to_inputs(), [([user2_pk], 1)], asset_ids=[tx.id])
        tx_transfer = tx_transfer.sign([user_sk])
        b.models.store_bulk_transactions([tx_transfer])

        owned_inputs_user1 = b.models.fastquery.get_outputs_by_public_key(user_pk)
        owned_inputs_user2 = b.models.fastquery.get_outputs_by_public_key(user2_pk)

        assert owned_inputs_user1 == [TransactionLink(tx.id, 0)]
        assert owned_inputs_user2 == [TransactionLink(tx_transfer.id, 0)]

    def test_get_owned_ids_single_tx_multiple_outputs(self, b, user_sk, user_pk, alice):
        user2_sk, user2_pk = crypto.generate_key_pair()

        # create divisible asset
        tx_create = Create.generate([alice.public_key], [([user_pk], 1), ([user_pk], 1)])
        tx_create_signed = tx_create.sign([alice.private_key])
        b.models.store_bulk_transactions([tx_create_signed])

        # get input
        owned_inputs_user1 = b.models.fastquery.get_outputs_by_public_key(user_pk)
        owned_inputs_user2 = b.models.fastquery.get_outputs_by_public_key(user2_pk)

        expected_owned_inputs_user1 = [TransactionLink(tx_create.id, 0), TransactionLink(tx_create.id, 1)]
        assert owned_inputs_user1 == expected_owned_inputs_user1
        assert owned_inputs_user2 == []

        # transfer divisible asset divided in two outputs
        tx_transfer = Transfer.generate(
            tx_create.to_inputs(), [([user2_pk], 1), ([user2_pk], 1)], asset_ids=[tx_create.id]
        )
        tx_transfer_signed = tx_transfer.sign([user_sk])
        b.models.store_bulk_transactions([tx_transfer_signed])

        owned_inputs_user1 = b.models.fastquery.get_outputs_by_public_key(user_pk)
        owned_inputs_user2 = b.models.fastquery.get_outputs_by_public_key(user2_pk)
        assert owned_inputs_user1 == expected_owned_inputs_user1
        assert owned_inputs_user2 == [TransactionLink(tx_transfer.id, 0), TransactionLink(tx_transfer.id, 1)]

    def test_get_owned_ids_multiple_owners(self, b, user_sk, user_pk, alice):
        user2_sk, user2_pk = crypto.generate_key_pair()
        user3_sk, user3_pk = crypto.generate_key_pair()

        tx = Create.generate([alice.public_key], [([user_pk, user2_pk], 1)])
        tx = tx.sign([alice.private_key])

        b.models.store_bulk_transactions([tx])

        owned_inputs_user1 = b.models.fastquery.get_outputs_by_public_key(user_pk)
        owned_inputs_user2 = b.models.fastquery.get_outputs_by_public_key(user_pk)
        expected_owned_inputs_user1 = [TransactionLink(tx.id, 0)]

        assert owned_inputs_user1 == owned_inputs_user2
        assert owned_inputs_user1 == expected_owned_inputs_user1

        tx = Transfer.generate(tx.to_inputs(), [([user3_pk], 1)], asset_ids=[tx.id])
        tx = tx.sign([user_sk, user2_sk])
        b.models.store_bulk_transactions([tx])

        owned_inputs_user1 = b.models.fastquery.get_outputs_by_public_key(user_pk)
        owned_inputs_user2 = b.models.fastquery.get_outputs_by_public_key(user2_pk)
        spent_user1 = b.models.get_spent(tx.id, 0)

        assert owned_inputs_user1 == owned_inputs_user2
        assert not spent_user1

    def test_get_spent_single_tx_single_output(self, b, user_sk, user_pk, alice):
        user2_sk, user2_pk = crypto.generate_key_pair()

        tx = Create.generate([alice.public_key], [([user_pk], 1)])
        tx = tx.sign([alice.private_key])
        b.models.store_bulk_transactions([tx])

        owned_inputs_user1 = b.models.fastquery.get_outputs_by_public_key(user_pk).pop()

        # check spents
        input_txid = owned_inputs_user1.txid
        spent_inputs_user1 = b.models.get_spent(input_txid, 0)
        assert spent_inputs_user1 is None

        # create a transaction and send it
        tx = Transfer.generate(tx.to_inputs(), [([user2_pk], 1)], asset_ids=[tx.id])
        tx = tx.sign([user_sk])
        b.models.store_bulk_transactions([tx])

        spent_inputs_user1 = b.models.get_spent(input_txid, 0)
        assert spent_inputs_user1 == tx.to_dict()

    def test_get_spent_single_tx_multiple_outputs(self, b, user_sk, user_pk, alice):
        # create a new users
        user2_sk, user2_pk = crypto.generate_key_pair()

        # create a divisible asset with 3 outputs
        tx_create = Create.generate([alice.public_key], [([user_pk], 1), ([user_pk], 1), ([user_pk], 1)])
        tx_create_signed = tx_create.sign([alice.private_key])
        b.models.store_bulk_transactions([tx_create_signed])

        owned_inputs_user1 = b.models.fastquery.get_outputs_by_public_key(user_pk)

        # check spents
        for input_tx in owned_inputs_user1:
            assert b.models.get_spent(input_tx.txid, input_tx.output) is None

        # transfer the first 2 inputs
        tx_transfer = Transfer.generate(
            tx_create.to_inputs()[:2], [([user2_pk], 1), ([user2_pk], 1)], asset_ids=[tx_create.id]
        )
        tx_transfer_signed = tx_transfer.sign([user_sk])
        b.models.store_bulk_transactions([tx_transfer_signed])

        # check that used inputs are marked as spent
        for ffill in tx_create.to_inputs()[:2]:
            spent_tx = b.models.get_spent(ffill.fulfills.txid, ffill.fulfills.output)
            assert spent_tx == tx_transfer_signed.to_dict()

        # check if remaining transaction that was unspent is also perceived
        # spendable by Planetmint
        assert b.models.get_spent(tx_create.to_inputs()[2].fulfills.txid, 2) is None

    def test_get_spent_multiple_owners(self, b, user_sk, user_pk, alice):
        user2_sk, user2_pk = crypto.generate_key_pair()
        user3_sk, user3_pk = crypto.generate_key_pair()

        transactions = []
        for i in range(3):
            payload = multihash(marshal({"msg": random.random()}))
            tx = Create.generate([alice.public_key], [([user_pk, user2_pk], 1)], payload)
            tx = tx.sign([alice.private_key])
            transactions.append(tx)

        b.models.store_bulk_transactions(transactions)

        owned_inputs_user1 = b.models.fastquery.get_outputs_by_public_key(user_pk)
        # check spents
        for input_tx in owned_inputs_user1:
            assert b.models.get_spent(input_tx.txid, input_tx.output) is None

        # create a transaction
        tx = Transfer.generate(transactions[0].to_inputs(), [([user3_pk], 1)], asset_ids=[transactions[0].id])
        tx = tx.sign([user_sk, user2_sk])
        b.models.store_bulk_transactions([tx])

        # check that used inputs are marked as spent
        assert b.models.get_spent(transactions[0].id, 0) == tx.to_dict()
        # check that the other remain marked as unspent
        for unspent in transactions[1:]:
            assert b.models.get_spent(unspent.id, 0) is None


def test_get_outputs_filtered_only_unspent(b):
    from transactions.common.transaction import TransactionLink

    go = "planetmint.model.fastquery.FastQuery.get_outputs_by_public_key"
    with patch(go) as get_outputs:
        get_outputs.return_value = [TransactionLink("a", 1), TransactionLink("b", 2)]
        fs = "planetmint.model.fastquery.FastQuery.filter_spent_outputs"
        with patch(fs) as filter_spent:
            filter_spent.return_value = [TransactionLink("b", 2)]
            out = b.models.get_outputs_filtered("abc", spent=False)
    get_outputs.assert_called_once_with("abc")
    assert out == [TransactionLink("b", 2)]


def test_get_outputs_filtered_only_spent(b):
    from transactions.common.transaction import TransactionLink

    go = "planetmint.model.fastquery.FastQuery.get_outputs_by_public_key"
    with patch(go) as get_outputs:
        get_outputs.return_value = [TransactionLink("a", 1), TransactionLink("b", 2)]
        fs = "planetmint.model.fastquery.FastQuery.filter_unspent_outputs"
        with patch(fs) as filter_spent:
            filter_spent.return_value = [TransactionLink("b", 2)]
            out = b.models.get_outputs_filtered("abc", spent=True)
    get_outputs.assert_called_once_with("abc")
    assert out == [TransactionLink("b", 2)]


# @patch("planetmint.model.fastquery.FastQuery.filter_unspent_outputs")
# @patch("planetmint.model.fastquery.FastQuery.filter_spent_outputs")
def test_get_outputs_filtered(
    b,
    mocker,
):
    from transactions.common.transaction import TransactionLink

    mock_filter_spent_outputs = mocker.patch("planetmint.model.fastquery.FastQuery.filter_spent_outputs")
    mock_filter_unspent_outputs = mocker.patch("planetmint.model.fastquery.FastQuery.filter_unspent_outputs")

    go = "planetmint.model.fastquery.FastQuery.get_outputs_by_public_key"
    with patch(go) as get_outputs:
        get_outputs.return_value = [TransactionLink("a", 1), TransactionLink("b", 2)]
        out = b.models.get_outputs_filtered("abc")
    get_outputs.assert_called_once_with("abc")
    mock_filter_spent_outputs.assert_not_called()
    mock_filter_unspent_outputs.assert_not_called()
    assert out == get_outputs.return_value


def test_cant_spend_same_input_twice_in_tx(b, alice):
    """Recreate duplicated fulfillments bug
    https://github.com/planetmint/planetmint/issues/1099
    """
    from transactions.common.exceptions import DoubleSpend

    # create a divisible asset
    tx_create = Create.generate([alice.public_key], [([alice.public_key], 100)])
    tx_create_signed = tx_create.sign([alice.private_key])
    assert b.validate_transaction(tx_create_signed) == tx_create_signed
    b.models.store_bulk_transactions([tx_create_signed])

    # Create a transfer transaction with duplicated fulfillments
    dup_inputs = tx_create.to_inputs() + tx_create.to_inputs()
    tx_transfer = Transfer.generate(dup_inputs, [([alice.public_key], 200)], asset_ids=[tx_create.id])
    tx_transfer_signed = tx_transfer.sign([alice.private_key])
    with pytest.raises(DoubleSpend):
        b.validate_transaction(tx_transfer_signed)


def test_transaction_unicode(b, alice):
    import copy

    from transactions.common.utils import serialize

    # http://www.fileformat.info/info/unicode/char/1f37a/index.htm

    beer_python = [{"data": multihash(marshal({"beer": "\N{BEER MUG}"}))}]
    beer_json = {"data": multihash(marshal({"beer": "\N{BEER MUG}"}))}

    tx = (Create.generate([alice.public_key], [([alice.public_key], 100)], assets=beer_python)).sign(
        [alice.private_key]
    )

    tx_1 = copy.deepcopy(tx)
    b.models.store_bulk_transactions([tx])

    assert beer_json["data"] in serialize(tx_1.to_dict())
