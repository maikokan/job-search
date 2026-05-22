from src.scrape import filter_by_reject_words, filter_location


def test_filter_by_reject_words():
    jobs = [
        {"title": "Senior Engineer", "url": "http://a.com"},
        {"title": "Junior Analyst", "url": "http://b.com"},
        {"title": "Lead Manager", "url": "http://c.com"},
        {"title": "Graduate Intern", "url": "http://d.com"},
    ]
    reject_words = ["Senior", "Lead", "Manager"]
    passed, rejected = filter_by_reject_words(jobs, reject_words)

    assert [j["title"] for j in passed] == ["Junior Analyst", "Graduate Intern"]
    assert [j["title"] for j in rejected] == ["Senior Engineer", "Lead Manager"]


def test_filter_location_rejects_guangdong():
    jobs = [
        {"title": "Analyst", "location": "Hong Kong"},
        {"title": "Analyst", "location": "Guangdong, China"},
        {"title": "Analyst", "location": "Hong Kong SAR"},
    ]
    passed, rejected = filter_location(jobs)
    assert len(passed) == 2
    assert len(rejected) == 1


def test_filter_by_reject_words_empty_list():
    jobs = [{"title": "Analyst", "url": "http://a.com"}]
    passed, rejected = filter_by_reject_words(jobs, [])
    assert passed == jobs
    assert rejected == []


def test_filter_by_reject_words_case_insensitive():
    jobs = [{"title": "SENIOR ANALYST", "url": "http://a.com"}]
    passed, rejected = filter_by_reject_words(jobs, ["senior"])
    assert len(passed) == 0
    assert len(rejected) == 1


def test_filter_location_empty():
    jobs = [{"title": "Analyst", "location": "Hong Kong"}]
    passed, rejected = filter_location(jobs)
    assert passed == jobs
    assert rejected == []


def test_filter_location_all_rejected():
    jobs = [
        {"title": "Analyst", "location": "Guangdong"},
        {"title": "Analyst", "location": "Guangdong, China"},
    ]
    passed, rejected = filter_location(jobs)
    assert passed == []
    assert len(rejected) == 2
