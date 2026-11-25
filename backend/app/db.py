import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

数据目录 = Path(os.environ.get("数据目录", Path(__file__).resolve().parent.parent / "data"))
夹具目录 = Path(os.environ.get("夹具目录", Path(__file__).resolve().parent.parent.parent / "fixtures"))
库路径 = 数据目录 / "日镜账.db"

_初始化锁 = threading.RLock()
_已就绪路径: str | None = None


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


建表 = """
CREATE TABLE IF NOT EXISTS 台参 (
  键 TEXT PRIMARY KEY,
  值 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 账户 (
  账户键 TEXT PRIMARY KEY,
  户名 TEXT NOT NULL,
  币种 TEXT NOT NULL DEFAULT 'CNY',
  开户营业日 TEXT NOT NULL,
  状态 TEXT NOT NULL DEFAULT '正常'
);
CREATE TABLE IF NOT EXISTS 变动流水 (
  流水号 TEXT PRIMARY KEY,
  账户键 TEXT NOT NULL,
  营业日 TEXT NOT NULL,
  发生时 TEXT NOT NULL,
  变动额 INTEGER NOT NULL,
  摘要 TEXT NOT NULL DEFAULT '',
  批次编号 TEXT NOT NULL DEFAULT '',
  命运 TEXT NOT NULL DEFAULT '已入账',
  序号 INTEGER
);
CREATE INDEX IF NOT EXISTS idx_流水_户日 ON 变动流水(账户键, 营业日);
CREATE INDEX IF NOT EXISTS idx_流水_户序号 ON 变动流水(账户键, 序号);
CREATE TABLE IF NOT EXISTS 抽取批次 (
  编号 TEXT PRIMARY KEY,
  营业日 TEXT NOT NULL,
  时刻 TEXT NOT NULL,
  报告 TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS 周期快照 (
  快照键 TEXT PRIMARY KEY,
  账户键 TEXT NOT NULL,
  营业日 TEXT NOT NULL,
  余额 INTEGER NOT NULL,
  抽取批次编号 TEXT NOT NULL,
  来源 TEXT NOT NULL DEFAULT '日终抽取',
  状态 TEXT NOT NULL DEFAULT '有效',
  UNIQUE(账户键, 营业日)
);
CREATE TABLE IF NOT EXISTS 回放批次 (
  编号 TEXT PRIMARY KEY,
  营业日 TEXT NOT NULL,
  时刻 TEXT NOT NULL,
  报告 TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS 差额行 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  回放批次编号 TEXT NOT NULL,
  账户键 TEXT NOT NULL,
  营业日 TEXT NOT NULL,
  快照余额 INTEGER,
  回放余额 INTEGER,
  差额 INTEGER NOT NULL,
  原因 TEXT NOT NULL,
  时刻 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 断档记录 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  账户键 TEXT NOT NULL,
  缺营业日 TEXT NOT NULL,
  检出批次编号 TEXT NOT NULL,
  处置 TEXT NOT NULL DEFAULT '待处理',
  时刻 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 跳变记录 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  账户键 TEXT NOT NULL,
  营业日 TEXT NOT NULL,
  前日余额 INTEGER,
  当日余额 INTEGER,
  流水净额 INTEGER,
  偏离 INTEGER NOT NULL,
  检出批次编号 TEXT NOT NULL,
  时刻 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 旁置簿 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  原因 TEXT NOT NULL,
  账户键 TEXT NOT NULL DEFAULT '',
  营业日 TEXT NOT NULL DEFAULT '',
  载荷 TEXT NOT NULL,
  时刻 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 装载批次 (
  编号 TEXT PRIMARY KEY,
  时刻 TEXT NOT NULL,
  报告 TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS 序缺口登记 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  账户键 TEXT NOT NULL,
  营业日 TEXT NOT NULL DEFAULT '',
  缺口区间 TEXT NOT NULL DEFAULT '[]',
  缺口数 INTEGER NOT NULL DEFAULT 0,
  重号 TEXT NOT NULL DEFAULT '[]',
  状态 TEXT NOT NULL DEFAULT '未解除',
  口径 TEXT NOT NULL DEFAULT '旁置日终镜',
  旁置快照键 TEXT NOT NULL DEFAULT '',
  检出批次编号 TEXT NOT NULL DEFAULT '',
  时刻 TEXT NOT NULL,
  更新时刻 TEXT NOT NULL DEFAULT '',
  解除时刻 TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_序缺口_户 ON 序缺口登记(账户键, 状态);
CREATE TABLE IF NOT EXISTS 旁置日终镜 (
  快照键 TEXT PRIMARY KEY,
  账户键 TEXT NOT NULL,
  营业日 TEXT NOT NULL,
  余额 INTEGER NOT NULL,
  开端余额 INTEGER NOT NULL DEFAULT 0,
  流水净额 INTEGER NOT NULL DEFAULT 0,
  缺口区间 TEXT NOT NULL DEFAULT '[]',
  状态 TEXT NOT NULL DEFAULT '旁置',
  抽取批次编号 TEXT NOT NULL DEFAULT '',
  晋升批次编号 TEXT NOT NULL DEFAULT '',
  时刻 TEXT NOT NULL,
  晋升时刻 TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_旁置日终_户日 ON 旁置日终镜(账户键, 营业日, 状态);
CREATE VIEW IF NOT EXISTS 序缺口 AS SELECT * FROM 序缺口登记;
CREATE VIEW IF NOT EXISTS 流水序缺口 AS SELECT * FROM 序缺口登记;
CREATE VIEW IF NOT EXISTS 旁置日终 AS SELECT * FROM 旁置日终镜;
"""

