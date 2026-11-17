"""RFC 8785 附录 B 的数字向量与 §3.2.2、§3.2.3 的示例。"""
import json
import struct

import pytest

from paoding_graph.jcs import JCSError, canonicalize

VECTORS = [
    ("0000000000000000", "0"), ("8000000000000000", "0"),
    ("0000000000000001", "5e-324"), ("8000000000000001", "-5e-324"),
    ("7fefffffffffffff", "1.7976931348623157e+308"), ("ffefffffffffffff", "-1.7976931348623157e+308"),
    ("4340000000000000", "9007199254740992"), ("c340000000000000", "-9007199254740992"),
    ("4430000000000000", "295147905179352830000"),
    ("44b52d02c7e14af5", "9.999999999999997e+22"), ("44b52d02c7e14af6", "1e+23"),
    ("44b52d02c7e14af7", "1.0000000000000001e+23"),
    ("444b1ae4d6e2ef4e", "999999999999999700000"), ("444b1ae4d6e2ef4f", "999999999999999900000"),
    ("444b1ae4d6e2ef50", "1e+21"),
    ("3eb0c6f7a0b5ed8c", "9.999999999999997e-7"), ("3eb0c6f7a0b5ed8d", "0.000001"),
    ("41b3de4355555553", "333333333.3333332"), ("41b3de4355555554", "333333333.33333325"),
    ("41b3de4355555555", "333333333.3333333"), ("41b3de4355555556", "333333333.3333334"),
    ("41b3de4355555557", "333333333.33333343"),
    ("becbf647612f3696", "-0.0000033333333333333333"), ("43143ff3c1cb0959", "1424953923781206.2"),
]


@pytest.mark.parametrize("bits,want", VECTORS)
def test_numbers(bits, want):
    x = struct.unpack(">d", bytes.fromhex(bits))[0]
    assert canonicalize(x).decode() == want


def test_rfc_example():
    src = ('{"numbers":[333333333.33333329,1E30,4.50,2e-3,0.000000000000000000000000001],'
           '"string":"\\u20ac$\\u000F\\u000aA\'\\u0042\\u0022\\u005c\\\\\\"\\/",'
           '"literals":[null,true,false]}')
    want = ('{"literals":[null,true,false],"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],'
            '"string":"€$\\u000f\\nA\'B\\"\\\\\\\\\\"/"}')
    assert canonicalize(json.loads(src)).decode() == want


def test_key_order_is_utf16():
    keys = ["€", "\r", "דּ", "1", "\U0001F600", "\u0080", "ö"]
    out = canonicalize({k: 0 for k in keys}).decode()
    order = [json.loads("{" + p + "}") for p in out[1:-1].split(",")]
    assert [list(o)[0] for o in order] == ["\r", "1", "\u0080", "ö", "€", "\U0001F600", "דּ"]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 2**53 + 1, {1: 2}, object()])
def test_rejects(bad):
    with pytest.raises(JCSError):
        canonicalize(bad)


def test_int_and_float_agree():
    assert canonicalize(1) == canonicalize(1.0) == b"1"
