import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db import 夹具目录, 连接
from app.modules import 流水序缺口 as 序闸
from app.services import 回放, 抽取, 目录, 装载

路由 = APIRouter(prefix="/api")


class 装载请求(BaseModel):
    批次编号: str = ""
    流水: list = Field(default_factory=list)


class 营业日请求(BaseModel):
    营业日: str
    批次编号: str = ""


class 核证请求(BaseModel):
    账户键: str = ""
    营业日: str = ""


class 晋升请求(BaseModel):
    账户键: str
    营业日: str
    批次编号: str = ""


class 口径请求(BaseModel):
    口径: str = ""


@路由.get("/健康")
def 健康():
    return {
        "正常": True,
        "项目": "日镜账",
        "骨架": "日终余额抽取→周期快照落行→变动流水回放核对→断档跳变检出→快照与回放差额清单",
        "序缺口口径": 序闸.当前口径(),
    }


@路由.get("/总览")
def 取总览():
    return 目录.总览()


@路由.get("/台参")
def 取台参():
    conn = 连接()
    try:
        return {r["键"]: r["值"] for r in conn.execute("SELECT 键, 值 FROM 台参")}
    finally:
        conn.close()


@路由.get("/账户")
def 列账户():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 账户 ORDER BY 账户键")]
    finally:
        conn.close()


@路由.get("/流水")
def 列流水(营业日: str = "", 账户键: str = ""):
    conn = 连接()
    try:
        sql = "SELECT * FROM 变动流水 WHERE 1=1"
        args: list = []
        if 营业日:
            sql += " AND 营业日=?"
            args.append(营业日)
        if 账户键:
            sql += " AND 账户键=?"
            args.append(账户键)
        sql += " ORDER BY 营业日 DESC, 发生时 DESC, 序号 ASC LIMIT 300"
        out = []
        for r in conn.execute(sql, args):
            d = dict(r)
            # 序号轨字段的响应别名，兼容不同命名的调用方。
            d["流水序号"] = d.get("序号")
            out.append(d)
        return out
    finally:
        conn.close()


@路由.get("/快照")
def 列快照(营业日: str = "", 账户键: str = "", 状态: str = "有效", 含旁置: bool = False):
    conn = 连接()
    try:
        sql = "SELECT * FROM 周期快照 WHERE 1=1"
        args: list = []
        if 营业日:
            sql += " AND 营业日=?"
            args.append(营业日)
        if 账户键:
            sql += " AND 账户键=?"
            args.append(账户键)
        if 状态 == "全部":
            pass
        elif 含旁置 and 状态 == "有效":
            sql += " AND 状态 IN ('有效','旁置')"
        elif 状态:
            sql += " AND 状态=?"
            args.append(状态)
        sql += " ORDER BY 营业日 DESC, 账户键 LIMIT 300"
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


@路由.get("/差额")
def 列差额(回放批次编号: str = ""):
    conn = 连接()
    try:
        if 回放批次编号:
            rows = conn.execute(
                "SELECT * FROM 差额行 WHERE 回放批次编号=? ORDER BY 编号 DESC",
                (回放批次编号,),
            )
        else:
            rows = conn.execute("SELECT * FROM 差额行 ORDER BY 编号 DESC LIMIT 200")
        return [dict(r) for r in rows]
    finally:
        conn.close()


@路由.get("/断档")
def 列断档():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 断档记录 ORDER BY 编号 DESC LIMIT 200")]
    finally:
        conn.close()


@路由.get("/跳变")
def 列跳变():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 跳变记录 ORDER BY 编号 DESC LIMIT 200")]
    finally:
        conn.close()


@路由.get("/旁置")
def 列旁置():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 旁置簿 ORDER BY 编号 DESC LIMIT 100")]
    finally:
        conn.close()


@路由.get("/旁置日终")
@路由.get("/seq-gap/side-mirrors")
def 列旁置日终(账户键: str = "", 营业日: str = "", 状态: str = ""):
    """旁置日终镜实体（序缺口专用）。默认返回旁置/已晋升全部投影，新行在前。"""
    conn = 连接()
    try:
        sql = "SELECT * FROM 旁置日终镜 WHERE 1=1"
        args: list = []
        if 账户键:
            sql += " AND 账户键=?"
            args.append(账户键)
        if 营业日:
            sql += " AND 营业日=?"
            args.append(营业日)
        if 状态:
            sql += " AND 状态=?"
            args.append(状态)
        sql += " ORDER BY 时刻 DESC, 快照键 DESC"
        rows = []
        for r in conn.execute(sql, args):
            d = dict(r)
            try:
                d["缺口区间"] = json.loads(d.get("缺口区间") or "[]")
            except Exception:
                pass
            rows.append(d)
        return rows
    finally:
        conn.close()


@路由.get("/序缺口")
def 列序缺口(状态: str = ""):
    conn = 连接()
    try:
        sql = "SELECT * FROM 序缺口登记 WHERE 1=1"
        args: list = []
        if 状态:
            sql += " AND 状态=?"
            args.append(状态)
        sql += " ORDER BY 编号 DESC LIMIT 200"
        out = []
        for r in conn.execute(sql, args):
            d = dict(r)
            for k in ("缺口区间", "重号"):
                try:
                    d[k] = json.loads(d.get(k) or "[]")
                except Exception:
                    pass
            out.append(d)
        return out
    finally:
        conn.close()


