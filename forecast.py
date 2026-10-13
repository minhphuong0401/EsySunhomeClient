import json
import urllib.request
import pandas as pd
import pvlib

# --- 1. Cấu hình thông số hệ thống của bạn ---
LAT = -33.94003
LON = 151.110707
PEAK_POWER_KW = 10.0  # Công suất đỉnh 10 kWp
SYSTEM_LOSS = 0.15  # Tổn thất hệ thống (15%)

TILT = 22
AZIMUTH = 248
TZ = "Australia/Sydney"
url = (
    "https://api.open-meteo.com/v1/forecast"
    f"?latitude={LAT}&longitude={LON}"
    "&hourly=temperature_2m,wind_speed_10m,shortwave_radiation,"
    "direct_normal_irradiance,diffuse_radiation"
    "&forecast_days=3&timezone=UTC&wind_speed_unit=ms"
)
with urllib.request.urlopen(url, timeout=30) as resp:
    raw = json.load(resp)

df = pd.DataFrame(raw["hourly"])
df["time"] = pd.to_datetime(df["time"])
df = df.set_index("time").tz_localize("UTC")
df = df.rename(columns={
    "temperature_2m": "temp_air",
    "wind_speed_10m": "wind_speed",
    "shortwave_radiation": "ghi",
    "direct_normal_irradiance": "dni",
    "diffuse_radiation": "dhi",
})

# Open-Meteo trả giá trị trung bình của GIỜ TRƯỚC đó -> dịch lùi 30 phút
# để tính vị trí mặt trời ở giữa khoảng thời gian cho chuẩn
df.index = df.index - pd.Timedelta(minutes=30)

# --- 3. Vị trí mặt trời + bức xạ trên mặt phẳng tấm pin (POA) ---
solpos = pvlib.solarposition.get_solarposition(df.index, LAT, LON)
dni_extra = pvlib.irradiance.get_extra_radiation(df.index)

poa = pvlib.irradiance.get_total_irradiance(
    surface_tilt=TILT,
    surface_azimuth=AZIMUTH,  # pvlib: 0=Bắc, 90=Đông, 180=Nam
    solar_zenith=solpos["apparent_zenith"],
    solar_azimuth=solpos["azimuth"],
    dni=df["dni"],
    ghi=df["ghi"],
    dhi=df["dhi"],
    dni_extra=dni_extra,
    model="haydavies",
)

# --- 4. Nhiệt độ cell + công suất DC/AC ---
temp_params = pvlib.temperature.TEMPERATURE_MODEL_PARAMETERS["sapm"]["open_rack_glass_glass"]
temp_cell = pvlib.temperature.sapm_cell(
    poa["poa_global"], df["temp_air"], df["wind_speed"], **temp_params
)

pdc = pvlib.pvsystem.pvwatts_dc(
    poa["poa_global"],   # bức xạ hiệu dụng trên mặt tấm
    temp_cell,
    PEAK_POWER_KW * 1000,  # pdc0
    -0.004,                # gamma_pdc
)
power_w = (pdc * (1 - SYSTEM_LOSS)).clip(lower=0, upper=PEAK_POWER_KW * 1000)

# --- 5. Kết quả ---
forecast = pd.DataFrame({
    "poa_W_m2": poa["poa_global"].round(0),
    "temp_air_C": df["temp_air"],
    "power_kW": (power_w / 1000).round(2),
}).tz_convert(TZ)

# Mỗi dòng = 1 giờ => kW x 1h = kWh
daily_kwh = forecast["power_kW"].resample("D").sum().round(1)

print("=== Công suất theo giờ (ban ngày) ===")
print(forecast[forecast["power_kW"] > 0])
print("\n=== Sản lượng dự báo theo ngày (kWh) ===")
print(daily_kwh)
print(f"\nTổng 3 ngày: {daily_kwh.sum():.1f} kWh")