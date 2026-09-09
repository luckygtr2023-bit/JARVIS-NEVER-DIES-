"""Device-trust security tests (fail-closed verification).

Asserts the master-prompt security invariants that are verifiable at the
gateway layer without live devices/network:

  UNTRUSTED DEVICE → DENY
  REVOKED DEVICE    → DENY
  WRONG SECRET      → DENY
  CORRUPT TRUST POLICY → FAIL CLOSED (no devices trusted)
  PAIRING OFFER     → SINGLE-USE, EXPIRES
"""

import asyncio
import json
from pathlib import Path

from brahma_connect.gateway.capability_manager import CapabilityManager
from brahma_connect.gateway.command_router import CommandRouter
from brahma_connect.gateway.device_manager import DeviceManager
from brahma_connect.gateway.pairing import PairingManager
from brahma_connect.gateway.websocket import ConnectionHub


def _paired_device(manager: DeviceManager, name: str = "Galaxy S24", platform: str = "android"):
    record, secret = manager.create_from_pairing(
        name=name, platform=platform, capabilities=["screen", "files"]
    )
    return record, secret


def test_unknown_device_cannot_authenticate(tmp_path: Path):
    manager = DeviceManager(tmp_path / "devices.json")
    assert manager.authenticate("android_000001", "any-secret") is None


def test_wrong_secret_rejected(tmp_path: Path):
    manager = DeviceManager(tmp_path / "devices.json")
    record, secret = _paired_device(manager)
    assert manager.authenticate(record.device_id, "wrong-secret") is None
    assert manager.authenticate(record.device_id, secret) is not None


def test_revoked_device_cannot_authenticate(tmp_path: Path):
    manager = DeviceManager(tmp_path / "devices.json")
    record, secret = _paired_device(manager)
    assert manager.revoke(record.device_id) is True
    assert manager.authenticate(record.device_id, secret) is None


def test_corrupt_registry_fails_closed(tmp_path: Path):
    registry = tmp_path / "devices.json"
    registry.write_text("{ this is not valid json !!!", encoding="utf-8")
    manager = DeviceManager(registry)
    assert manager.list_devices() == []
    assert manager.authenticate("anything", "x") is None


def test_wrong_shape_registry_fails_closed(tmp_path: Path):
    """A registry that is JSON but not a device dict must not crash NOR trust."""
    registry = tmp_path / "devices.json"
    registry.write_text(json.dumps({"devices": ["not-a-dict", 42]}), encoding="utf-8")
    manager = DeviceManager(registry)
    assert manager.list_devices() == []
    # list-shaped registry must not raise on construction
    registry.write_text(json.dumps(["also-not-a-dict"]), encoding="utf-8")
    manager2 = DeviceManager(registry)
    assert manager2.list_devices() == []


def test_revocation_persists_after_reload(tmp_path: Path):
    registry = tmp_path / "devices.json"
    manager = DeviceManager(registry)
    record, secret = _paired_device(manager)
    manager.revoke(record.device_id)
    manager2 = DeviceManager(registry)
    assert manager2.authenticate(record.device_id, secret) is None


def test_router_denies_unknown_device():
    manager = DeviceManager(Path("/tmp/nonexistent-devices-xyz.json"))
    router = CommandRouter(manager, ConnectionHub(), CapabilityManager())
    result = asyncio.run(router.route("no-such-device", "open_app"))
    assert result["success"] is False
    assert result["error_code"] == "DEVICE_NOT_FOUND"


def test_router_denies_revoked_device(tmp_path: Path):
    manager = DeviceManager(tmp_path / "devices.json")
    record, _ = _paired_device(manager, name="Pixel 9")
    manager.revoke(record.device_id)
    router = CommandRouter(manager, ConnectionHub(), CapabilityManager())
    result = asyncio.run(router.route(record.name, "open_app"))
    assert result["success"] is False
    assert result["error_code"] == "DEVICE_REVOKED"


def test_router_denies_offline_device(tmp_path: Path):
    manager = DeviceManager(tmp_path / "devices.json")
    record, _ = _paired_device(manager, name="Offline Tablet")
    assert record.online is False  # paired but never authenticated/connected
    router = CommandRouter(manager, ConnectionHub(), CapabilityManager())
    result = asyncio.run(router.route(record.name, "open_app"))
    assert result["success"] is False
    assert result["error_code"] == "DEVICE_OFFLINE"


def test_pairing_offer_is_single_use(tmp_path: Path):
    manager = PairingManager()
    offer = manager.create_offer("127.0.0.1", 8765)
    assert manager.approve(offer.pairing_token) is offer
    # Second approval of the same token must fail (consumed).
    assert manager.approve(offer.pairing_token) is None
    # Code index was cleaned up too.
    assert manager.get_offer_by_code(offer.pairing_code) is None


def test_pairing_offer_expires(tmp_path: Path):
    manager = PairingManager()
    offer = manager.create_offer("127.0.0.1", 8765)
    offer.expires_at = 0  # force expiry
    assert manager.get_offer(offer.pairing_token) is None
    assert manager.get_offer_by_code(offer.pairing_code) is None
