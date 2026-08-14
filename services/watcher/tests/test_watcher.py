from app.watcher import KubernetesWatcher


def test_scan_detects_waiting_reason_and_restarts(monkeypatch):
    watcher = KubernetesWatcher(namespaces=("demo",), restart_threshold=3)
    watcher._list_pods = lambda: [
        {
            "metadata": {"namespace": "demo", "name": "api-123"},
            "status": {
                "containerStatuses": [
                    {
                        "restartCount": 4,
                        "state": {"waiting": {"reason": "CrashLoopBackOff"}},
                    }
                ]
            },
        }
    ]

    incidents = watcher.scan()

    assert len(incidents) == 1
    assert incidents[0].namespace == "demo"
    assert incidents[0].pod_name == "api-123"
    assert incidents[0].reason == "CrashLoopBackOff"
    assert incidents[0].signature == "CrashLoopBackOff:RepeatedRestarts"
    assert incidents[0].as_job_request() == {
        "namespace": "demo",
        "pod_name": "api-123",
        "target_kind": "Pod",
    }


def test_scan_detects_oom_and_unschedulable_pods(monkeypatch):
    watcher = KubernetesWatcher(namespaces=("demo",), restart_threshold=3)
    watcher._list_pods = lambda: [
        {
            "metadata": {"namespace": "demo", "name": "worker"},
            "status": {
                "containerStatuses": [
                    {
                        "restartCount": 0,
                        "lastState": {"terminated": {"reason": "OOMKilled"}},
                    }
                ]
            },
        },
        {
            "metadata": {"namespace": "demo", "name": "pending"},
            "status": {
                "conditions": [{"reason": "Unschedulable"}],
            },
        },
    ]

    incidents = watcher.scan()

    assert [(item.pod_name, item.reason) for item in incidents] == [
        ("worker", "OOMKilled"),
        ("pending", "Unschedulable"),
    ]
