from fastapi.testclient import TestClient
from sqlalchemy import select

from ffpanel import scheduler as scheduler_module
from ffpanel.main import create_app
from ffpanel.models import RuntimeCapability
from ffpanel.serialize import capability_dict


def test_gpu_snapshot_api_and_persistence(settings, monkeypatch, gpu_snapshot):
    async def detect(_):
        return gpu_snapshot

    monkeypatch.setattr(scheduler_module, "detect_capabilities", detect)
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/api/v1/snapshot")
        assert response.status_code == 200
        system = response.json()["system"]
        assert system["recommendedHardwareMode"] == "nvdec_nvenc"
        assert len(system["hardwareProfiles"]) == 9
        assert len(system["hardwareBackends"]) == 5
        with app.state.sessions() as session:
            row = session.scalar(select(RuntimeCapability))
            assert row.hardware_json == gpu_snapshot.hardware_dict()
            assert capability_dict(row)["hardwareProfiles"] == system["hardwareProfiles"]
            row.hardware_json = {}
            legacy = capability_dict(row)
            assert legacy["mppAvailable"]
            assert not next(profile for profile in legacy["hardwareProfiles"] if profile["id"] == "nvdec_nvenc")["available"]
