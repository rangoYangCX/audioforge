from __future__ import annotations

from types import SimpleNamespace

from audioforge.app.services.playback_service import PlaybackService


class _FakeChannel:
    def __init__(self) -> None:
        self.volume = 0.0

    def set_volume(self, value: float) -> None:
        self.volume = value

    def get_busy(self) -> bool:
        return False


class _FakeSound:
    def __init__(self, channel) -> None:
        self.channel = channel
        self.volume = 0.0

    def set_volume(self, value: float) -> None:
        self.volume = value

    def play(self):
        return self.channel


def test_playback_service_reports_mixer_initialization_failure(monkeypatch) -> None:
    service = PlaybackService()
    fake_renderer = SimpleNamespace(
        is_available=lambda: True,
        render_file=lambda *args, **kwargs: SimpleNamespace(audio_data=SimpleNamespace(size=4), sample_rate=48000),
    )
    service._renderer = fake_renderer

    monkeypatch.setattr(
        "audioforge.app.services.playback_service.np",
        SimpleNamespace(ascontiguousarray=lambda value: value, int16="int16"),
    )

    class _FakeArray:
        size = 4

        def __mul__(self, _value):
            return self

        def astype(self, *_args, **_kwargs):
            return self

    fake_renderer.render_file = lambda *args, **kwargs: SimpleNamespace(audio_data=_FakeArray(), sample_rate=48000)

    fake_pygame = SimpleNamespace(
        mixer=SimpleNamespace(init=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("device missing")), quit=lambda: None),
        sndarray=SimpleNamespace(make_sound=lambda value: value),
    )
    monkeypatch.setattr("audioforge.app.services.playback_service.pygame", fake_pygame)

    message = service.play_file("demo.wav", 0.0)

    assert "真实试听不可用" in message
    assert "device missing" in message


def test_playback_service_rejects_missing_channel_after_sound_play(monkeypatch) -> None:
    service = PlaybackService()

    class _FakeArray:
        size = 4

        def __mul__(self, _value):
            return self

        def astype(self, *_args, **_kwargs):
            return self

    service._renderer = SimpleNamespace(
        is_available=lambda: True,
        render_file=lambda *args, **kwargs: SimpleNamespace(audio_data=_FakeArray(), sample_rate=48000),
    )

    monkeypatch.setattr(
        "audioforge.app.services.playback_service.np",
        SimpleNamespace(ascontiguousarray=lambda value: value, int16="int16"),
    )
    fake_pygame = SimpleNamespace(
        mixer=SimpleNamespace(init=lambda **kwargs: None, quit=lambda: None),
        sndarray=SimpleNamespace(make_sound=lambda value: _FakeSound(channel=None)),
    )
    monkeypatch.setattr("audioforge.app.services.playback_service.pygame", fake_pygame)

    message = service.play_file("demo.wav", 0.0)

    assert "未分配到可用播放通道" in message


def test_playback_service_reinitializes_mixer_when_sample_rate_changes(monkeypatch) -> None:
    service = PlaybackService()
    init_calls: list[dict[str, int]] = []

    fake_pygame = SimpleNamespace(
        mixer=SimpleNamespace(
            init=lambda **kwargs: init_calls.append(kwargs),
            quit=lambda: init_calls.append({"quit": 1}),
        ),
        sndarray=SimpleNamespace(make_sound=lambda value: _FakeSound(channel=_FakeChannel())),
    )
    monkeypatch.setattr("audioforge.app.services.playback_service.pygame", fake_pygame)

    service._ensure_initialized(48000)
    service._ensure_initialized(44100)

    assert init_calls[0]["frequency"] == 48000
    assert init_calls[1] == {"quit": 1}
    assert init_calls[2]["frequency"] == 44100