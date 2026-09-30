from obd_reader.adapter import INIT, identify, init_adapter
from obd_reader.replay import ReplayPort
from obd_reader.transport import Transport


def records(pairs):
    return [{"tx": tx, "rx": rx} for tx, rx in pairs]


def test_init_sends_reset_echo_linefeed_headers_and_the_protocol():
    port = ReplayPort(records([("ATZ", ["ELM327 v1.4b"]), ("ATE0", ["OK"]), ("ATL0", ["OK"]),
                               ("ATH0", ["OK"]), ("ATSP0", ["OK"])]))
    init_adapter(Transport(port), "0")
    assert port.written == [*INIT, "ATSP0"]
    assert port.unmatched == []


def test_init_without_protocol_does_not_send_atsp():
    port = ReplayPort(records([(c, ["OK"]) for c in INIT]))
    init_adapter(Transport(port), None)
    assert port.written == list(INIT)


def test_identify_reports_genuine_stn():
    port = ReplayPort(records([("ATI", ["ELM327 v1.4b"]), ("STI", ["STN2232 v5.12.4"])]))
    a = identify(Transport(port))
    assert (a.ati, a.sti, a.chip, a.genuine_stn) == ("ELM327 v1.4b", "STN2232 v5.12.4", "STN2232", True)


def test_identify_reports_a_plain_elm_when_sti_is_unknown():
    port = ReplayPort(records([("ATI", ["ELM327 v1.5"]), ("STI", ["?"])]))
    a = identify(Transport(port))
    assert a.genuine_stn is False and a.chip is None and a.sti is None
