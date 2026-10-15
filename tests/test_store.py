from jobhunt.models import JobDetail, JobStub
from jobhunt.store import Store


def stub(n):
    return JobStub(source="s", external_id=str(n), url=f"u{n}", title=f"T{n}", company="C")


def test_avisos_que_desaparecen_quedan_cerrados_y_vuelven_si_reaparecen(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    for n in (1, 2, 3):
        store.upsert_stub(stub(n))
        store.save_detail(stub(n).id, JobDetail(description="d"))
    store.set_status(stub(3).id, "filtered")

    gone = store.mark_gone("s", {stub(1).id})
    assert gone == [stub(2).id]  # los filtrados no se tocan
    assert store.get(stub(2).id)["status"] == "gone"

    store.upsert_stub(stub(2))
    assert store.get(stub(2).id)["status"] == "pending"
