from serato_bpm_cleanup.detect import _looks_like_serato_process


def test_serato_dj_pro_detected():
    assert _looks_like_serato_process("Serato DJ Pro.exe")
    assert _looks_like_serato_process("Serato.exe")
    mac = "/Applications/Serato DJ Pro.app/Contents/MacOS/Serato DJ Pro"
    assert _looks_like_serato_process(mac)


def test_this_cli_is_not_serato():
    assert not _looks_like_serato_process("serato-bpm-cleanup")
    assert not _looks_like_serato_process("python serato_bpm_cleanup")
    assert not _looks_like_serato_process("chrome.exe")
