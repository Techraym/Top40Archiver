from app.service_queue import MAX_DOWNLOAD_WORKERS, _download_worker_count


def test_download_worker_default_is_one_without_setting():
    assert _download_worker_count({}) == 1


def test_two_workers_are_supported():
    assert _download_worker_count({"download_workers": "2"}) == 2


def test_worker_count_is_bounded():
    assert _download_worker_count({"download_workers": "0"}) == 1
    assert _download_worker_count({"download_workers": "999"}) == MAX_DOWNLOAD_WORKERS


def test_invalid_worker_count_falls_back_safely():
    assert _download_worker_count({"download_workers": "geen-getal"}) == 1
