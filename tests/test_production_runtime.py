import pytest
from cryptography.fernet import Fernet
from scripts.check_production_runtime import validate_environment

def environment():
    return dict(APP_ENV='production',QB_SCHEMA_MANAGED='1',SECURITY_HARDENING='1',REQUIRE_STAFF_MFA='1',DB_POOL_ENABLED='1',DB_POOL_SIZE='5',DATABASE_URL='postgresql+psycopg://runtime:dummy@/exam?host=/cloudsql/project:region:db',EXPECTED_DB_NAME='exam',EXPECTED_DB_USER='runtime',EXPECTED_CLOUDSQL_CONNECTION='project:region:db',GCS_DATA_BUCKET='exam-data',EXPECTED_DATA_BUCKET='exam-data',GOOGLE_CLIENT_ID='test-client',MFA_ENCRYPTION_KEY=Fernet.generate_key().decode(),APP_BASE_URL='https://example.test')

def test_valid_production_configuration():validate_environment(environment())

@pytest.mark.parametrize('key,value',[('QB_SCHEMA_MANAGED','0'),('EXPECTED_DB_USER','other'),('EXPECTED_CLOUDSQL_CONNECTION','another:region:db'),('EXPECTED_DATA_BUCKET','other'),('APP_BASE_URL','http://example.test'),('APP_BASE_URL','https://example.test/app'),('DB_POOL_SIZE','100')])
def test_unsafe_configuration_rejected(key,value):
    env=environment();env[key]=value
    with pytest.raises(RuntimeError):validate_environment(env)
