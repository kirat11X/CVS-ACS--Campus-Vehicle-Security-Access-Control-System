import time
import json
import logging
import threading
from typing import Optional, Callable
import paho.mqtt.client as mqtt
from backend.app.config import MQTT_BROKER_HOST, MQTT_BROKER_PORT, MQTT_TOPIC_PREFIX

logger = logging.getLogger(__name__)

class MQTTManager:
    def __init__(self, host: str = MQTT_BROKER_HOST, port: int = MQTT_BROKER_PORT):
        self.host = host
        self.port = port
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.connected = False
        self.last_events = []
        self.on_event_callback: Optional[Callable] = None

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            self.connected = True
            logger.info(f"Connected to MQTT broker at {self.host}:{self.port}")
            client.subscribe(f"{MQTT_TOPIC_PREFIX}/#")
            client.subscribe("health/ping")
        else:
            self.connected = False
            logger.error(f"Failed to connect to MQTT broker, rc={rc}")

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties=None):
        self.connected = False
        logger.warning(f"Disconnected from MQTT broker: {reason_code}")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        try:
            payload = msg.payload.decode("utf-8")
            data = json.loads(payload)
        except Exception:
            data = msg.payload.decode("utf-8", errors="replace")

        event = {"topic": topic, "data": data, "timestamp": time.time()}
        self.last_events.append(event)
        if len(self.last_events) > 50:
            self.last_events.pop(0)

        if self.on_event_callback:
            self.on_event_callback(topic, data)

    def start(self):
        try:
            self.client.connect(self.host, self.port, keepalive=60)
            self.client.loop_start()
        except Exception as e:
            logger.error(f"Error starting MQTT client: {e}")

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()

    def check_connection(self) -> dict:
        test_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        subscribed = threading.Event()
        received = threading.Event()
        timing = {}

        def on_msg(c, u, msg):
            if msg.payload == b"probe_ping":
                timing["rtt"] = time.perf_counter() - timing["sent"]
                received.set()

        def on_conn(c, u, flags, rc, props=None):
            if rc == 0:
                c.subscribe("health/test_probe")

        def on_sub(c, u, mid, reason_codes, props=None):
            subscribed.set()

        test_client.on_connect = on_conn
        test_client.on_subscribe = on_sub
        test_client.on_message = on_msg

        try:
            test_client.connect(self.host, self.port, keepalive=10)
            test_client.loop_start()
            try:
                # Publish only once the SUBACK is in, otherwise the probe can be missed.
                if not subscribed.wait(2.0):
                    return {"status": "error", "detail": "Subscription was not acknowledged within timeout"}
                timing["sent"] = time.perf_counter()
                test_client.publish("health/test_probe", "probe_ping")
                if not received.wait(2.0):
                    return {"status": "error", "detail": "Message was not received within timeout"}
                return {"status": "ok", "broker": f"{self.host}:{self.port}", "latency_ms": round(timing["rtt"] * 1000, 2)}
            finally:
                # Disconnect first so the network thread exits now instead of after its 1 s select timeout.
                test_client.disconnect()
                test_client.loop_stop()
        except Exception as e:
            return {"status": "error", "detail": str(e)}

mqtt_manager = MQTTManager()
