import pytest

from tests.conftest import ANY_DB_OVERRIDE, check_test_db_url


@pytest.mark.parametrize("url", ["postgresql://u:p@h:5432/ambulance_test", "postgresql://h/test", "postgres://h/TestDB"])
def test_test_database_names_pass(url):
    check_test_db_url(url, env={})


@pytest.mark.parametrize("url", ["postgresql://u:p@h:5432/ambulance", "postgresql://h/postgres", "postgresql://h/"])
def test_other_databases_are_refused(url):
    with pytest.raises(pytest.UsageError):
        check_test_db_url(url, env={})
    check_test_db_url(url, env={ANY_DB_OVERRIDE: "1"})  # explicit override
