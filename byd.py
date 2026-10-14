import asyncio
import json
import math
from datetime import datetime, timezone

from pybyd import BydApiError, BydClient, BydConfig


async def main() -> None:
    config = BydConfig.from_env()

    async with BydClient(config) as client:
        vehicles = await client.get_vehicles()
        if not vehicles:
            raise ValueError("No BYD vehicles are associated with this account")
        vin = vehicles[0].vin

        realtime = await client.get_vehicle_realtime(vin)
        consumption = None
        try:
            energy = await client.get_energy_consumption(vin)
            recent = energy.nearest_energy_consumption
            if recent and recent.ev_unit in ("", "kWh/100km"):
                consumption = recent.avg_ev_consumption
        except BydApiError:
            pass
        if consumption is None or not math.isfinite(consumption) or consumption <= 0:
            if realtime.recent_50km_energy_ev_unit in (None, "kWh/100km"):
                consumption = realtime.recent_50km_energy_ev
        if realtime.elec_percent is None or realtime.total_mileage is None:
            raise ValueError("BYD did not report SOC and odometer")
        print(json.dumps({
            "fetchedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "vehicleTime": realtime.timestamp.isoformat() if realtime.timestamp else None,
            "socPercent": realtime.elec_percent,
            "odometerKm": realtime.total_mileage,
            "recent50kmKwhPer100km": consumption,
        }))

if __name__ == "__main__":
    asyncio.run(main())
