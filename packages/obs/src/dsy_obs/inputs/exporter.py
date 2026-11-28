"""One pass over the state inputs, kept as gauges on a Temporal runtime's meter.

An input that fails keeps the value it last had, which a Temporal gauge holds until it is set
again, and is counted in `Exporter.errors`.

`dsy-stateops` and `psycopg` come with the optional extra `stateops`, so they are imported where
they are used and the package still imports in a process that never runs the exporter.
"""

import logging
import re
from collections import Counter
from collections.abc import Iterable
from typing import TYPE_CHECKING

from temporalio.common import MetricMeter

if TYPE_CHECKING:
    import psycopg
    from dsy_stateops.inputs import Input, Inputs

log = logging.getLogger(__name__)

# The store inputs need `kubectl exec` into the store pod and its credentials, so they stay out.
EXPORTED = ("sql", "sql_labelled", "invariants")
SUFFIXED_UNITS = {"bytes": "_bytes", "seconds": "_seconds"}
LABELLED = re.compile(r"(?P<name>\w+)\{(?P<label>\w+)=(?P<value>.*)\}")
CONNECT_SECONDS = 5
# A slow query ends at the timeout and counts as an error, so one input never holds a pass.
STATEMENT_TIMEOUT = "30s"


def metric_name(item: "Input") -> str:
    """`dsy_state_<name>`, with the unit appended when it is bytes or seconds and the name does
    not already end in it."""
    suffix = SUFFIXED_UNITS.get(item.unit, "")
    return f"dsy_state_{item.name}" + ("" if item.name.endswith(suffix) else suffix)


class Exporter:
    def __init__(self, meter: MetricMeter, dsn: str, inputs: "Inputs"):
        self.dsn = dsn
        self.inputs = [i for i in inputs.inputs if i.source.kind in EXPORTED]
        self.errors: Counter[str] = Counter()
        self._gauges = {
            i.name: meter.create_gauge_float(metric_name(i), f"State input {i.name}, in {i.unit}.")
            for i in self.inputs
        }

    def run_once(self) -> int:
        """Reads every input and sets its gauges; returns the number of inputs that were read."""
        import psycopg
        from dsy_servicekit import pg

        try:
            conn = pg.connect(
                self.dsn,
                autocommit=True,
                connect_timeout=CONNECT_SECONDS,
                statement_timeout=STATEMENT_TIMEOUT,
            )
        except psycopg.Error as error:
            for item in self.inputs:
                self._failed(item, error)
            return 0
        with conn:
            return sum(self._read(conn, item) for item in self.inputs)

    def _read(self, conn: "psycopg.Connection", item: "Input") -> bool:
        from dsy_stateops.inputs import Inputs, collect_inputs

        try:
            values = collect_inputs(conn, Inputs(inputs=[item])).values
        except Exception as error:  # noqa: BLE001
            # Any failure of one input, a refused query included, leaves the others to run.
            self._failed(item, error)
            return False
        self._set(item, values)
        return True

    def _set(self, item: "Input", values: Iterable[tuple[str, int | float]]) -> None:
        for name, value in values:
            labelled = LABELLED.fullmatch(name)
            labels = {labelled["label"]: labelled["value"]} if labelled else None
            if value < 0:
                # A Temporal gauge rejects a negative value, which would end the process.
                self.errors[item.name] += 1
                log.error("state input %s: %s is negative (%s), skipped", item.name, name, value)
                continue
            self._gauges[item.name].set(float(value), labels)

    def _failed(self, item: "Input", error: Exception) -> None:
        self.errors[item.name] += 1
        log.error("state input %s failed: %s", item.name, " ".join(str(error).split()))
