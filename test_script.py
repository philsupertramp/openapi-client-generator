from client.client import DatasinkAPIClient
from client import models


def test_read_root():
    client = DatasinkAPIClient('https://datasink.dev.easybits.tech', 'c2VydmljZXNAZWFzeWJpdHMudGVjaDo5dmVOSGFTSyFIbGJIOW1B')

    response = client.read_root()
    assert response == models.ReadRootResponse()


def test_health_check():
    client = DatasinkAPIClient('https://datasink.dev.easybits.tech', 'c2VydmljZXNAZWFzeWJpdHMudGVjaDo5dmVOSGFTSyFIbGJIOW1B')

    response = client.health_check()
    assert response == models.HealthCheckResponse()


def test_get_models():
    client = DatasinkAPIClient('https://datasink.dev.easybits.tech', 'c2VydmljZXNAZWFzeWJpdHMudGVjaDo5dmVOSGFTSyFIbGJIOW1B')

    response = client.get_models()
    assert isinstance(response, list) and all(isinstance(item, models.EmbeddingModel) for item in response)
    print(response)


def test_query():
    client = DatasinkAPIClient('https://datasink.dev.easybits.tech', 'c2VydmljZXNAZWFzeWJpdHMudGVjaDo5dmVOSGFTSyFIbGJIOW1B')

    response = client.query(4, models.QueryRequest(query='Hey there, what is up'))
    assert isinstance(response, list), response


test_read_root()
test_health_check()
test_get_models()
test_query()
