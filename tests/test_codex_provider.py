"""The codex image provider (Codex CLI on the user's ChatGPT subscription)
and its delegation to cube_art-director's art.py.

Every subprocess goes through `image_providers._run`, which these tests
replace: no test ever launches a real Codex CLI or art.py.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest
from PIL import Image

import gen_sprites
import genimg
import image_providers as ip
from manifest_schema import load_manifest


class Done:
    """Stand-in for subprocess.CompletedProcess."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    """No key sources, no Codex install visible, and the subprocess seam
    fails unless a test installs its own fake."""
    for var in (ip.NO_CODEX_ENV, ip.ART_PY_ENV, ip.ALLOW_PAID_ENV, "OPENROUTER_API_KEY", "IMAGE_API"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(ip, "CONFIG_PATH", tmp_path / "cfg" / "image_api.json")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    real_which = shutil.which
    monkeypatch.setattr(ip.shutil, "which",
                        lambda name, *a, **k: None if name == "codex" else real_which(name, *a, **k))

    def _guard(argv, **kwargs):
        raise AssertionError(f"unexpected subprocess: {argv}")

    monkeypatch.setattr(ip, "_run", _guard)
    ip._codex_login_cache.clear()
    yield
    ip._codex_login_cache.clear()


def _install_codex(tmp_path: Path, version: str = "1.0.0", age_s: float = 0.0) -> str:
    exe = tmp_path / "localappdata" / "OpenAI" / "Codex" / "bin" / version / "codex.exe"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"not a real codex")
    t = 1_700_000_000 - age_s
    os.utime(exe, (t, t))
    return str(exe)


def _login(monkeypatch, text: str = "Logged in using ChatGPT", rc: int = 0) -> list:
    calls: list = []

    def _fake(argv, **kwargs):
        calls.append(list(argv))
        assert argv[1:] == ["login", "status"], argv
        return Done(rc, text + "\n")

    monkeypatch.setattr(ip, "_run", _fake)
    return calls


# ---------------------------------------------------------------- discovery

def test_find_codex_cli_takes_the_newest_localappdata_install(tmp_path):
    _install_codex(tmp_path, "0.9.0", age_s=3600)
    newest = _install_codex(tmp_path, "1.2.0", age_s=0)
    assert ip.find_codex_cli() == newest


def test_find_codex_cli_falls_back_to_path(monkeypatch):
    monkeypatch.setattr(ip.shutil, "which", lambda name, *a, **k: "/usr/local/bin/codex")
    assert ip.find_codex_cli() == "/usr/local/bin/codex"


def test_find_codex_cli_none_when_not_installed():
    assert ip.find_codex_cli() is None


# ---------------------------------------------------------------- login

def test_login_status_chatgpt_is_ok(tmp_path, monkeypatch):
    exe = _install_codex(tmp_path)
    calls = _login(monkeypatch)
    assert ip.codex_login_status(exe) == (True, "Logged in using ChatGPT")
    assert calls == [[exe, "login", "status"]]


@pytest.mark.parametrize("text,rc", [
    ("Not logged in", 0),
    ("Not logged in. Run `codex login` to sign in with ChatGPT", 0),
    ("Logged in using ChatGPT", 1),
    ("Logged in using an API key - sk-proj-***", 0),
])
def test_login_status_rejects_everything_but_a_chatgpt_login(tmp_path, monkeypatch, text, rc):
    exe = _install_codex(tmp_path)
    _login(monkeypatch, text, rc)
    ok, first = ip.codex_login_status(exe)
    assert ok is False
    assert first == text


def test_login_status_survives_a_broken_binary(tmp_path, monkeypatch):
    exe = _install_codex(tmp_path)

    def _boom(argv, **kwargs):
        raise OSError("not a valid Win32 application")

    monkeypatch.setattr(ip, "_run", _boom)
    ok, info = ip.codex_login_status(exe)
    assert ok is False and "Win32" in info


def test_login_status_is_checked_once_per_process(tmp_path, monkeypatch):
    exe = _install_codex(tmp_path)
    calls = _login(monkeypatch)
    ip.codex_login_status(exe)
    ip.codex_login_status(exe)
    assert len(calls) == 1
    ip.codex_login_status(exe, use_cache=False)
    assert len(calls) == 2


# ---------------------------------------------------------------- chain

def test_detect_codex_logged_in(tmp_path, monkeypatch):
    exe = _install_codex(tmp_path)
    _login(monkeypatch)
    assert ip.detect_codex() == ip.ProviderConfig(provider="codex", cli=exe)


def test_detect_codex_not_installed_runs_nothing():
    assert ip.detect_codex() is None          # the autouse guard would fail on any subprocess


def test_no_codex_env_skips_detection_entirely(tmp_path, monkeypatch):
    _install_codex(tmp_path)
    monkeypatch.setenv(ip.NO_CODEX_ENV, "1")
    assert ip.detect_codex() is None          # no login check either (guard)


def test_resolve_prefers_codex_over_every_key(tmp_path, monkeypatch):
    exe = _install_codex(tmp_path)
    _login(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-key")
    monkeypatch.setenv("IMAGE_API", "sk-openai")
    cfg = ip.resolve_provider()
    assert cfg.provider == "codex" and cfg.cli == exe and cfg.key is None


def test_resolve_falls_back_to_the_key_chain_when_logged_out(tmp_path, monkeypatch):
    _install_codex(tmp_path)
    _login(monkeypatch, "Not logged in")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-key")
    with pytest.raises(ip.PaidProviderNotAllowed):            # never silently: the paid key needs the opt-in
        ip.resolve_provider()
    monkeypatch.setenv(ip.ALLOW_PAID_ENV, "1")
    assert ip.resolve_provider().provider == "openrouter"


def test_resolve_none_without_codex_or_keys():
    assert ip.resolve_provider() is None


def test_no_codex_env_lets_a_key_win(tmp_path, monkeypatch):
    _install_codex(tmp_path)
    monkeypatch.setenv(ip.NO_CODEX_ENV, "1")
    monkeypatch.setenv("IMAGE_API", "xai-abc")
    monkeypatch.setenv(ip.ALLOW_PAID_ENV, "1")
    assert ip.resolve_provider().provider == "xai"


# ---------------------------------------------------------------- provider object

def test_get_provider_codex_validate(tmp_path, monkeypatch):
    exe = _install_codex(tmp_path)
    prov = ip.get_provider(ip.ProviderConfig(provider="codex", cli=exe))
    assert isinstance(prov, ip.CodexProvider)
    _login(monkeypatch)
    prov.validate()
    _login(monkeypatch, "Not logged in")
    with pytest.raises(ip.ProviderValidationError, match="codex login"):
        prov.validate()


def test_codex_validate_without_cli_raises():
    with pytest.raises(ip.ProviderValidationError, match="not found"):
        ip.validate(ip.ProviderConfig(provider="codex"))


def test_save_provider_never_stores_a_cli_path(tmp_path):
    ip.save_provider("sk-or-abc")
    assert "cli" not in json.loads(ip.CONFIG_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- art.py delegation

def test_find_art_py_is_the_art_director_script():
    art = ip.find_art_py()
    assert art.is_file()
    assert art.as_posix().endswith("skills/cube_art-director/scripts/art.py")


def test_find_art_py_env_override(tmp_path, monkeypatch):
    fake = tmp_path / "art.py"
    fake.write_text("# fake", encoding="utf-8")
    monkeypatch.setenv(ip.ART_PY_ENV, str(fake))
    assert ip.find_art_py() == fake
    monkeypatch.setenv(ip.ART_PY_ENV, str(tmp_path / "missing.py"))
    with pytest.raises(ip.ImageGenError):
        ip.find_art_py()


def _record_art(monkeypatch, rcs: dict | None = None) -> list:
    """Fake art.py runs: record argv, return the rc given per command."""
    calls: list = []

    def _fake(argv, **kwargs):
        argv = [str(a) for a in argv]
        assert argv[0] == sys.executable and argv[1].endswith("art.py"), argv
        calls.append(argv[2:])
        return Done((rcs or {}).get(argv[2], 0))

    monkeypatch.setattr(ip, "_run", _fake)
    return calls


def test_codex_generate_runs_gen_then_process(tmp_path, monkeypatch):
    calls = _record_art(monkeypatch)
    m, ws = tmp_path / "plans" / "demo_assets.json", tmp_path / "assets_demo"
    ip.codex_generate(m, ws, only=["hero_00", "hero_01"], force=True, jobs=2)
    assert calls == [
        ["gen", str(m), "--workspace", str(ws), "--only", "hero_00,hero_01", "--force", "--jobs", "2"],
        ["process", str(m), "--workspace", str(ws), "--only", "hero_00,hero_01"],
    ]


def test_codex_generate_whole_manifest_by_default(tmp_path, monkeypatch):
    calls = _record_art(monkeypatch)
    ip.codex_generate(tmp_path / "m.json", tmp_path / "ws")
    assert [c[0] for c in calls] == ["gen", "process"]
    assert all("--only" not in c and "--force" not in c for c in calls)


def test_codex_generate_failure_still_processes_the_rest(tmp_path, monkeypatch):
    calls = _record_art(monkeypatch, {"gen": 1})
    with pytest.raises(ip.ImageGenError, match="gen"):
        ip.codex_generate(tmp_path / "m.json", tmp_path / "ws")
    assert [c[0] for c in calls] == ["gen", "process"]


def test_codex_draw_builds_a_one_asset_spec_and_returns_the_final(tmp_path, monkeypatch):
    ref = tmp_path / "ref.png"
    Image.new("RGBA", (4, 4), (1, 2, 3, 255)).save(ref)
    seen: dict = {}

    def _fake(argv, **kwargs):
        cmd, spec = str(argv[2]), Path(argv[3])
        root = spec.parent
        data = json.loads(spec.read_text(encoding="utf-8"))
        seen.setdefault("spec", data)
        seen.setdefault("root", root)
        if cmd == "gen":
            (root / "ws" / "raw").mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (1024, 1024), (255, 0, 255)).save(root / "ws" / "raw" / "image.png")
        elif cmd == "process":
            (root / "ws" / "final").mkdir(parents=True, exist_ok=True)
            Image.new("RGBA", (40, 30), (10, 20, 30, 255)).save(root / "ws" / "final" / "image.png")
        return Done(0)

    monkeypatch.setattr(ip, "_run", _fake)
    img = ip.codex_draw("a red apple", size=(40, 30), reference=ref, background="key")
    assert img.size == (40, 30)
    asset = seen["spec"]["assets"][0]
    assert asset["name"] == "image" and asset["size"] == [40, 30]
    assert asset["background"] == "key" and asset["prompt"] == "a red apple"
    assert Path(asset["subject_ref"]) == ref.resolve()
    assert not seen["root"].exists()            # the throw-away project is removed


def test_codex_draw_reports_a_failed_gen(monkeypatch):
    _record_art(monkeypatch, {"gen": 1})
    with pytest.raises(ip.ImageGenError, match="no image"):
        ip.codex_draw("anything")


def test_genimg_codex_skips_its_own_cutout_and_resize(tmp_path, monkeypatch):
    """art.py already keyed and fitted the image: genimg must save it as is
    (its corner flood fill would eat dark outline pixels next to the
    transparent border)."""
    drawn = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    for x in range(2, 6):
        drawn.putpixel((x, 2), (5, 5, 5, 255))           # dark outline row
    got: dict = {}

    def _fake_draw(prompt, **kwargs):
        got.update(kwargs, prompt=prompt)
        return drawn

    monkeypatch.setattr(ip, "codex_draw", _fake_draw)
    out = genimg.generate_image("a coin", tmp_path / "o" / "coin.png", size=(8, 8), cutout=True,
                                provider=ip.ProviderConfig(provider="codex"))
    assert got["background"] == "key" and got["size"] == (8, 8)
    assert Image.open(out).convert("RGBA").tobytes() == drawn.tobytes()


# ---------------------------------------------------------------- gen_sprites helpers

def _manifest(tmp_path, sprites, extra=None) -> Path:
    data = {"game": "demo", "schema_version": 1, "sprites": sprites, "sounds": []}
    data.update(extra or {})
    p = tmp_path / "plans" / "demo_assets.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _sprite(name, **kw):
    s = {"name": name, "size": [32, 32], "description": name, "gen_prompt": f"draw {name}"}
    s.update(kw)
    return s


def test_seed_fixes_points_later_frames_at_the_first(tmp_path):
    mp = _manifest(tmp_path, [
        _sprite("hero_walk_01", group="hero", anim="hero_walk", frame=1),
        _sprite("hero_walk_00", group="hero", anim="hero_walk", frame=0),
        _sprite("hero_walk_02", group="hero", anim="hero_walk", frame=2),
        _sprite("coin"),
    ])
    ws = tmp_path / "assets_demo"
    assert gen_sprites.seed_fixes(load_manifest(mp), ws) == ["hero_walk_01", "hero_walk_02"]
    fixes = json.loads((ws / "fixes.json").read_text(encoding="utf-8"))
    assert fixes == {"hero_walk_01": {"text": "", "ref": "hero_walk_00"},
                     "hero_walk_02": {"text": "", "ref": "hero_walk_00"}}
    assert gen_sprites.seed_fixes(load_manifest(mp), ws) == []        # rerun: no-op


def test_seed_fixes_merges_into_the_reviewers_file(tmp_path):
    """The reviewer may write fixes.json before the first run: the seed keeps
    every existing entry, turns a text-only entry into text + ref, and never
    touches an entry that already names a ref (null = deliberately none)."""
    mp = _manifest(tmp_path, [_sprite(f"a_0{i}", anim="a", frame=i) for i in range(4)] + [_sprite("fx")])
    ws = tmp_path / "assets_demo"
    ws.mkdir()
    before = {"@colour_lock": ["a_"], "fx": "only the effect, no characters",
              "a_01": "keep the hat", "a_02": {"text": "", "ref": None},
              "a_03": {"text": "x", "ref": "fx"}}
    (ws / "fixes.json").write_text(json.dumps(before), encoding="utf-8")
    assert gen_sprites.seed_fixes(load_manifest(mp), ws) == ["a_01"]
    after = json.loads((ws / "fixes.json").read_text(encoding="utf-8"))
    assert after == {**before, "a_01": {"text": "keep the hat", "ref": "a_00"}}


def test_seed_fixes_respects_a_legacy_override_file(tmp_path):
    mp = _manifest(tmp_path, [_sprite("a_00", anim="a", frame=0), _sprite("a_01", anim="a", frame=1)])
    ws = tmp_path / "assets_demo"
    ws.mkdir()
    (ws / "prompt_overrides.json").write_text("{}", encoding="utf-8")
    assert gen_sprites.seed_fixes(load_manifest(mp), ws) == []
    assert not (ws / "fixes.json").exists()


def test_seed_fixes_reports_broken_json(tmp_path):
    mp = _manifest(tmp_path, [_sprite("a_00", anim="a", frame=0), _sprite("a_01", anim="a", frame=1)])
    ws = tmp_path / "assets_demo"
    ws.mkdir()
    (ws / "fixes.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        gen_sprites.seed_fixes(load_manifest(mp), ws)


def test_generate_codex_maps_a_group_to_only(tmp_path, monkeypatch):
    mp = _manifest(tmp_path, [_sprite("hero_00", group="hero"), _sprite("hero_01", group="hero"),
                              _sprite("coin", group="pickup")])
    ws = tmp_path / "assets_demo"
    seen: dict = {}

    def _fake(manifest_path, workspace, *, only=None, force=False, jobs=None):
        seen.update(manifest_path=manifest_path, workspace=workspace, only=only, force=force, jobs=jobs)
        (Path(workspace) / "art").mkdir(parents=True, exist_ok=True)
        for n in only:
            Image.new("RGBA", (32, 32)).save(Path(workspace) / "art" / f"{n}.png")

    monkeypatch.setattr(ip, "codex_generate", _fake)
    out = gen_sprites.generate_codex(mp, ws, group="hero", force=True, jobs=4)
    assert seen == {"manifest_path": mp, "workspace": ws, "only": ["hero_00", "hero_01"],
                    "force": True, "jobs": 4}
    assert out == [ws / "art" / "hero_00.png", ws / "art" / "hero_01.png"]
    assert gen_sprites.generate_codex(mp, ws, group="nope") == []


def test_is_cutout_follows_the_background_field(tmp_path):
    m = load_manifest(_manifest(tmp_path, [
        _sprite("hero"),                                              # palette default -> cut-out
        _sprite("floor", flags={"bg": True}),                         # legacy bg -> picture
        _sprite("photo", color="full", flags={"alpha": False}),       # full colour -> picture
        _sprite("logo", flags={"bg": True}, background="key"),        # explicit wins
        _sprite("strip", background="opaque"),
    ]))
    assert {s.name: gen_sprites.is_cutout(s) for s in m.sprites} == {
        "hero": True, "floor": False, "photo": False, "logo": True, "strip": False}


def test_api_prompt_adds_the_style_and_a_backdrop_once(tmp_path):
    style = "Style: chunky pixel art, dark outlines."
    m = load_manifest(_manifest(tmp_path, [
        _sprite("hero", gen_prompt="a knight in a pink cape"),
        _sprite("floor", background="opaque", gen_prompt="stone floor tiles"),
        _sprite("old", gen_prompt=f"{style} Subject: a coin on a flat #FF00FF background"),
    ]))
    hero, floor, old = m.sprites
    p = gen_sprites.api_prompt(hero, style)
    assert p.startswith(style) and "#00FF00" in p          # pink subject -> green key
    assert "#FF00FF" not in gen_sprites.api_prompt(floor, style)
    assert "background" not in gen_sprites.api_prompt(floor, style)
    p_old = gen_sprites.api_prompt(old, style)
    assert p_old.count(style) == 1 and p_old.count("#FF00FF") == 1


def test_manifest_style_reads_the_top_level_string(tmp_path):
    mp = _manifest(tmp_path, [_sprite("a")], {"_style": "  Style: flat vector.  "})
    assert gen_sprites.manifest_style(mp) == "Style: flat vector."
    assert gen_sprites.manifest_style(tmp_path / "missing.json") is None


def test_default_workspace_sits_next_to_plans(tmp_path):
    mp = _manifest(tmp_path, [_sprite("a")])
    assert gen_sprites.default_workspace(mp, "demo") == (tmp_path / "assets_demo").resolve()
