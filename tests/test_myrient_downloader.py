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


def test_queue_delay_schedule():
    assert MyrientDownloader._queue_delay_seconds(0) == 0
    assert MyrientDownloader._queue_delay_seconds(1) == 15
    assert MyrientDownloader._queue_delay_seconds(2) == 30
    assert MyrientDownloader._queue_delay_seconds(3) == 60
    assert MyrientDownloader._queue_delay_seconds(4) == 120
    assert MyrientDownloader._queue_delay_seconds(10) == 120
