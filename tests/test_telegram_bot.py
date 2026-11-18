from flowdesk.bot import Bot
from flowdesk.journal import Journal


class FakeTG:
    def __init__(self, chat_id=""):
        self.token, self.chat_id, self.sent = "x", chat_id, []

    @property
    def enabled(self):
        return bool(self.chat_id)

    def send(self, text, chat_id=None, buttons=None):
        self.sent.append((chat_id, text)); return True

    def call(self, *a, **k):
        return {"ok": True}


def upd(uid, chat, text, typ="private"):
    return {"update_id": uid, "message": {"chat": {"id": chat, "type": typ}, "text": text}}


def test_owner_claim_and_replies(tmp_path, monkeypatch):
    import flowdesk.config as c
    monkeypatch.setattr(c, "ROOT", tmp_path)
    tg = FakeTG()
    b = Bot(journal=Journal(":memory:"), tg=tg)
    assert b.handle_update(upd(1, 111, "/start"))
    assert tg.chat_id == "111" and "connected" in tg.sent[-1][1]
    assert (tmp_path / ".env").read_text().strip() == "FLOWDESK_TELEGRAM_CHAT_ID=111"
    assert b.handle_update(upd(2, 111, "hello there"))          # plain text -> help
    assert "/check" in tg.sent[-1][1]
    assert b.handle_update(upd(3, 111, "/nonsense"))
    assert "/check" in tg.sent[-1][1]
    n = len(tg.sent)
    assert not b.handle_update(upd(4, 222, "/start"))           # strangers ignored
    assert len(tg.sent) == n


def test_group_cannot_claim():
    tg = FakeTG()
    b = Bot(journal=Journal(":memory:"), tg=tg)
    assert not b.handle_update(upd(1, -5, "/start", "group")) and tg.chat_id == ""
