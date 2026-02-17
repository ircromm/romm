import os
import tempfile

from rommanager.monitor import setup_monitoring, log_event, LOGGER_NAME


def test_monitor_writes_event_to_file():
    with tempfile.TemporaryDirectory() as tmp:
        logfile = os.path.join(tmp, 'events.log')

        logger = setup_monitoring(log_file=logfile, echo=False)
        # ensure clean for deterministic assertion
        for h in list(logger.handlers):
            h.flush()

        log_event('test.event', 'monitor alive')

        for h in logger.handlers:
            h.flush()

        with open(logfile, 'r', encoding='utf-8') as f:
            content = f.read()

        assert 'test.event' in content
        assert 'monitor alive' in content


