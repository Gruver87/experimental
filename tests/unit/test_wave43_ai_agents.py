"""Wave 43 — AI Agent Manager SQLite persistence + plasma submit hint."""
import os
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)


def test_ai_agent_create_persists_and_charges_fee():
    from features.ai_manager import AIAgentManager
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "ai.db"))
    db.initialize()
    owner = "0x" + "a" * 40
    db.set_balance(owner, 5.0)

    m1 = AIAgentManager(db=db)
    aid = m1.create_agent("Trader1", owner, "transformer")
    assert aid
    assert db.get_balance(owner) == 5.0 - m1.CREATE_FEE

    m2 = AIAgentManager(db=db)
    assert aid in m2.agents
    assert m2.get_stats()["persisted"] is True


def test_ai_agent_trade_fails_without_execution_backend():
    from features.ai_manager import AIAgentManager
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "at.db"))
    db.initialize()
    owner = "0x" + "b" * 40
    db.set_balance(owner, 10.0)

    m = AIAgentManager(db=db)
    aid = m.create_agent("Bot", owner)
    out = m.trade(aid, "buy", 1.0, 100.0)
    assert out == {"success": False, "error": "Trade execution backend not configured"}


def test_ai_agent_trade_persists_executor_result():
    from features.ai_manager import AIAgentManager
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "atex.db"))
    db.initialize()
    owner = "0x" + "d" * 40
    db.set_balance(owner, 10.0)

    def executor(order):
        assert order["type"] == "buy"
        assert order["amount"] == 1.0
        return {
            "success": True,
            "trade_id": "venue-trade-1",
            "pnl": 2.5,
            "venue": "test-exchange",
            "status": "filled",
        }

    m = AIAgentManager(db=db, trade_executor=executor)
    aid = m.create_agent("Bot", owner)
    out = m.trade(aid, "buy", 1.0, 100.0)
    assert out["success"] is True
    assert out["trade_id"] == "venue-trade-1"
    assert out["pnl"] == 2.5

    m2 = AIAgentManager(db=db)
    agent = m2.get_agent(aid)
    assert agent.actions_count == 1
    assert len(agent.memory) == 1
    assert agent.memory[0]["venue"] == "test-exchange"


def test_ai_create_rejects_low_balance():
    from features.ai_manager import AIAgentManager
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "ar.db"))
    db.initialize()
    owner = "0x" + "c" * 40
    db.set_balance(owner, 0.001)

    m = AIAgentManager(db=db)
    assert m.create_agent("X", owner) is None


def test_ai_create_requires_balance_backend():
    from features.ai_manager import AIAgentManager

    m = AIAgentManager(db=None)
    assert m.create_agent("NoBackend", "0x" + "e" * 40) is None


def test_ai_agent_trade_requires_active_agent_and_final_execution():
    from features.ai_manager import AIAgentManager
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "inactive.db"))
    db.initialize()
    owner = "0x" + "f" * 40
    db.set_balance(owner, 10.0)

    def pending_executor(_order):
        return {
            "success": True,
            "trade_id": "venue-trade-pending",
            "status": "pending",
        }

    m = AIAgentManager(db=db, trade_executor=pending_executor)
    aid = m.create_agent("Bot", owner)
    out = m.trade(aid, "buy", 1.0, 100.0)
    assert out == {"success": False, "error": "Trade execution not final: pending"}
    assert m.get_agent(aid).actions_count == 0

    assert m.deactivate(aid) is True
    assert m.deactivate(aid) is False
    assert m.trade(aid, "buy", 1.0, 100.0) == {
        "success": False,
        "error": "Agent is not active",
    }


def test_ai_agent_profit_is_satoshi_quantized_bool_refused():
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "ai-money.db"))
    db.initialize()
    db.save_ai_agent(
        {
            "agent_id": "a1",
            "name": "Bot",
            "owner": "0x" + "a" * 40,
            "performance_score": 0.333,
            "total_profit": 1.0000003,
            "created_at": 1,
        }
    )
    row = db.get_ai_agents()[0]
    assert row["total_profit"] == 1.0
    assert row["performance_score"] == 0.333
    with pytest.raises(TypeError, match="bool is not an amount"):
        db.save_ai_agent(
            {
                "agent_id": "a2",
                "name": "Bot",
                "owner": "0x" + "b" * 40,
                "total_profit": True,
                "created_at": 1,
            }
        )
    with pytest.raises(ValueError, match="must be a number, not bool"):
        db.save_ai_agent(
            {
                "agent_id": "a3",
                "name": "Bot",
                "owner": "0x" + "c" * 40,
                "performance_score": True,
                "created_at": 1,
            }
        )
