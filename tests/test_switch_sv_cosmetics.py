"""Held channels in source color selectors must not interpolate between forms."""
import struct
from types import SimpleNamespace

import pytest

from rae.platforms.switch import sv_cosmetics
from rae.platforms.switch.flatbuf import TableFields

pytestmark=pytest.mark.switch


def test_form_selector_samples_exact_keys_and_holds_omitted_channels(monkeypatch):
    data=bytearray(28)
    for offset,value in ((4,0.),(8,.25),(12,1.),(16,.75),(20,165.),(24,.75)):
        struct.pack_into('<f',data,offset,value)
    monkeypatch.setattr(sv_cosmetics.fb,'read_table_vector',lambda *_:[
        TableFields([4,8]),TableFields([12,16]),TableFields([20,24])])
    table=SimpleNamespace(get=lambda _:0)
    assert sv_cosmetics._curve(data,table,0)==.25
    assert sv_cosmetics._curve(data,table,1)==.75
    assert sv_cosmetics._curve(data,table,3)==.75
