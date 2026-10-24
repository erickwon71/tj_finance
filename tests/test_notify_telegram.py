"""notify_telegram sends one short line through telegram.sh and never sends in tests."""
import stat

from scripts import notify


def _script(tmp_path, exit_code, out="args.txt"):
    s = tmp_path / "telegram.sh"
    s.write_text(f'#!/bin/bash\nprintf "%s" "$1" > "{tmp_path / out}"\nexit {exit_code}\n')
    s.chmod(s.stat().st_mode | stat.S_IEXEC)
    return s


def test_one_line_and_length(tmp_path, monkeypatch):
    s = _script(tmp_path, 0)
    monkeypatch.setenv("TJ_TELEGRAM_SH", str(s))
    assert notify.notify_telegram("미러 *실패*", "line1\nline2 " + "x" * 400) is True
    sent = (tmp_path / "args.txt").read_text()
    assert "\n" not in sent and "*" not in sent
    assert len(sent) <= notify.TELEGRAM_MAX_CHARS and sent.startswith("[TJ Finance] 미러 실패")


def test_exit_3_is_not_delivered(tmp_path, monkeypatch):
    monkeypatch.setenv("TJ_TELEGRAM_SH", str(_script(tmp_path, 3)))
    assert notify.notify_telegram("t", "m") is False


def test_missing_script_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setenv("TJ_TELEGRAM_SH", str(tmp_path / "nope.sh"))
    assert notify.notify_telegram("t", "m") is False


def test_notify_failure_is_suppressed_under_pytest(tmp_path, monkeypatch):
    s = _script(tmp_path, 0)
    monkeypatch.setenv("TJ_TELEGRAM_SH", str(s))
    notify.notify_failure("t", "m")                 # PYTEST_CURRENT_TEST is set -> nothing sent
    assert not (tmp_path / "args.txt").exists()
