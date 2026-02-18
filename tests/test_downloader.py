from rommanager.downloader import ArchiveOrgDownloader
from rommanager.models import ROMInfo


def test_batch_search_strips_parenthetical_text_from_term():
    downloader = ArchiveOrgDownloader.__new__(ArchiveOrgDownloader)

    calls = []

    def fake_search(term, system_name, max_results=10):
        calls.append((term, system_name, max_results))
        return [{"identifier": "stub"}]

    downloader.search = fake_search

    rom = ROMInfo(
        name="Super Mario Bros. (USA)",
        crc32="1234ABCD",
        size=40976,
        game_name="Super Mario Bros. (Rev A)",
        system_name="NES",
        region="USA",
        status="missing",
        dat_id="no-intro",
    )

    results = downloader.batch_search([rom])

    assert calls == [("Super Mario Bros.", "NES", 5)]
    assert results == {"Super Mario Bros. (USA)": [{"identifier": "stub"}]}
