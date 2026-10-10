#!/usr/bin/env python3
"""Fetch today's PV generation / load consumption / grid import+export (kWh)
from an ESY Sunhome / BenBen Energy inverter (HM6 and similar models).

Reuses the login + mTLS cert + binary telemetry parsing logic from the
branko-lazarevic/esysunhome Home Assistant integration (vendored under
esy_lib/) without depending on Home Assistant itself.

Usage:
    export ESY_ACCESS_TOKEN="..."
    export ESY_REFRESH_TOKEN="..."
    # Or, when tokens are unavailable:
    export ESY_USERNAME="you@example.com"
    export ESY_PASSWORD="your-password"
    python3 fetch_today.py
"""
import asyncio
import json
import logging
import os
import ssl
import sys
from pathlib import Path

import aiomqtt

from esy_lib.esysunhome import ESYSunhomeAPI
from esy_lib.protocol import DynamicTelemetryParser, ESYCommandBuilder
from esy_lib.protocol_api import get_protocol_api
from esy_lib.const import DEFAULT_PV_POWER, DEFAULT_TP_TYPE, DEFAULT_MCU_VERSION

logging.basicConfig(
    level=logging.DEBUG if os.environ.get("ESY_DEBUG") else logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    stream=sys.stderr,
)

CERT_DIR = Path(__file__).parent / ".certs"
WAIT_SECONDS = 35


def write_token_state(api: ESYSunhomeAPI) -> None:
    output_path = os.environ.get("ESY_TOKEN_OUTPUT_FILE")
    if not output_path:
        return

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    with os.fdopen(file_descriptor, "w", encoding="utf-8") as token_file:
        json.dump(
            {
                "access_token": api.access_token,
                "refresh_token": api.refresh_token,
            },
            token_file,
        )
    path.chmod(0o600)


def build_tls_context(credentials) -> ssl.SSLContext | None:
    if not credentials.use_tls:
        return None

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    if credentials.ca_cert_path and os.path.exists(credentials.ca_cert_path):
        ctx.load_verify_locations(credentials.ca_cert_path)
    if (
        credentials.client_cert_path
        and credentials.client_key_path
        and os.path.exists(credentials.client_cert_path)
        and os.path.exists(credentials.client_key_path)
    ):
        ctx.load_cert_chain(
            certfile=credentials.client_cert_path,
            keyfile=credentials.client_key_path,
        )
    # ESY's broker cert does not fully validate; mirrors the integration's own setup.
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