def _核证响应(账户键: str, 营业日: str):
    try:
        if not 账户键:
            conn = 连接()
            try:
                户s = [r["账户键"] for r in conn.execute("SELECT 账户键 FROM 账户 ORDER BY 账户键")]
                参 = {r["键"]: r["值"] for r in conn.execute("SELECT 键, 值 FROM 台参")}
            finally:
                conn.close()
            return {
                "口径": 序闸.当前口径(参),
                "明细": [序闸.核证(账户键=a, 营业日=营业日, 参=参) for a in 户s],
            }
        return 序闸.核证(账户键=账户键, 营业日=营业日)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@路由.get("/序缺口核证")
@路由.get("/序缺口/核证")
@路由.get("/核证序缺口")
@路由.get("/seq-gap/verify")
def 取核证(账户键: str = "", 营业日: str = ""):
    return _核证响应(账户键, 营业日)


@路由.post("/序缺口核证")
@路由.post("/序缺口/核证")
def _post核证(体: 核证请求):
    return _核证响应(体.账户键, 体.营业日)


@路由.get("/序缺口口径")
def 取口径():
    return {"口径": 序闸.当前口径(), "可选": [序闸.口径_旁置, 序闸.口径_阻塞]}


@路由.post("/序缺口口径")
def 设口径(体: 口径请求):
    规范 = 序闸.规范口径(体.口径)
    conn = 连接()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO 台参(键, 值) VALUES ('序缺口口径', ?) "
            "ON CONFLICT(键) DO UPDATE SET 值=excluded.值",
            (规范,),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"口径": 规范, "提示": "全局口径已切换；既有镜状态不被追溯改写"}


@路由.post("/晋升")
@路由.post("/旁置晋升")
@路由.post("/序缺口晋升")
@路由.post("/序缺口/晋升")
@路由.post("/promote")
def 执行晋升(体: 晋升请求):
    try:
        return 序闸.晋升旁置(体.账户键, 体.营业日, 体.批次编号)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@路由.post("/补序装载")
@路由.post("/序缺口/补序")
def 执行补序(体: 装载请求):
    try:
        报告 = 装载.装载流水(体.流水, 体.批次编号)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    受影响 = sorted(
        {str(x.get("账户键") or "").strip() for x in 体.流水 if str(x.get("账户键") or "").strip()}
    )
    报告["核证"] = [序闸.核证(账户键=a) for a in 受影响]
    return 报告


def _列批(表: str):
    conn = 连接()
    try:
        out = []
        for r in conn.execute(f"SELECT * FROM {表} ORDER BY 时刻 DESC LIMIT 40"):
            d = dict(r)
            try:
                d["报告"] = json.loads(d.get("报告") or "{}")
            except Exception:
                pass
            out.append(d)
        return out
    finally:
        conn.close()


@路由.get("/装载批次")
def 列装载批():
    return _列批("装载批次")


@路由.get("/抽取批次")
def 列抽取批():
    return _列批("抽取批次")


@路由.get("/回放批次")
def 列回放批():
    return _列批("回放批次")


@路由.get("/夹具")
def 列夹具():
    if not 夹具目录.exists():
        return []
    return sorted(p.name for p in 夹具目录.glob("*.json"))


@路由.post("/装载")
def 执行装载(体: 装载请求):
    try:
        return 装载.装载流水(体.流水, 体.批次编号)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


class 夹具请求(BaseModel):
    名: str


@路由.post("/装载夹具/{name}")
def 装载夹具路径(name: str):
    return _装载夹具文件(name)


@路由.post("/装载夹具")
def 装载夹具体(体: 夹具请求):
    return _装载夹具文件(体.名)


def _装载夹具文件(名: str):
    path = 夹具目录 / 名
    if not path.exists():
        raise HTTPException(404, f"夹具不存在: {名}")
    data = json.loads(path.read_text(encoding="utf-8"))
    流水 = data.get("流水") or data.get("事件") or []
    return 装载.装载流水(流水, str(data.get("批次编号") or ""))


@路由.post("/抽取")
def 执行抽取(体: 营业日请求):
    try:
        return 抽取.日终抽取(体.营业日, 体.批次编号)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@路由.post("/回放")
def 执行回放(体: 营业日请求):
    try:
        return 回放.回放核对(体.营业日, 体.批次编号)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@路由.post("/重置业务库")
def 重置():
    """开发冒烟用：清业务表并保留账户与台参。"""
    conn = 连接()
    try:
        for t in (
            "变动流水",
            "抽取批次",
            "周期快照",
            "回放批次",
            "差额行",
            "断档记录",
            "跳变记录",
            "旁置簿",
            "装载批次",
            "序缺口登记",
            "旁置日终镜",
        ):
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
        return {"完成": True, **目录.总览()}
    finally:
        conn.close()
