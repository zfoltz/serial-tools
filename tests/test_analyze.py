from serialtools.analyze import diff, errors, full_report, render_text, summary, timing


def test_summary(conversation):
    r = summary.analyze(conversation)
    assert r["frames"] == 9
    assert r["directions"]["MASTER"]["frames"] == 5
    assert r["directions"]["SLAVE"]["frames"] == 4
    assert r["directions"]["MASTER"]["frame_len"]["median"] == 8


def test_timing_finds_the_unanswered_poll_and_the_silence(conversation):
    r = timing.analyze(conversation, silence_ms=5000.0)
    assert r["request_dir"] == "MASTER"
    assert r["requests"] == 5
    assert len(r["unanswered"]) == 1
    assert r["latency_ms"]["count"] == 4
    assert 19.0 < r["latency_ms"]["median"] < 21.0
    assert len(r["silence_gaps"]) == 1
    assert r["silence_gaps"][0]["silence_ms"] >= 11000


def test_errors_counts_integrity_and_retries(conversation):
    conversation[0].decode = {"proto": "modbus_rtu", "ok": False, "summary": "",
                              "errors": ["crc_mismatch"]}
    conversation[2].decode = {"proto": "modbus_rtu", "ok": True, "summary": ""}
    r = errors.analyze(conversation)
    assert r["error_counts"]["crc_mismatch"] == 1
    assert r["integrity_error_rate"] == 0.5  # 1 of 2 decoded frames
    # identical MASTER polls 1s apart count as retries only within 2s: all do
    assert r["retries"] >= 1


def test_full_report_renders(conversation):
    text = render_text(full_report(conversation))
    assert "== summary ==" in text
    assert "UNANSWERED" in text


def test_diff_flags_new_errors(conversation):
    import copy
    good = copy.deepcopy(conversation)
    bad = copy.deepcopy(conversation)
    bad[1].decode = {"proto": "x", "ok": False, "summary": "", "errors": ["crc_mismatch"]}
    r = diff.analyze(good, bad)
    assert "crc_mismatch" in r["bad_error_types"]
    assert "crc_mismatch" not in r["good_error_types"]
    lines = "\n".join(diff.render(r))
    assert "crc_mismatch" in lines
