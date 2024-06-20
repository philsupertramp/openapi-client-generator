from data_sink_api_client.async_client import AsyncDatasinkAPIClient
from data_sink_api_client.client import models
import asyncio


async def test_read_root():
    client = AsyncDatasinkAPIClient('https://datasink.dev.easybits.tech', 'c2VydmljZXNAZWFzeWJpdHMudGVjaDo5dmVOSGFTSyFIbGJIOW1B')

    response = await client.read_root()
    #assert response == models.ReadRootResponse(), response
    print(response)


async def test_health_check():
    client = AsyncDatasinkAPIClient('https://datasink.dev.easybits.tech', 'c2VydmljZXNAZWFzeWJpdHMudGVjaDo5dmVOSGFTSyFIbGJIOW1B')

    response = await client.health_check()
    print(response)
    #assert response == models.HealthCheckResponse()


async def test_get_models():
    client = AsyncDatasinkAPIClient('https://datasink.dev.easybits.tech', 'c2VydmljZXNAZWFzeWJpdHMudGVjaDo5dmVOSGFTSyFIbGJIOW1B')

    response = await client.get_models()
    #assert isinstance(response, list) and all(isinstance(item, models.EmbeddingModel) for item in response)
    print(response)


async def test_query():
    client = AsyncDatasinkAPIClient('https://datasink.dev.easybits.tech', 'c2VydmljZXNAZWFzeWJpdHMudGVjaDo5dmVOSGFTSyFIbGJIOW1B')

    response = await client.query(4, models.QueryRequest(query='Hey there, what is up'))
    #assert isinstance(response, list), response
    print(response)



if __name__ == '__main__':
    asyncio.run(test_read_root())
    asyncio.run(test_health_check())
    asyncio.run(test_get_models())
    asyncio.run(test_query())
