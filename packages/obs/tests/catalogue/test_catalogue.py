"""Every series a dashboard query or a rule expression reads is in the platform catalogue, and, with
`-m cluster` after one `just smoke`, every catalogue entry has samples in Prometheus.

The live check needs `DSY_OBS_PROMETHEUS_URL`, and names each absent entry in its failure."""

import os
import time
from pathlib import Path

import pytest
from dsy_obs import catalogue

ROOT = Path(__file__).resolve().parents[4]
DASHBOARDS = sorted((ROOT / "deploy/obs/grafana/dashboards").glob("*.json"))
RULES = sorted((ROOT / "deploy/obs/prometheus/rules").glob("*.yaml"))
CATALOGUE = catalogue.load(ROOT)
SCRAPE_WAIT_S = 60


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("dsy_a_total", {"dsy_a_total"}),
        ('sum by (pool) (rate(dsy_a_total{pool="x"}[$__rate_interval]))', {"dsy_a_total"}),
        ("histogram_quantile(0.5, sum by (le) (rate(dsy_h_bucket[5m])))", {"dsy_h_bucket"}),
        ("a / on (pool) group_left (x) b > bool 1", {"a", "b"}),
        ('sum(x) unless label_replace(y, "z", "$1", "w", "(.*)")', {"x", "y"}),
        ('{__name__="dsy_c", job="j"}', {"dsy_c"}),
        ("count(max by (pod) (kube_pod_info offset 5m)) or vector(0)", {"kube_pod_info"}),
        ("topk(3, rate(a[1h])) * 100", {"a"}),
    ],
)
def test_series_names_of_an_expression(expr, expected):
    assert catalogue.series(expr) == expected


def test_there_are_dashboards_and_rules():
    assert DASHBOARDS
    assert RULES


@pytest.mark.parametrize("path", DASHBOARDS, ids=lambda p: p.stem)
def test_every_dashboard_series_is_catalogued(path):
    exprs = catalogue.dashboard_exprs(path)
    assert exprs
    assert not catalogue.uncatalogued(exprs, CATALOGUE)


@pytest.mark.parametrize("path", RULES, ids=lambda p: p.name)
def test_every_rule_series_is_catalogued(path):
    unknown = catalogue.uncatalogued(
        catalogue.rule_exprs(path), CATALOGUE, catalogue.recorded(path)
    )
    assert not unknown, sorted(unknown)


def test_a_dashboard_naming_an_unknown_series_fails_the_check(tmp_path):
    dashboard = tmp_path / "bad.json"
    dashboard.write_text(
        '{"panels": [{"datasource": {"type": "prometheus", "uid": "prometheus"}, "targets":'
        ' [{"expr": "sum(rate(dsy_nope_total[5m]))"}]}]}'
    )
    assert catalogue.uncatalogued(catalogue.dashboard_exprs(dashboard), CATALOGUE) == {
        "dsy_nope_total"
    }


def test_a_rule_naming_an_unknown_series_fails_the_check(tmp_path):
    rules = tmp_path / "bad.yaml"
    rules.write_text(
        "groups:\n- name: g\n  rules:\n  - alert: A\n    expr: dsy_nope_total > 0\n"
        "  - record: dsy:ok\n    expr: dsy_admission_live_jobs\n"
        "  - alert: B\n    expr: dsy:ok > 1\n"
    )
    unknown = catalogue.uncatalogued(
        catalogue.rule_exprs(rules), CATALOGUE, catalogue.recorded(rules)
    )
    assert unknown == {"dsy_nope_total"}


def test_histogram_suffixes_are_the_catalogued_name():
    names = catalogue.names(CATALOGUE)
    assert "dsy_workflow_job_seconds_bucket" in names
    assert "dsy_workflow_jobs_total_bucket" not in names


def test_absent_lists_the_entries_with_no_sample(fake):
    small = {
        "metrics": {
            "dsy_a": {"type": "gauge"},
            "dsy_b_seconds": {"type": "histogram"},
            "dsy_c_total": {"type": "counter"},
        },
        "external": {"ext_d": {"type": "gauge"}, "ext_e": {"type": "gauge", "conditional": True}},
    }
    sample = [{"metric": {}, "value": [0, "1"]}]
    fake.vectors["count(last_over_time(dsy_a[10m]))"] = sample
    fake.vectors["count(last_over_time(dsy_b_seconds_bucket[10m]))"] = sample
    assert catalogue.absent(fake.url, small) == ["dsy_c_total", "ext_d"]


@pytest.mark.cluster
def test_every_catalogue_entry_is_in_prometheus():
    # Selected on purpose, so a missing URL fails and does not pass by skipping.
    if not (url := os.environ.get("DSY_OBS_PROMETHEUS_URL")):
        pytest.fail("DSY_OBS_PROMETHEUS_URL is not set, point it at a forward of svc/prometheus")
    # A series written just before the check appears after the next scrape.
    deadline = time.monotonic() + SCRAPE_WAIT_S
    while (missing := catalogue.absent(url, CATALOGUE)) and time.monotonic() < deadline:
        time.sleep(5)
    assert not missing, f"{len(missing)} catalogue entries absent from Prometheus: {missing}"