空桩模块 = [
    "开户首日无前日",
    "同日重复抽取幂等",
    "流水迟到补抽",
    "销户终镜",
    "负余额闸",
    "币种隔离",
    "半截抽取回滚",
    "快照封印写闸",
    "回放权威择定",
    "断档补齐",
    "断档旁置",
    "跳变阈值",
    "账户分片抽取",
    "抽取时钟漂移",
    "流水序缺口",
    "并户继承镜",
    "子户汇总镜",
    "假期跳日日历",
    "差额分桶",
    "三日连环守恒",
    "抽取重试预算",
    "跨日切点策略",
]


def 原始连接() -> sqlite3.Connection:
    数据目录.mkdir(parents=True, exist_ok=True)
    # isolation_level=None => 显式事务（BEGIN IMMEDIATE ... COMMIT），
    # 让“核缺口 + 写镜”在同一把写锁内串行，补序与抽取交错时失败闭。
    c = sqlite3.connect(str(库路径), timeout=20.0, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("PRAGMA busy_timeout = 20000")
    return c


def 开始立即事务(conn: sqlite3.Connection, 最长等待: float = 25.0) -> None:
    """获取写锁并开启立即事务；遇到锁忙时退避重试，保证交错不写出残缺正式镜。"""
    截止 = time.monotonic() + 最长等待
    while True:
        try:
            conn.execute("BEGIN IMMEDIATE")
            return
        except sqlite3.OperationalError as e:
            if "locked" not in str(e).lower() and "busy" not in str(e).lower():
                raise
            if time.monotonic() >= 截止:
                raise
            time.sleep(0.01)


def _迁移(conn: sqlite3.Connection) -> None:
    列 = {r["name"] for r in conn.execute("PRAGMA table_info(变动流水)").fetchall()}
    if "序号" not in 列:
        conn.execute("ALTER TABLE 变动流水 ADD COLUMN 序号 INTEGER")


def 初始化库() -> None:
    global _已就绪路径
    with _初始化锁:
        conn = 原始连接()
        try:
            conn.executescript(建表)
            _迁移(conn)
            if conn.execute("SELECT COUNT(*) AS c FROM 台参").fetchone()["c"] == 0:
                for k, v in {
                    "站名": "日镜账",
                    "骨架": "日终余额抽取→周期快照落行→变动流水回放核对→断档跳变检出→快照与回放差额清单",
                    "跳变阈值分": "0",
                    "断档处置": "记断档并继续",
                    "缺前日策略": "以零为开端",
                    "重复抽取": "盖写同日快照",
                }.items():
                    conn.execute("INSERT INTO 台参(键, 值) VALUES (?, ?)", (k, v))
            if conn.execute("SELECT COUNT(*) AS c FROM 账户").fetchone()["c"] == 0:
                for 键, 名, 日 in [
                    ("户甲", "甲收单户", "2026-11-01"),
                    ("户乙", "乙结算户", "2026-11-01"),
                    ("户丙", "丙备用户", "2026-11-05"),
                ]:
                    conn.execute(
                        "INSERT INTO 账户(账户键, 户名, 币种, 开户营业日, 状态) VALUES (?,?,?,?,?)",
                        (键, 名, "CNY", 日, "正常"),
                    )
            conn.commit()
        finally:
            conn.close()
        _已就绪路径 = str(库路径)


def 连接() -> sqlite3.Connection:
    global _已就绪路径
    目标 = str(库路径)
    if _已就绪路径 != 目标:
        with _初始化锁:
            if _已就绪路径 != 目标:
                初始化库()
    return 原始连接()
