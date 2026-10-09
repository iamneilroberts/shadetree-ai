import time

import pytest

from obd_reader.allowlist import ForbiddenCommand
from obd_reader.transport import SerialPort


def test_raw_mode_refuses_obd_commands_until_caf1(elm_server):
    url = elm_server([{"tx": "ATCAF0", "rx": ["OK"]}, {"tx": "ATCAF1", "rx": ["OK"]}, {"tx": "0104", "rx": ["41 04 00"]}])
    sp = SerialPort(url)
    try:
        sp.write(b"ATCAF0\r")
        assert "OK" in sp.read_until_prompt(2)
        with pytest.raises(ForbiddenCommand, match="raw CAN mode"):
            sp.write(b"0104\r")  # with CAF0 this would be a raw clear-codes frame
        sp.write(b"ATCAF1\r")
        assert "OK" in sp.read_until_prompt(2)
        sp.write(b"0104\r")
        assert "41 04 00" in sp.read_until_prompt(2)
    finally:
        sp.close()


def test_atcaf0_is_the_only_off_list_body_and_other_junk_is_still_refused():
    sp = SerialPort("loop://")
    try:
        for bad in (b"ATCAF 0\r", b"atcaf0\r", b"04\r", b"ATCSM0\r"):
            with pytest.raises(ForbiddenCommand):
                sp.write(bad)
    finally:
        sp.close()


def test_interrupt_sends_a_cr_only_while_a_reply_is_outstanding():
    sp = SerialPort("loop://")  # loop:// echoes what is written
    try:
        sp.interrupt()
        time.sleep(0.05)
        assert sp.read_available(0.2) == ""  # at the prompt a CR would repeat the last command
        sp.write(b"ATI\r")
        sp.interrupt()
        time.sleep(0.05)
        assert sp.read_available(0.3) == "ATI\r\r"
    finally:
        sp.close()
