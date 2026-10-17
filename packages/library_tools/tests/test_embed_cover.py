from pathlib import Path

from library_tools.embed_cover import (
    EmbedJob,
    apply_jobs,
    embed_cover,
    is_final_image,
    main,
    match_folder_to_mp3s,
    plan_embeds,
    tokens,
)
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3

# 1x1 PNG
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a4944415478da63000100000500010d0a2db40000000049454e44ae426082"
)


def _tiny_mp3(path: Path) -> None:
    path.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 256)
    EasyID3().save(path)


def test_tokens_normalize_ampersand_and_stopwords():
    assert "sound" in tokens("These are the Times x Safe & Sound")
    assert "and" not in tokens("Safe & Sound")
    assert "mashup" not in tokens("What It Sounds Like Mashup")
    assert tokens("Whistle x Final Breath") == tokens("Final Breath x Whistle")


def test_is_final_image():
    assert is_final_image(Path("final.png"))
    assert is_final_image(Path("final.JPG"))
    assert is_final_image(Path("cover-final.png"))
    assert is_final_image(Path("cover_final.webp"))
    assert not is_final_image(Path("final_V2.mp4"))
    assert not is_final_image(Path("ChatGPT Image.png"))
    assert not is_final_image(Path("CHOSEN-harry-illenium-clean.png"))


def test_match_swapped_titles_and_typos():
    mp3s = [
        Path("Whistle x Final Breath.mp3"),
        Path("DJ Got Us Fallin' in Love x One of These Mornings.mp3"),
        Path("Rude Boy x Take Me Away.mp3"),
    ]
    assert match_folder_to_mp3s("Final Breath x Whistle", mp3s) == [mp3s[0]]
    assert match_folder_to_mp3s("DJ Got Us Fallin' In Love x One of These Momements", mp3s) == [
        mp3s[1]
    ]
    assert match_folder_to_mp3s("Rude Boy", mp3s) == [mp3s[2]]


def test_match_edit_and_mashup_pair():
    mp3s = [
        Path("Beautiful Soul x Lonely [HuntingSzn Edit].mp3"),
        Path("Beautiful Soul x Lonely [HuntingSzn Mashup].mp3"),
        Path("The Cure x Pray [HuntingSzn Mashup].mp3"),
    ]
    hits = match_folder_to_mp3s("Beautiful Soul  x Lonely", mp3s)
    assert mp3s[0] in hits
    assert mp3s[1] in hits
    assert mp3s[2] not in hits


def test_match_sign_of_the_times_does_not_hit_these_are_the_times():
    mp3s = [
        Path("Sign of the Times x Sideways x Hollow x Falling Fast [HuntingSzn Edit].mp3"),
        Path("These are the Times x Safe and Sound.mp3"),
    ]
    assert match_folder_to_mp3s("Sign of the Times x Sideways", mp3s) == [mp3s[0]]
    assert match_folder_to_mp3s("These are the Times x Safe & Sound", mp3s) == [mp3s[1]]


def test_plan_uses_release_folder_not_nested_parent(tmp_path: Path):
    music = tmp_path / "music"
    releases = tmp_path / "releases"
    music.mkdir()
    nested = releases / "The Cure x Pray" / "03-finals"
    nested.mkdir(parents=True)
    _tiny_mp3(music / "The Cure x Pray [HuntingSzn Mashup].mp3")
    (nested / "final.png").write_bytes(TINY_PNG)

    plan = plan_embeds(music, releases)
    assert len(plan.jobs) == 1
    assert plan.jobs[0].folder == "The Cure x Pray"
    assert plan.jobs[0].image.name == "final.png"
    assert plan.unmatched_finals == []
    assert plan.leftover_mp3s == []


def test_plan_skips_appledouble_and_reports_leftover(tmp_path: Path):
    music = tmp_path / "music"
    releases = tmp_path / "releases"
    music.mkdir()
    (releases / "Hot Girl Bummer").mkdir(parents=True)
    keep = music / "Hot Girl Bummer Remix v5.mp3"
    leftover = music / "Five More Hours (Sumant Remix) [HuntingSzn Flip].mp3"
    _tiny_mp3(keep)
    _tiny_mp3(leftover)
    (music / ("._" + keep.name)).write_bytes(b"not audio")
    (releases / "Hot Girl Bummer" / "final.png").write_bytes(TINY_PNG)

    plan = plan_embeds(music, releases)
    assert [job.mp3.name for job in plan.jobs] == [keep.name]
    assert [path.name for path in plan.leftover_mp3s] == [leftover.name]


def test_embed_writes_apic(tmp_path: Path):
    mp3 = tmp_path / "track.mp3"
    image = tmp_path / "final.png"
    _tiny_mp3(mp3)
    image.write_bytes(TINY_PNG)
    embed_cover(mp3, image)
    apics = ID3(mp3).getall("APIC")
    assert len(apics) == 1
    assert apics[0].mime == "image/png"
    assert bytes(apics[0].data) == TINY_PNG


def test_apply_jobs_skip_existing_and_already_ok(tmp_path: Path):
    mp3 = tmp_path / "track.mp3"
    image = tmp_path / "final.png"
    other = tmp_path / "other.png"
    _tiny_mp3(mp3)
    image.write_bytes(TINY_PNG)
    other.write_bytes(TINY_PNG + b"\x00")
    embed_cover(mp3, image)

    stats = apply_jobs(
        [EmbedJob(mp3=mp3, image=image, folder="x")],
        dry_run=False,
        skip_existing=True,
    )
    assert stats["skipped"] == 1

    stats = apply_jobs(
        [EmbedJob(mp3=mp3, image=image, folder="x")],
        dry_run=False,
        skip_existing=False,
    )
    assert stats["already_ok"] == 1

    stats = apply_jobs(
        [EmbedJob(mp3=mp3, image=other, folder="x")],
        dry_run=True,
        skip_existing=False,
    )
    assert stats["embedded"] == 1
    assert bytes(ID3(mp3).getall("APIC")[0].data) == TINY_PNG


def test_main_explicit_pair_and_batch_dry_run(tmp_path: Path, capsys):
    music = tmp_path / "music"
    releases = tmp_path / "releases" / "Empire State of Mind"
    music.mkdir()
    releases.mkdir(parents=True)
    mp3 = music / "Empire State of Mind (HuntingSzn Remix).mp3"
    image = releases / "final.png"
    leftover = music / "Five More Hours (Sumant Remix) [HuntingSzn Flip].mp3"
    _tiny_mp3(mp3)
    _tiny_mp3(leftover)
    image.write_bytes(TINY_PNG)

    assert main(["--mp3", str(mp3), "--image", str(image)]) == 0
    assert ID3(mp3).getall("APIC")

    code = main(
        [
            "--music",
            str(music),
            "--releases",
            str(releases.parent),
            "--dry-run",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "no cover: Five More Hours" in out
    assert "already_ok:" in out


def test_main_unmatched_final_exits_one(tmp_path: Path):
    music = tmp_path / "music"
    releases = tmp_path / "releases" / "Unknown Mashup"
    music.mkdir()
    releases.mkdir(parents=True)
    _tiny_mp3(music / "Rude Boy x Take Me Away.mp3")
    (releases / "final.png").write_bytes(TINY_PNG)
    assert main(["--music", str(music), "--releases", str(releases.parent)]) == 1
