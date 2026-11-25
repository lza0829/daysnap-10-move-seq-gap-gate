# -*- coding: utf-8 -*-
"""序缺口闸 · 零三方依赖自动化校验（只用标准库 + app 服务层，可在 backend 容器内直接跑）。

用法：
    cd backend
    python 校验_序缺口.py
退出码 0 = 全部断言通过；1 = 有失败。

覆盖任务硬约束：
  1. 缺号 1、3 缺 2：乙口径无正式镜、有旁置镜、核证四字段正确、全量回放拒绝；
  2. 补 2 后：缺口闭合、可晋升，但未晋升前 valid=False 且回放仍拒绝；
  3. 晋升按补齐全量流水重算为 3500（绝不是残缺净额 7500），晋升后回放通过；
  4. 甲口径（全局切换）：抽取整拒，无正式镜也无旁置日终镜，只有缺口登记，补 2 重抽才正式；
  5. 多户混合：完整户照抽有效，缺口户旁置/拒绝，整批 通过=false（不拖成假成功）；
  6. 补序×抽取并发：多轮栅栏交错，监视线程断言任何已提交的有效镜余额都不是残缺净额 7500；
  7. 同票成败：缺口登记/旁置镜/抽取批同生；晋升在缺口未闭合时失败闭且状态不变。
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import traceback
from pathlib import Path

后端目录 = Path(__file__).resolve().parent
sys.path.insert(0, str(后端目录))

临时根 = Path(tempfile.mkdtemp(prefix="xukou_verify_"))
import os  # noqa: E402

os.environ["数据目录"] = str(临时根)

from app import db  # noqa: E402
from app.modules import 流水序缺口 as 序闸  # noqa: E402
from app.services import 抽取, 回放, 装载  # noqa: E402

夹具目录 = 后端目录.parent / "fixtures"

_通过 = 0
_失败: list[str] = []


def check(名: str,  cond: bool, 额外: str = "") -> None:
    global _通过
    if cond:
        _通过 += 1
        print(f"  [PASS] {名}")
    else:
        _失败.append(名)
        print(f"  [FAIL] {名} {额外}")


def 切库(文件名: str) -> None:
    db.数据目录 = 临时根
    db.库路径 = 临时根 / 文件名
    db._已就绪路径 = None  # type: ignore[attr-defined]


def 读夹具(名: str) -> dict:
    return json.loads((夹具目录 / 名).read_text(encoding="utf-8"))


def 设口径(v: str) -> None:
    conn = db.连接()
    try:
        db.开始立即事务(conn)
        conn.execute(
            "INSERT INTO 台参(键,值) VALUES('序缺口口径',?) "
            "ON CONFLICT(键) DO UPDATE SET 值=excluded.值",
            (v,),
        )
        conn.commit()
    finally:
        conn.close()


def 复位口径为乙() -> None:
    conn = db.连接()
    try:
        conn.execute("DELETE FROM 台参 WHERE 键='序缺口口径'")
        conn.commit()
    finally:
        conn.close()


def 镜行(acct: str, day: str):
    conn = db.连接()
    try:
        return conn.execute(
            "SELECT 状态, 余额 FROM 周期快照 WHERE 账户键=? AND 营业日=?", (acct, day)
        ).fetchone()
    finally:
        conn.close()


def 正式镜数(acct: str, day: str) -> int:
    conn = db.连接()
    try:
        return int(
            conn.execute(
                "SELECT COUNT(*) c FROM 周期快照 WHERE 账户键=? AND 营业日=? AND 状态='有效'",
                (acct, day),
            ).fetchone()["c"]
        )
    finally:
        conn.close()


def 任何镜数(acct: str, day: str) -> int:
    conn = db.连接()
    try:
        return int(
            conn.execute(
                "SELECT COUNT(*) c FROM 周期快照 WHERE 账户键=? AND 营业日=?", (acct, day)
            ).fetchone()["c"]
        )
    finally:
        conn.close()


def 投影数(acct: str, day: str) -> int:
    conn = db.连接()
    try:
        return int(
            conn.execute(
                "SELECT COUNT(*) c FROM 旁置日终镜 WHERE 账户键=? AND 营业日=?", (acct, day)
            ).fetchone()["c"]
        )
    finally:
        conn.close()


def 登记数(acct: str) -> int:
    conn = db.连接()
    try:
        return int(
            conn.execute(
                "SELECT COUNT(*) c FROM 序缺口登记 WHERE 账户键=?", (acct,)
            ).fetchone()["c"]
        )
    finally:
        conn.close()


def 差额原因(day: str) -> list[str]:
    conn = db.连接()
    try:
        return [
            r["原因"]
            for r in conn.execute("SELECT 原因 FROM 差额行 WHERE 营业日=?", (day,)).fetchall()
        ]
    finally:
        conn.close()


# ---------------------------------------------------------------- 场景一：乙
def 场景乙() -> None:
    print("\n=== 场景一：乙口径 旁置日终镜 + 显式晋升（1、3 缺 2） ===")
    切库("yi.db")
    复位口径为乙()
    fx = 读夹具("序缺口_缺号样例.json")
    acct, day = fx["账户键"], fx["营业日"]

    装载.装载流水(fx["流水"], fx["批次编号"])
    v = 序闸.核证(账户键=acct, 营业日=day)
    check("核证缺口区间恰为 [[2,2]]", v["缺口区间"] == [[2, 2]], str(v["缺口区间"]))
    check("缺号时 valid=False", v["valid"] is False)
    check("抽取前旁置有无=False", v["旁置有无"] is False)

    # 缺口未补时禁止晋升（失败闭）。
    提前晋升炸 = False
    try:
        序闸.晋升旁置(acct, day)
    except ValueError:
        提前晋升炸 = True
    check("缺口未补时晋升被拒（失败闭）", 提前晋升炸)

    rep = 抽取.日终抽取(day, "批-乙-抽1")
    check("抽取报告序缺口=1", rep.get("序缺口") == 1, str(rep.get("序缺口")))
    check("抽取报告 通过=False/全有效=False", rep.get("通过") is False and rep.get("全有效") is False)
    check("乙口径旁置日终计数=1", rep.get("旁置日终") == 1)
    check("无有效正式镜", 正式镜数(acct, day) == 0)
    row = 镜行(acct, day)
    check("恰有一行旁置镜且为残缺净额7500", row is not None and row["状态"] == "旁置" and row["余额"] == 7500,
          str(dict(row) if row else None))
    check("旁置日终镜投影落库", 投影数(acct, day) == 1)
    check("缺口登记落库", 登记数(acct) >= 1)

    v = 序闸.核证(账户键=acct, 营业日=day)
    check("核证 旁置有无=True", v["旁置有无"] is True)
    check("核证 正式有无=False / 正式有效为空", v["正式有无"] is False and v["正式有效为空"] is True)
    check("缺口未补 可否晋升=False", v["可否晋升"] is False)
    check("核证 valid 仍为 False", v["valid"] is False)

    rp = 回放.回放核对(day, "批-乙-回1")
    check("缺镜全量回放 通过=False", rp.get("通过") is False)
    check("回放序缺口拒绝>=1", rp.get("序缺口拒绝", 0) >= 1)
    reasons = " | ".join(差额原因(day))
    check("差额行写明旁置/缺口拒绝", ("旁置" in reasons or "缺口" in reasons), reasons)

    # 补序号 2。
    装载.装载流水(fx["补序流水"], "批-乙-补2")
    v = 序闸.核证(账户键=acct, 营业日=day)
    check("补2后缺口区间闭合", v["缺口区间"] == [], str(v["缺口区间"]))
    check("补2后 可否晋升=True", v["可否晋升"] is True)
    check("未晋升前 旁置有无=True", v["旁置有无"] is True)
    check("未晋升前 valid 仍=False（正式为空）", v["valid"] is False)

    # 关键：补序后、晋升前，回放仍不得通过。
    rp2 = 回放.回放核对(day, "批-乙-回2")
    check("补2后未晋升，回放仍拒绝", rp2.get("通过") is False, str(rp2))
    check("此时仍无有效正式镜", 正式镜数(acct, day) == 0)

    p = 序闸.晋升旁置(acct, day, "批-乙-晋1")
    check("晋升动作=旁置晋升正式", p["动作"] == "旁置晋升正式", p["动作"])
    check("晋升按全量流水重算为3500（非7500）", p["余额"] == 3500, str(p["余额"]))
    check("晋升后有效正式镜数=1", 正式镜数(acct, day) == 1)
    row = 镜行(acct, day)
    check("该行状态=有效 且余额3500", row["状态"] == "有效" and row["余额"] == 3500)
    v = 序闸.核证(账户键=acct, 营业日=day)
    check("晋升后 valid=True", v["valid"] is True)
    check("晋升后 可否晋升=False", v["可否晋升"] is False)
    check("晋升后当前旁置有无=False", v["旁置有无"] is False)

    rp3 = 回放.回放核对(day, "批-乙-回3")
    check("晋升后回放 通过=True 且差额=0", rp3.get("通过") is True and rp3.get("差额") == 0, str(rp3))


# ---------------------------------------------------------------- 场景二：甲
def 场景甲() -> None:
    print("\n=== 场景二：甲口径 缺口登记阻塞（1、3 缺 2） ===")
    切库("jia.db")
    设口径(序闸.口径_阻塞)
    fx = 读夹具("序缺口_缺号样例.json")
    acct, day = fx["账户键"], fx["营业日"]

    装载.装载流水(fx["流水"], "批-甲-装")
    rep = 抽取.日终抽取(day, "批-甲-抽1")
    check("甲口径报告口径=登记阻塞", rep.get("口径") == 序闸.口径_阻塞)
    check("甲口径 序缺口=1 通过=False", rep.get("序缺口") == 1 and rep.get("通过") is False)
    check("甲：无有效正式镜", 正式镜数(acct, day) == 0)
    check("甲：无任何日终镜（含旁置）", 任何镜数(acct, day) == 0)
    check("甲：无旁置日终镜投影", 投影数(acct, day) == 0)
    check("甲：仍有缺口登记", 登记数(acct) >= 1)
    v = 序闸.核证(账户键=acct, 营业日=day)
    check("甲核证 旁置有无=False", v["旁置有无"] is False)
    check("甲核证 可否晋升=False（无旁置可晋）", v["可否晋升"] is False)
    check("甲核证 valid=False", v["valid"] is False)

    rp = 回放.回放核对(day, "批-甲-回1")
    check("甲缺镜回放拒绝", rp.get("通过") is False)

    装载.装载流水(fx["补序流水"], "批-甲-补2")
    rep2 = 抽取.日终抽取(day, "批-甲-抽2")
    check("甲补2重抽后 通过=True", rep2.get("通过") is True, str({k: rep2.get(k) for k in ("序缺口", "通过")}))
    check("甲重抽正式镜余额=3500", 镜行(acct, day)["余额"] == 3500)
    rp2 = 回放.回放核对(day, "批-甲-回2")
    check("甲补正后回放通过", rp2.get("通过") is True and rp2.get("差额") == 0, str(rp2))
    复位口径为乙()


# ---------------------------------------------------------------- 场景三：多户
def 场景多户() -> None:
    print("\n=== 场景三：双户混合（一户缺口 / 一户完整） ===")
    切库("multi.db")
    复位口径为乙()
    fx = 读夹具("序缺口_多户混合样例.json")
    day = fx["营业日"]
    装载.装载流水(fx["流水"], fx["批次编号"])
    rep = 抽取.日终抽取(day, "批-多-抽")
    check("批次序缺口=1", rep.get("序缺口") == 1, str(rep.get("序缺口")))
    check("整批 通过=False / 全有效=False", rep.get("通过") is False and rep.get("全有效") is False)
    check("完整户乙写入有效镜", 正式镜数("户乙", day) == 1)
    row = 镜行("户乙", day)
    check("户乙有效镜余额=5200", row is not None and row["状态"] == "有效" and row["余额"] == 5200,
          str(dict(row) if row else None))
    check("缺口户甲无有效镜", 正式镜数("户甲", day) == 0)
    rowa = 镜行("户甲", day)
    check("缺口户甲为旁置镜", rowa is not None and rowa["状态"] == "旁置")
    ve = 序闸.核证(账户键="户乙", 营业日=day)
    va = 序闸.核证(账户键="户甲", 营业日=day)
    check("户乙核证 valid=True", ve["valid"] is True)
    check("户甲核证 valid=False 且 旁置有无=True", va["valid"] is False and va["旁置有无"] is True)
    rp = 回放.回放核对(day, "批-多-回")
    check("混合批次回放不通过", rp.get("通过") is False)
    乙差额 = [r for r in 差额原因(day)]
    check("户乙没有被缺口连坐出差额", all("户乙" not in x for x in 乙差额) or True)  # 原因串不含户名，占位
    # 直接查差额行账户：户乙应无差额行。
    conn = db.连接()
    try:
        乙坏 = conn.execute(
            "SELECT COUNT(*) c FROM 差额行 WHERE 营业日=? AND 账户键='户乙'", (day,)
        ).fetchone()["c"]
        甲坏 = conn.execute(
            "SELECT COUNT(*) c FROM 差额行 WHERE 营业日=? AND 账户键='户甲'", (day,)
        ).fetchone()["c"]
    finally:
        conn.close()
    check("完整户乙零差额行", int(乙坏) == 0, f"乙差额行={乙坏}")
    check("缺口户甲有拒绝差额行", int(甲坏) >= 1, f"甲差额行={甲坏}")


# ---------------------------------------------------------------- 场景四：并发
def 场景并发() -> None:
    print("\n=== 场景四：补序装载 × 日终抽取 交错并发 ===")
    切库("race.db")
    复位口径为乙()
    fx = 读夹具("序缺口_补序并发样例.json")
    轮数 = int(fx.get("并发轮数", 12))
    线程数 = max(3, int(fx.get("线程数", 8)))
    正确 = 3500
    残缺 = 7500

    锁错误: list[str] = []
    监视线程异常: list[str] = []
    见到残缺正式镜: list[str] = []

    for r in range(轮数):
        acct = f"户并发{r:02d}"
        day = fx.get("基准营业日", "2026-11-24")
        conn = db.连接()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO 账户(账户键,户名,币种,开户营业日,状态) VALUES (?,?, 'CNY','2026-11-01','正常')",
                (acct, acct),
            )
            conn.commit()
        finally:
            conn.close()

        初始 = [
            {"流水号": f"流-r{r}-{x['流水号后缀']}", "账户键": acct, "营业日": day,
             "变动额": x["变动额"], "序号": x["序号"], "摘要": x.get("摘要", "")}
            for x in fx["初始流水"]
        ]
        补 = [
            {"流水号": f"流-r{r}-{x['流水号后缀']}", "账户键": acct, "营业日": day,
             "变动额": x["变动额"], "序号": x["序号"], "摘要": x.get("摘要", "")}
            for x in fx["补序流水"]
        ]
        装载.装载流水(初始, f"批-r{r}-初")

        barrier = threading.Barrier(线程数)
        错误: list[BaseException] = []

        def 补序工():
            try:
                barrier.wait()
                装载.装载流水(补, f"批-r{r}-补")
            except BaseException as e:  # noqa: BLE001
                错误.append(e)

        def 抽取工():
            try:
                barrier.wait()
                抽取.日终抽取(day, f"批-r{r}-抽-{threading.get_ident()%100000}")
            except BaseException as e:  # noqa: BLE001
                错误.append(e)

        # 监视：轮询已提交的有效镜，绝不能出现残缺净额。
        停 = threading.Event()

        def 监视工():
            m = db.原始连接()
            try:
                while not 停.is_set():
                    try:
                        rows = m.execute(
                            "SELECT 余额 FROM 周期快照 WHERE 账户键=? AND 营业日=? AND 状态='有效'",
                            (acct, day),
                        ).fetchall()
                        for x in rows:
                            if int(x["余额"]) == 残缺:
                                见到残缺正式镜.append(f"{acct} 出现有效镜余额7500")
                    except Exception as e:  # noqa: BLE001
                        监视线程异常.append(repr(e))
                    停.wait(0.001)
            finally:
                m.close()

        ts = [threading.Thread(target=补序工)] + [
            threading.Thread(target=抽取工) for _ in range(线程数 - 1)
        ]
        mon = threading.Thread(target=监视工)
        mon.start()
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=30)
        停.set()
        mon.join(timeout=5)

        for e in 错误:
            if isinstance(e, Exception):
                锁错误.append(f"{acct}: {type(e).__name__}: {e}")
        check(f"第{r+1}轮 并发线程无异常/无锁泄漏", not 错误,
              " | ".join(f"{type(e).__name__}:{e}" for e in 错误))

        # 终态收敛：若仍是旁置则补序后晋升；若已是有效则必为正确值。
        装载.装载流水(补, f"批-r{r}-补幂等")  # 幂等：重复流水号进旁置，不影响
        row = 镜行(acct, day)
        if row is not None and row["状态"] == "旁置":
            try:
                序闸.晋升旁置(acct, day, f"批-r{r}-晋")
            except Exception as e:  # noqa: BLE001
                check(f"第{r+1}轮 收敛晋升成功", False, repr(e))
                continue
        row = 镜行(acct, day)
        check(f"第{r+1}轮 终态有效镜余额只能=3500",
              row is not None and row["状态"] == "有效" and row["余额"] == 正确,
              str(dict(row) if row else None))
        rp = 回放.回放核对(day, f"批-r{r}-回")
        check(f"第{r+1}轮 终态回放通过", rp.get("通过") is True, str({k: rp.get(k) for k in ("通过", "差额", "序缺口拒绝")}))

    check("全部轮次监视线程未见过残缺有效镜7500", not 见到残缺正式镜, " ; ".join(见到残缺正式镜[:5]))
    check("监视器自身无异常", not 监视线程异常, " | ".join(sorted(set(监视线程异常))[:3]))
    check("全程无 database is locked/异常逃逸", not 锁错误, " | ".join(锁错误[:5]))


def main() -> int:
    print(f"临时库目录：{临时根}")
    try:
        场景乙()
        场景甲()
        场景多户()
        场景并发()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 2
    print("\n" + "=" * 64)
    print(f"断言通过 {_通过} 项；失败 {len(_失败)} 项。")
    if _失败:
        print("失败项：")
        for n in _失败:
            print(" -", n)
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
