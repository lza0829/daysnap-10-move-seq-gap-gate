# -*- coding: utf-8 -*-
"""序缺口闸自动化断言：正式镜 vs 旁置镜、回放拒绝、补序晋升、多户、并发。

全服务层、每用例独立临时库；不依赖 httpx。HTTP 层用例在缺 httpx 时自动跳过。
"""

from __future__ import annotations

import threading

import pytest

from app import db
from app.modules import 流水序缺口 as 序闸
from app.services import 抽取, 回放, 装载

DAY = "2026-11-20"

INITIAL = [
    {"流水号": "k-01", "账户键": "户甲", "营业日": DAY, "变动额": 10000, "序号": 1},
    {"流水号": "k-03", "账户键": "户甲", "营业日": DAY, "变动额": -2500, "序号": 3},
]
FILL2 = [
    {"流水号": "k-02", "账户键": "户甲", "营业日": DAY, "变动额": -4000, "序号": 2},
]


@pytest.fixture()
def 临时库(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "数据目录", tmp_path)
    monkeypatch.setattr(db, "库路径", tmp_path / "序缺口测试.db")
    db._已就绪路径 = None
    db.初始化库()
    yield tmp_path


def _状态余额(acct="户甲", day=DAY):
    conn = db.连接()
    try:
        r = conn.execute(
            "SELECT 状态,余额 FROM 周期快照 WHERE 账户键=? AND 营业日=?", (acct, day)
        ).fetchone()
        return (r["状态"], r["余额"]) if r else (None, None)
    finally:
        conn.close()


def _有效数(acct="户甲", day=DAY):
    conn = db.连接()
    try:
        return conn.execute(
            "SELECT COUNT(*) c FROM 周期快照 WHERE 账户键=? AND 营业日=? AND 状态='有效'",
            (acct, day),
        ).fetchone()["c"]
    finally:
        conn.close()


def test_缺号核证四字段(临时库):
    装载.装载流水(INITIAL)
    v = 序闸.核证(账户键="户甲", 营业日=DAY)
    assert v["缺口区间"] == [[2, 2]]
    assert v["旁置有无"] is False
    assert v["可否晋升"] is False
    assert v["valid"] is False


def test_乙_旁置镜非权威_补序后须晋升(临时库):
    装载.装载流水(INITIAL)
    # 缺口未补禁止晋升（失败闭）。
    with pytest.raises(ValueError):
        序闸.晋升旁置("户甲", DAY)

    rep = 抽取.日终抽取(DAY)
    assert rep["序缺口"] == 1 and rep["通过"] is False
    assert rep["旁置日终"] == 1
    assert _有效数() == 0
    assert _状态余额() == ("旁置", 7500)  # 残缺净额只许进旁置

    v = 序闸.核证(账户键="户甲", 营业日=DAY)
    assert v["旁置有无"] is True and v["正式有无"] is False
    assert v["可否晋升"] is False and v["valid"] is False

    rp = 回放.回放核对(DAY)
    assert rp["通过"] is False and rp["序缺口拒绝"] >= 1

    # 补 2：缺口闭合、可晋升，但未显式晋升前仍无正式镜、回放仍拒绝。
    装载.装载流水(FILL2)
    v = 序闸.核证(账户键="户甲", 营业日=DAY)
    assert v["缺口区间"] == [] and v["可否晋升"] is True and v["valid"] is False
    assert _有效数() == 0
    assert 回放.回放核对(DAY)["通过"] is False

    # 晋升按全量流水重算，残缺值 7500 不得成为正式镜。
    p = 序闸.晋升旁置("户甲", DAY)
    assert p["余额"] == 3500 and p["动作"] == "旁置晋升正式"
    assert _状态余额() == ("有效", 3500)
    v = 序闸.核证(账户键="户甲", 营业日=DAY)
    assert v["valid"] is True and v["可否晋升"] is False and v["旁置有无"] is False
    rp = 回放.回放核对(DAY)
    assert rp["通过"] is True and rp["差额"] == 0


def test_甲_登记阻塞_无任何日终镜(临时库):
    conn = db.连接()
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        "INSERT INTO 台参(键,值) VALUES('序缺口口径',?)", (序闸.口径_阻塞,)
    )
    conn.commit()
    conn.close()

    装载.装载流水(INITIAL)
    rep = 抽取.日终抽取(DAY)
    assert rep["口径"] == 序闸.口径_阻塞 and rep["通过"] is False
    assert _状态余额() == (None, None)  # 无正式也无旁置日终镜
    conn = db.连接()
    try:
        assert conn.execute("SELECT COUNT(*) c FROM 旁置日终镜").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) c FROM 序缺口登记").fetchone()["c"] >= 1
    finally:
        conn.close()
    assert 回放.回放核对(DAY)["通过"] is False

    装载.装载流水(FILL2)
    rep2 = 抽取.日终抽取(DAY)
    assert rep2["通过"] is True
    assert _状态余额() == ("有效", 3500)
    assert 回放.回放核对(DAY)["通过"] is True


