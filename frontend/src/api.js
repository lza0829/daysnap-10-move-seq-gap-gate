async function 请求(path, opts = {}) {
  const r = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  const text = await r.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!r.ok) {
    const msg = (data && data.detail) || text || r.statusText;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

const qs = (o = {}) => {
  const p = new URLSearchParams();
  Object.entries(o).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") p.append(k, v);
  });
  const s = p.toString();
  return s ? `?${s}` : "";
};

export const api = {
  健康: () => 请求("/健康"),
  总览: () => 请求("/总览"),
  台参: () => 请求("/台参"),
  账户: () => 请求("/账户"),
  流水: (q = "") => 请求(`/流水${q}`),
  快照: (q = "") => 请求(`/快照${q}`),
  差额: (q = "") => 请求(`/差额${q}`),
  断档: () => 请求("/断档"),
  跳变: () => 请求("/跳变"),
  旁置: () => 请求("/旁置"),
  旁置日终: (o = {}) => 请求(`/旁置日终${qs(o)}`),
  序缺口列表: (o = {}) => 请求(`/序缺口${qs(o)}`),
  核证序缺口: (账户键, 营业日) => 请求(`/序缺口核证${qs({ 账户键, 营业日 })}`),
  口径: () => 请求("/序缺口口径"),
  设口径: (口径) => 请求("/序缺口口径", { method: "POST", body: JSON.stringify({ 口径 }) }),
  晋升: (账户键, 营业日) =>
    请求("/晋升", { method: "POST", body: JSON.stringify({ 账户键, 营业日 }) }),
  补序装载: (流水, 批次编号 = "") =>
    请求("/补序装载", { method: "POST", body: JSON.stringify({ 流水, 批次编号 }) }),
  夹具: () => 请求("/夹具"),
  装载批次: () => 请求("/装载批次"),
  抽取批次: () => 请求("/抽取批次"),
  回放批次: () => 请求("/回放批次"),
  装载夹具: (名) => 请求("/装载夹具", { method: "POST", body: JSON.stringify({ 名 }) }),
  抽取: (营业日) => 请求("/抽取", { method: "POST", body: JSON.stringify({ 营业日 }) }),
  回放: (营业日) => 请求("/回放", { method: "POST", body: JSON.stringify({ 营业日 }) }),
  重置: () => 请求("/重置业务库", { method: "POST", body: "{}" }),
};
