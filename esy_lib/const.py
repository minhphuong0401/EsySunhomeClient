"""Constants used by the ESY Sunhome API and protocol client."""

ESY_API_BASE_URL = "http://esybackend.esysunhome.com:7073"
ESY_API_LOGIN_ENDPOINT = "/login?grant_type=app"
ESY_API_DEVICE_ENDPOINT = "/api/lsydevice/page?current=1&size=10"
ESY_API_OBTAIN_ENDPOINT = "/api/param/set/obtain?val=3&deviceId="
ESY_API_MODE_ENDPOINT = "/api/lsypattern/switch"
ESY_API_SOCSCHEDULES_QUERY_ENDPOINT = "/api/lsydevicechargedischarge/info?deviceId="
ESY_API_SOCSCHEDULES_SAVE_ENDPOINT = "/api/lsydevicechargedischarge/save"
ESY_API_PROTOCOL_LIST = "/sys/protocol/list"
ESY_API_PROTOCOL_SEGMENT = "/sys/protocol/segment"
ESY_API_DEVICE_INFO = "/api/lsydevice/info"
ESY_API_CERT_ENDPOINT = "/security/cert/android"

ESY_MQTT_BROKER_URL = "abroadtcp.esysunhome.com"
ESY_MQTT_BROKER_PORT = 8883

DEFAULT_PV_POWER = 6
DEFAULT_TP_TYPE = 1
DEFAULT_MCU_VERSION = 1049

DATA_TYPE_UNSIGNED = "unsigned"
DATA_TYPE_SIGNED = "signed"

FC_READ_HOLDING = 3
FC_READ_INPUT = 4
