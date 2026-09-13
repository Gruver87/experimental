#!/usr/bin/env python3
"""Smart account auth must fail closed without real verifiers."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from features.smart_accounts import AuthMethod, SessionPermission, SmartAccount, SmartAccountManager


def test_private_social_and_passkey_auth_fail_closed():
    account = SmartAccount("0x" + "a" * 40, "0x" + "b" * 40)
    account.add_auth_method(AuthMethod.PRIVATE_KEY, {"public_key": "0xpub"})
    account.add_auth_method(AuthMethod.SOCIAL, {"provider": "google"})
    account.add_auth_method(AuthMethod.PASSKEY, {"credential_id": "cred"})

    assert account.authenticate(AuthMethod.PRIVATE_KEY, "signed-message") is False
    assert account.authenticate(AuthMethod.SOCIAL, "provider-token") is False
    assert account.authenticate(AuthMethod.PASSKEY, {"assertion": "raw"}) is False


def test_session_key_auth_remains_bounded_by_validity():
    account = SmartAccount("0x" + "c" * 40, "0x" + "d" * 40)
    account.add_auth_method(AuthMethod.SESSION_KEY, {})
    session_key = account.create_session_key(
        [SessionPermission.TRANSFER],
        expires_in=60,
        max_uses=1,
    )
    key_id = session_key.split(".", 1)[0]

    assert account.authenticate(AuthMethod.SESSION_KEY, key_id) is False
    assert account.authenticate(AuthMethod.SESSION_KEY, session_key) is True
    account.session_keys[key_id].use()
    assert account.authenticate(AuthMethod.SESSION_KEY, session_key) is False


def test_manager_create_session_and_authenticate_fail_closed():
    manager = SmartAccountManager(
        transaction_executor=lambda tx: {"success": True, "tx_hash": "0xlab", **tx}
    )
    created = manager.create_account("0x" + "e" * 40)
    address = created["address"]

    assert created["success"] is True
    assert manager.authenticate(address, "raw-private-key-signature", "private_key") is False

    session = manager.create_session_key(address, [SessionPermission.TRANSFER], max_uses=1)
    assert session["success"] is True
    assert manager.authenticate(address, session["key_id"], "session_key") is False
    assert manager.authenticate(address, session["session_key"], "session_key") is True
    manager.get_account(address).session_keys[session["key_id"]].use()
    assert manager.authenticate(address, session["session_key"], "session_key") is False


def test_manager_create_account_refuses_ephemeral_unbound():
    manager = SmartAccountManager()
    created = manager.create_account("0x" + "e" * 40)
    assert created["success"] is False
    assert created.get("http_status") == 501
    assert created.get("error") == "smart_accounts_ephemeral_unbound"


def test_smart_account_transaction_requires_execution_backend():
    account = SmartAccount("0x" + "f" * 40, "0x" + "1" * 40)
    account.add_auth_method(AuthMethod.SESSION_KEY, {})
    session_key = account.create_session_key(
        [SessionPermission.TRANSFER],
        expires_in=60,
        max_uses=1,
    )

    assert account.execute_transaction(
        "0x" + "2" * 40,
        1.0,
        auth_method=AuthMethod.SESSION_KEY,
        credential=session_key,
    ) is None


def test_smart_account_transaction_uses_real_executor_and_consumes_session():
    calls = []

    def executor(tx):
        calls.append(tx)
        return {"success": True, "tx_hash": "0xabc", **tx}

    account = SmartAccount(
        "0x" + "3" * 40,
        "0x" + "4" * 40,
        transaction_executor=executor,
    )
    account.add_auth_method(AuthMethod.SESSION_KEY, {})
    session_key = account.create_session_key(
        [SessionPermission.TRANSFER],
        expires_in=60,
        max_uses=1,
    )

    result = account.execute_transaction(
        "0x" + "5" * 40,
        2.0,
        auth_method=AuthMethod.SESSION_KEY,
        credential=session_key,
    )

    assert result["success"] is True
    assert result["tx_hash"] == "0xabc"
    assert calls[0]["from"] == account.address
    assert account.execute_transaction(
        "0x" + "5" * 40,
        2.0,
        auth_method=AuthMethod.SESSION_KEY,
        credential=session_key,
    ) is None


def test_smart_account_recovery_requires_approved_guardian_majority():
    owner = "0x" + "a" * 40
    new_owner = "0x" + "b" * 40
    g1 = "0x" + "1" * 40
    g2 = "0x" + "2" * 40
    account = SmartAccount("0x" + "c" * 40, owner)
    account.guardian_verifier = lambda guardian, cred, rid: cred == f"sig:{guardian}"

    assert account.add_guardian(g1, "guardian-1") is True
    assert account.add_guardian(g2, "guardian-2") is True
    assert account.request_recovery(g1) is None

    assert account.approve_guardian(g1, owner) is True
    assert account.approve_guardian(g2, owner) is True
    request_id = account.request_recovery(g1)
    assert request_id

    # Unsigned address-only approval must fail (Wave K).
    assert account.approve_recovery(request_id, g1) is False

    assert account.approve_recovery(request_id, g1, credential=f"sig:{g1}") is True
    assert account.recovery_requests[request_id].status == "pending"
    assert account.execute_recovery(request_id, new_owner) is False

    assert account.approve_recovery(request_id, g2, credential=f"sig:{g2}") is True
    assert account.recovery_requests[request_id].status == "approved"
    assert account.execute_recovery(request_id, new_owner) is True
    assert account.owner == new_owner


def test_smart_account_recovery_rejects_invalid_new_owner():
    owner = "0x" + "d" * 40
    guardian = "0x" + "3" * 40
    account = SmartAccount("0x" + "e" * 40, owner)
    account.guardian_verifier = lambda guardian, cred, rid: bool(cred)
    account.add_guardian(guardian, "guardian")
    account.approve_guardian(guardian, owner)
    request_id = account.request_recovery(guardian)
    account.approve_recovery(request_id, guardian, credential="sig")

    assert account.execute_recovery(request_id, "") is False
    assert account.execute_recovery(request_id, owner) is False


def test_manager_recover_account_requires_real_guardian_quorum():
    manager = SmartAccountManager(
        transaction_executor=lambda tx: {"success": True, "tx_hash": "0xlab", **tx}
    )
    created = manager.create_account("0x" + "a" * 40)
    account = manager.get_account(created["address"])
    account.guardian_verifier = lambda guardian, cred, rid: cred == f"sig:{guardian}"
    g1 = "0x" + "1" * 40
    g2 = "0x" + "2" * 40
    new_owner = "0x" + "b" * 40

    account.add_guardian(g1, "guardian-1")
    account.add_guardian(g2, "guardian-2")

    assert manager.recover_account(
        created["address"], new_owner, [g1, g2], credentials=["sig:" + g1, "sig:" + g2]
    ) is False

    account.approve_guardian(g1, account.owner)
    assert manager.recover_account(
        created["address"], new_owner, [g1], credentials=["sig:" + g1]
    ) is True
    assert account.owner == new_owner

    created2 = manager.create_account("0x" + "c" * 40)
    account2 = manager.get_account(created2["address"])
    account2.guardian_verifier = lambda guardian, cred, rid: cred == f"sig:{guardian}"
    h1 = "0x" + "3" * 40
    h2 = "0x" + "4" * 40
    account2.add_guardian(h1, "guardian-1")
    account2.add_guardian(h2, "guardian-2")
    account2.approve_guardian(h1, account2.owner)
    account2.approve_guardian(h2, account2.owner)

    assert manager.recover_account(
        created2["address"], "0x" + "d" * 40, [h1], credentials=["sig:" + h1]
    ) is False
    assert manager.recover_account(
        created2["address"],
        "0x" + "d" * 40,
        [h1, h2],
        credentials=["sig:" + h1, "sig:" + h2],
    ) is True