async def fetch_once() -> dict:
    access_token = os.environ.get("ESY_ACCESS_TOKEN")
    refresh_token = os.environ.get("ESY_REFRESH_TOKEN")
    has_tokens = bool(access_token or refresh_token)
    username = os.environ.get("ESY_USERNAME")
    password = os.environ.get("ESY_PASSWORD")

    if not has_tokens and (not username or not password):
        raise RuntimeError(
            "Set ESY_ACCESS_TOKEN or ESY_REFRESH_TOKEN, or provide both "
            "ESY_USERNAME and ESY_PASSWORD"
        )

    api = ESYSunhomeAPI(username, password, device_id=None)
    api.access_token = access_token
    api.refresh_token = refresh_token

    try:
        await api.get_bearer_token()
        if not api.access_token:
            raise RuntimeError("Authentication succeeded without an access token")
        await api.ensure_device_id()

        device_info = await api.get_device_info()
        device_sn = device_info.get("sn")
        print(f"[debug] device_id={api.device_id} sn={device_sn!r}", file=sys.stderr)
        if not device_sn:
            print(f"[debug] full device_info={device_info}", file=sys.stderr)
            raise RuntimeError("device_info has no 'sn' field - check [debug] output above for the right field name")

        credentials = await api.get_mqtt_credentials(str(CERT_DIR))
        print(
            f"[debug] mqtt broker={credentials.broker_url}:{credentials.port} "
            f"tls={credentials.use_tls} mtls={credentials.client_cert_path is not None} "
            f"username={credentials.username!r}",
            file=sys.stderr,
        )
        for label, path in (
            ("ca", credentials.ca_cert_path),
            ("client_cert", credentials.client_cert_path),
            ("client_key", credentials.client_key_path),
        ):
            if path:
                print(f"[debug] cert {label}: {path} exists={os.path.exists(path)}", file=sys.stderr)

        tls_context = build_tls_context(credentials)

        protocol_api = get_protocol_api(api.access_token)
        protocol = await protocol_api.get_protocol_definition(
            pv_power=device_info.get("pvPower", DEFAULT_PV_POWER),
            tp_type=device_info.get("tpType", DEFAULT_TP_TYPE),
            mcu_version=device_info.get("mcuVersion", DEFAULT_MCU_VERSION),
        )

        parser = DynamicTelemetryParser(protocol)
        parser.set_tp_type(device_info.get("tpType", DEFAULT_TP_TYPE))

        topic_up = f"/ESY/PVVC/{device_sn}/UP"
        topic_down = f"/ESY/PVVC/{device_sn}/DOWN"
        topic_event = f"/ESY/PVVC/{device_sn}/EVENT"
        topic_alarm = f"/ESY/PVVC/{device_sn}/ALARM"

        print(f"[debug] connecting to {credentials.broker_url}:{credentials.port} ...", file=sys.stderr)
        async with aiomqtt.Client(
            hostname=credentials.broker_url,
            port=credentials.port,
            username=credentials.username,
            password=credentials.password,
            tls_context=tls_context,
            keepalive=60,
        ) as client:
            print("[debug] MQTT connected", file=sys.stderr)
            await client.subscribe(topic_up)
            await client.subscribe(topic_event)
            await client.subscribe(topic_alarm)
            print(f"[debug] subscribed: {topic_up}, {topic_event}, {topic_alarm}", file=sys.stderr)

            # Ask the inverter to publish fresh telemetry: send the same
            # poll request the official app sends (segments 0,1,3,6 cover
            # power + daily energy stats), and also hit the REST "obtain"
            # endpoint as a belt-and-suspenders trigger.
            poll_command = ESYCommandBuilder.build_poll_request(
                segment_ids=[0, 1, 3, 6], msg_id=1
            )
            await client.publish(topic_down, poll_command)
            print(f"[debug] published poll request to {topic_down}", file=sys.stderr)
            await api.request_update()
            print("[debug] called REST obtain trigger", file=sys.stderr)

            async for message in client.messages:
                print(
                    f"[debug] got message on topic={message.topic} ({len(message.payload)} bytes): "
                    f"{message.payload[:40]!r}",
                    file=sys.stderr,
                )

                if str(message.topic) != topic_up:
                    continue

                result = parser.parse_message(message.payload)
                if not result:
                    print("[debug] parse_message returned nothing", file=sys.stderr)
                    continue
                print(f"[debug] parsed telemetry: {result}", file=sys.stderr)
                summary = {
                    "photovoltaicPowerGenerationToday_kWh": result.get("dailyPowerGeneration"),
                    "buyElectricityToday_kWh": result.get("dailyGridImport"),
                    "sellingElectricityToday_kWh": result.get("dailyGridExport"),
                    "totalConsumptionToday_kWh": result.get("dailyConsumption"),
                    "batterySoc_percent": result.get("batterySoc"),
                }
                mqtt_current_time = result.get("_mqttCurrentTime")
                if mqtt_current_time is not None:
                    summary["mqttCurrentTime"] = mqtt_current_time
                return summary

        raise RuntimeError("MQTT connection closed before any telemetry arrived")

    finally:
        try:
            write_token_state(api)
        finally:
            await api.close_session()


async def main() -> None:
    try:
        summary = await asyncio.wait_for(fetch_once(), timeout=WAIT_SECONDS)
    except asyncio.TimeoutError:
        print(
            f"Timed out after {WAIT_SECONDS}s waiting for telemetry from the inverter.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
