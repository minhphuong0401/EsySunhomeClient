import asyncio
from pybyd import BydClient, BydConfig


async def main() -> None:
    config = BydConfig.from_env()

    async with BydClient(config) as client:
        vehicles = await client.get_vehicles()
        vin = vehicles[0].vin

        realtime = await client.get_vehicle_realtime(vin)

        print(f"VIN: {vin}")
        print(f"Battery: {realtime.elec_percent}%")
        print(realtime)

asyncio.run(main())
