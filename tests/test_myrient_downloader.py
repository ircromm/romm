from rommanager.models import ROMInfo
from rommanager.myrient_downloader import DownloadProgress, DownloadTask, MyrientDownloader


class _HeadOkSession:
    class Resp:
        status_code = 200

    def __init__(self):
        self.calls = 0

    def head(self, *args, **kwargs):
        self.calls += 1
        return self.Resp()


def _new_downloader(session):
    dl = MyrientDownloader.__new__(MyrientDownloader)
    dl.session = session
    dl.timeout = (10, 90)
    dl._cancel_flag = False
    dl._pause_flag = False
    dl._url_cache = {}
    dl.download_backend = 'auto'
    return dl


def test_find_rom_url_skips_head_by_default_and_uses_cache():
    dl = _new_downloader(_HeadOkSession())
    dl.find_system_url = lambda _name: 'https://example.com/system/'

    rom = ROMInfo('Game Name (USA)', 'abcd1234', 123, 'Game Name', 'System', 'USA', 'missing', 'dat')

    url_1 = dl.find_rom_url(rom)
    url_2 = dl.find_rom_url(rom)

    assert url_1 == 'https://example.com/system/Game%20Name%20%28USA%29.zip'
    assert url_2 == url_1
    assert dl.session.calls == 0


def test_find_rom_url_validate_true_performs_head_once_with_cache():
    session = _HeadOkSession()
    dl = _new_downloader(session)
    dl.find_system_url = lambda _name: 'https://example.com/system/'

    rom = ROMInfo('Another.zip', 'abcd1234', 123, 'Another', 'System', 'USA', 'missing', 'dat')

    assert dl.find_rom_url(rom, validate=True) == 'https://example.com/system/Another.zip'
    assert dl.find_rom_url(rom, validate=True) == 'https://example.com/system/Another.zip'
    assert session.calls == 1


def test_download_file_opens_url_in_browser(monkeypatch):
    dl = _new_downloader(_HeadOkSession())
    dl.download_backend = 'browser'
    task = DownloadTask(rom_name='game', url='https://example.com/game.zip', dest_path='unused/game.zip')
    progress = DownloadProgress(total_count=1)

    opened = []

    def fake_open(url, new=0):
        opened.append((url, new))
        return True

    monkeypatch.setattr('rommanager.myrient_downloader.webbrowser.open', fake_open)

    dl._download_file(task, progress, callback=None)

    assert opened == [('https://example.com/game.zip', 2)]
    assert task.downloaded_bytes == 1
    assert task.total_bytes == 1


def test_download_file_auto_falls_back_to_browser(monkeypatch):
    dl = _new_downloader(_HeadOkSession())
    dl.download_backend = 'auto'
    task = DownloadTask(rom_name='game', url='https://example.com/game.zip', dest_path='unused/game.zip')
    progress = DownloadProgress(total_count=1)

    def fail_requests(*_args, **_kwargs):
        raise RuntimeError('requests failed')

    def fail_curl(*_args, **_kwargs):
        raise RuntimeError('curl failed')

    opened = []

    def fake_open(url, new=0):
        opened.append((url, new))
        return True

    monkeypatch.setattr(dl, '_download_file_requests', fail_requests)
    monkeypatch.setattr(dl, '_download_file_curl', fail_curl)
    monkeypatch.setattr('rommanager.myrient_downloader.webbrowser.open', fake_open)

    dl._download_file(task, progress, callback=None)

    assert opened == [('https://example.com/game.zip', 2)]


def test_queue_delay_schedule():
    assert MyrientDownloader._queue_delay_seconds(0) == 0
    assert MyrientDownloader._queue_delay_seconds(1) == 15
    assert MyrientDownloader._queue_delay_seconds(2) == 30
    assert MyrientDownloader._queue_delay_seconds(3) == 60
    assert MyrientDownloader._queue_delay_seconds(4) == 120
    assert MyrientDownloader._queue_delay_seconds(10) == 120


def test_directory_url_returns_parent_folder():
    assert (
        MyrientDownloader.directory_url(
            'https://myrient.erista.me/files/Redump/Sega%20-%20Dreamcast/Game.zip'
        )
        == 'https://myrient.erista.me/files/Redump/Sega%20-%20Dreamcast/'
    )


def test_get_myrient_page_for_rom_returns_game_specific_url():
    dl = _new_downloader(_HeadOkSession())
    dl.find_rom_url = lambda rom, validate=False: (
        'https://myrient.erista.me/files/Redump/Sega%20-%20Dreamcast/Skies%20of%20Arcadia%20%28USA%29%20%28Disc%201%29.zip'
    )
    rom = ROMInfo(name='Skies of Arcadia (USA)', size=0, crc32='', system_name='Sega - Dreamcast')

    assert dl.get_myrient_page_for_rom(rom) == (
        'https://myrient.erista.me/files/Redump/Sega%20-%20Dreamcast/Skies%20of%20Arcadia%20%28USA%29%20%28Disc%201%29.zip'
    )


def test_get_myrient_page_for_rom_falls_back_to_system_page():
    dl = _new_downloader(_HeadOkSession())
    dl.find_rom_url = lambda rom, validate=False: None
    dl.find_system_url = lambda _name: 'https://myrient.erista.me/files/Redump/Sega%20-%20Dreamcast/'
    rom = ROMInfo(name='Skies of Arcadia (USA)', size=0, crc32='', system_name='Sega - Dreamcast')

    assert dl.get_myrient_page_for_rom(rom) == 'https://myrient.erista.me/files/Redump/Sega%20-%20Dreamcast/'
