import time
import sys
import paho.mqtt.client as mqtt

received_messages = []

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("[MQTT] Connected to broker, subscribing to frigate/# ...")
        client.subscribe("frigate/#")
    else:
        print(f"[MQTT] Connect failed with rc={rc}")

def on_message(client, userdata, msg):
    payload = msg.payload.decode("utf-8", errors="replace")
    print(f"  [FRIGATE MQTT EVENT] Topic: {msg.topic} -> Payload: {payload[:120]}")
    received_messages.append({"topic": msg.topic, "payload": payload})

def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message

    print("Connecting to localhost:1883 to verify Frigate MQTT events...")
    client.connect("localhost", 1883, 60)
    client.loop_start()

    # Wait up to 10 seconds for events
    timeout = time.time() + 10.0
    while time.time() < timeout and len(received_messages) < 2:
        time.sleep(0.5)

    client.loop_stop()
    client.disconnect()

    if received_messages:
        print(f"\n[SUCCESS] Successfully captured {len(received_messages)} Frigate MQTT event(s)!")
        for m in received_messages[:5]:
            print(f"  * {m['topic']}")
        sys.exit(0)
    else:
        print("\n[FAILURE] Did not capture any Frigate MQTT events.", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
