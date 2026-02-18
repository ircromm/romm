import os
import tempfile
import zlib

from rommanager.models import ROMInfo
from rommanager.myrient_downloader import DownloadProgress, DownloadTask, MyrientDownloader


class _FakeResponse:
    def __init__(self, data: bytes, status_code: int = 200):
        self._data = data
        self.status_code = status_code
        self.headers = {'content-length': str(len(data))}

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=65536):
        for i in range(0, len(self._data), chunk_size):
            yield self._data[i:i + chunk_size]


class _FakeSession:
    def __init__(self, response):
        self.response = response
        self.last_headers = None

    def get(self, url, stream=True, timeout=None, headers=None):
        self.last_headers = headers or {}
        return self.response


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


def test_download_file_resumes_from_part_file_using_range():
    payload = b'def'
    session = _FakeSession(_FakeResponse(payload, status_code=206))
    dl = _new_downloader(session)

    with tempfile.TemporaryDirectory() as tmp:
        final_path = os.path.join(tmp, 'game.zip')
        part_path = final_path + '.part'
        with open(part_path, 'wb') as fh:
            fh.write(b'abc')

        task = DownloadTask(rom_name='game', url='https://example.com/game.zip', dest_path=final_path)
        progress = DownloadProgress(total_count=1)

        dl._download_file(task, progress, callback=None)

        assert session.last_headers.get('Range') == 'bytes=3-'
        with open(final_path, 'rb') as fh:
            assert fh.read() == b'abcdef'
        assert not os.path.exists(part_path)
        assert task.downloaded_bytes == 6
        assert task.total_bytes == 6
        expected_crc = f"{zlib.crc32(b'abcdef') & 0xFFFFFFFF:08x}"
        assert task.computed_crc == expected_crc
