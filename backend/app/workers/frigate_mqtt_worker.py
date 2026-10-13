import json
import logging
import uuid
from typing import Optional, Union, Dict, Any
import paho.mqtt.client as mqtt
from sqlalchemy.orm import Session

from backend.app.config import MQTT_BROKER_HOST, MQTT_BROKER_PORT
from backend.app.db import SessionLocal
from backend.app.models.observation import ObservationEvent
from backend.app.services.frigate_event_parser import FrigateEventParser
from backend.app.services.observation_service import ObservationService

logger = logging.getLogger("campus_security.frigate_worker")

def _reject_non_finite(constant: str):
    """json.loads hook: NaN/Infinity are not JSON (RFC 8259) and PostgreSQL's JSON type rejects them."""
    raise ValueError(f"non-finite number {constant} in payload")

class FrigateMQTTWorker:
    """
    Background worker that subscribes to Frigate NVR MQTT telemetry on 'frigate/events',
    translates sensory payloads into ObservationCreate schemas via FrigateEventParser,
    and persists them into PostgreSQL via ObservationService.
    """

    def __init__(
        self,
        host: str = MQTT_BROKER_HOST,
        port: int = MQTT_BROKER_PORT,
        topic: str = "frigate/events",
        client_id: Optional[str] = None
    ):
        self.host = host
        self.port = port
        self.topic = topic
        self.client_id = client_id or f"campus_frigate_worker_{uuid.uuid4().hex[:6]}"
        
        self.client: Optional[mqtt.Client] = None
        self.connected = False
        self.running = False

        self.stats: Dict[str, int] = {
            "messages_received": 0,
            "observations_created": 0,
            "observations_updated": 0,
            "unmapped_cameras": 0,
            "non_vehicle_events": 0,
            "malformed_payloads": 0,
            "errors": 0,
        }

    def _setup_client(self):
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.client_id
        )
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            self.connected = True
            logger.info(f"FrigateMQTTWorker connected to MQTT broker at {self.host}:{self.port}")
            client.subscribe(self.topic)
            logger.info(f"FrigateMQTTWorker subscribed to topic: '{self.topic}'")
        else:
            self.connected = False
            logger.error(f"FrigateMQTTWorker failed to connect to broker, rc={rc}")

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties=None):
        self.connected = False
        logger.warning(f"FrigateMQTTWorker disconnected from broker: {reason_code}")

    def _on_message(self, client, userdata, msg):
        self.stats["messages_received"] += 1
        try:
            self.process_payload(msg.payload)
        except Exception as e:
            self.stats["errors"] += 1
            logger.error(f"Unhandled error in FrigateMQTTWorker message handler: {e}", exc_info=True)

    def process_payload(
        self,
        raw_payload: Union[str, bytes, Dict[str, Any]],
        db: Optional[Session] = None
    ) -> Optional[ObservationEvent]:
        """
        Decodes, validates, parses, and persists a Frigate event payload.
        Can be called directly by tests or background message callbacks.
        """
        # 1. Parse JSON if string or bytes
        if isinstance(raw_payload, (str, bytes)):
            try:
                if isinstance(raw_payload, bytes):
                    payload_str = raw_payload.decode("utf-8")
                else:
                    payload_str = raw_payload
                payload_dict = json.loads(payload_str, parse_constant=_reject_non_finite)
            except Exception as e:
                self.stats["malformed_payloads"] += 1
                logger.warning(f"FrigateMQTTWorker received malformed JSON payload: {e}")
                return None
        elif isinstance(raw_payload, dict):
            payload_dict = raw_payload
        else:
            self.stats["malformed_payloads"] += 1
            logger.warning(f"FrigateMQTTWorker received unsupported payload type: {type(raw_payload)}")
            return None

        # 2. Manage database session
        session_created = False
        if db is None:
            db = SessionLocal()
            session_created = True

        try:
            # 3. Parse event via FrigateEventParser
            obs_create = FrigateEventParser.parse_event(payload_dict, db)
            if not obs_create:
                # Could be a non-vehicle object, an unmapped camera or a missing event ID
                after = payload_dict.get("after") if isinstance(payload_dict.get("after"), dict) else payload_dict
                camera = after.get("camera")
                if FrigateEventParser.is_non_vehicle(after):
                    self.stats["non_vehicle_events"] += 1
                elif camera and not FrigateEventParser.resolve_camera_to_gate(camera, db):
                    self.stats["unmapped_cameras"] += 1
                else:
                    self.stats["malformed_payloads"] += 1
                return None

            # 4. Check whether this is a creation or update for telemetry stats
            existing_obs = None
            if obs_create.source_event_id:
                existing_obs = db.query(ObservationEvent).filter_by(
                    source=obs_create.source,
                    source_event_id=obs_create.source_event_id
                ).first()

            # 5. Delegate persistence to authoritative ObservationService
            saved_obs = ObservationService.create_or_update_observation(db, obs_create)

            if existing_obs:
                self.stats["observations_updated"] += 1
                logger.debug(
                    f"Refined ObservationEvent '{saved_obs.id}' for source_event_id='{obs_create.source_event_id}'"
                )
            else:
                self.stats["observations_created"] += 1
                logger.info(
                    f"Created ObservationEvent '{saved_obs.id}' for gate='{saved_obs.gate_id}' "
                    f"plate='{saved_obs.normalized_plate}' type='{saved_obs.vehicle_type.value}'"
                )

            return saved_obs

        except Exception as e:
            db.rollback()
            self.stats["errors"] += 1
            logger.error(f"Error persisting Frigate observation: {e}", exc_info=True)
            return None
        finally:
            if session_created:
                db.close()

    def start(self):
        """Starts the MQTT worker client loop in the background."""
        if self.running:
            logger.info("FrigateMQTTWorker already running.")
            return

        self._setup_client()
        logger.info(f"Starting FrigateMQTTWorker connecting to {self.host}:{self.port}...")
        try:
            self.client.connect(self.host, self.port, keepalive=60)
            self.client.loop_start()
            self.running = True
        except Exception as e:
            logger.error(f"FrigateMQTTWorker failed to connect on startup: {e}")
            self.running = False

    def stop(self):
        """Stops the MQTT worker loop and disconnects cleanly."""
        if not self.running or not self.client:
            return

        logger.info("Stopping FrigateMQTTWorker...")
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception as e:
            logger.warning(f"Exception while disconnecting FrigateMQTTWorker: {e}")
        finally:
            self.running = False
            self.connected = False
            self.client = None
            logger.info("FrigateMQTTWorker stopped.")

    def is_connected(self) -> bool:
        return self.connected

    def get_stats(self) -> Dict[str, Any]:
        return {
            "running": self.running,
            "connected": self.connected,
            "topic": self.topic,
            "stats": dict(self.stats)
        }

# Global worker singleton
frigate_worker = FrigateMQTTWorker()