def test_多户混合_完整户不被连坐(临时库):
    flows = INITIAL + [
        {"流水号": "m-乙-1", "账户键": "户乙", "营业日": DAY, "变动额": 5000, "序号": 1},
        {"流水号": "m-乙-2", "账户键": "户乙", "营业日": DAY, "变动额": 200, "序号": 2},
    ]
    装载.装载流水(flows)
    rep = 抽取.日终抽取(DAY)
    assert rep["序缺口"] == 1 and rep["通过"] is False
    assert _状态余额("户乙") == ("有效", 5200)
    assert _有效数("户乙") == 1
    assert _有效数("户甲") == 0 and _状态余额("户甲")[0] == "旁置"

    rp = 回放.回放核对(DAY)
    assert rp["通过"] is False
    conn = db.连接()
    try:
        assert conn.execute(
            "SELECT COUNT(*) c FROM 差额行 WHERE 账户键='户乙'"
        ).fetchone()["c"] == 0
        assert conn.execute(
            "SELECT COUNT(*) c FROM 差额行 WHERE 账户键='户甲'"
        ).fetchone()["c"] >= 1
    finally:
        conn.close()


def test_并发补序与抽取_无残缺正式镜(临时库):
    rounds = 8
    saw_bad = []
    errors = []
    for r in range(rounds):
        acct, day = f"户并发{r}", "2026-11-24"
        conn = db.连接()
        conn.execute(
            "INSERT INTO 账户(账户键,户名,开户营业日) VALUES (?,?,?)",
            (acct, acct, "2026-11-01"),
        )
        conn.commit()
        conn.close()

        装载.装载流水([
            {"流水号": f"r{r}-1", "账户键": acct, "营业日": day, "变动额": 10000, "序号": 1},
            {"流水号": f"r{r}-3", "账户键": acct, "营业日": day, "变动额": -2500, "序号": 3},
        ])
        bar = threading.Barrier(3)

        def do_fill():
            try:
                bar.wait()
                装载.装载流水([
                    {"流水号": f"r{r}-2", "账户键": acct, "营业日": day, "变动额": -4000, "序号": 2}
                ])
            except BaseException as e:  # noqa: BLE001
                errors.append(e)

        def do_extract():
            try:
                bar.wait()
                抽取.日终抽取(day)
            except BaseException as e:  # noqa: BLE001
                errors.append(e)

        stop = threading.Event()

        def watch():
            m = db.原始连接()
            try:
                while not stop.is_set():
                    for row in m.execute(
                        "SELECT 余额 FROM 周期快照 WHERE 账户键=? AND 营业日=? AND 状态='有效'",
                        (acct, day),
                    ):
                        if int(row["余额"]) == 7500:
                            saw_bad.append(acct)
                    stop.wait(0.001)
            finally:
                m.close()

        tw = threading.Thread(target=watch)
        threads = [threading.Thread(target=do_fill),
                   threading.Thread(target=do_extract),
                   threading.Thread(target=do_extract)]
        tw.start()
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        stop.set()
        tw.join(5)

        assert not errors, [repr(e) for e in errors]
        # 收敛终态。
        装载.装载流水([
            {"流水号": f"r{r}-2", "账户键": acct, "营业日": day, "变动额": -4000, "序号": 2}
        ])
        st, bal = _状态余额(acct, day)
        if st == "旁置":
            序闸.晋升旁置(acct, day)
            st, bal = _状态余额(acct, day)
        assert (st, bal) == ("有效", 3500)
        assert 回放.回放核对(day)["通过"] is True

    assert saw_bad == []


def test_http_核证与晋升端点(临时库):
    httpx = pytest.importorskip("httpx")  # noqa: F841
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        c.post("/api/装载", json={"流水": INITIAL})
        r = c.get("/api/序缺口核证", params={"账户键": "户甲", "营业日": DAY})
        assert r.status_code == 200
        body = r.json()
        for k in ("缺口区间", "旁置有无", "可否晋升", "valid"):
            assert k in body
        c.post("/api/抽取", json={"营业日": DAY})
        side = c.get("/api/旁置日终", params={"账户键": "户甲", "营业日": DAY}).json()
        assert len(side) == 1 and side[0]["状态"] == "旁置"
        assert c.post("/api/回放", json={"营业日": DAY}).json()["通过"] is False
        c.post("/api/补序装载", json={"流水": FILL2})
        p = c.post("/api/晋升", json={"账户键": "户甲", "营业日": DAY})
        assert p.status_code == 200 and p.json()["余额"] == 3500
        assert c.post("/api/回放", json={"营业日": DAY}).json()["通过"] is True
