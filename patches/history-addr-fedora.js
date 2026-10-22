
/* ---- Fedora patch: 原生 history addon 在本机写库失败（SdpcHistory 一直为空），
   导致登录页服务器地址每次都要手输。这里让历史地址回落到：
     1) addr.conf   —— 最近一次登录的地址（客户端自己维护）
     2) addr.list   —— 手工维护的多条地址，一行一个，可写注释
   ---- */
(function () {
  const fs = require("fs");
  const path = require("path");
  const Common = require("./common");
  const MAX_ADDR = 10;

  function readLines(p) {
    try {
      return fs.readFileSync(p, "utf8").split("\n")
        .map(function (s) { return s.trim(); })
        .filter(function (s) { return s && s.charAt(0) !== "#"; });
    } catch (e) { return []; }
  }

  function fallbackList() {
    const out = [];
    function push(u) {
      if (!Common.isURLlegal(u)) return;
      const key = u.toLowerCase().replace(/\/+$/, "");
      if (out.some(function (x) { return x.addr.toLowerCase().replace(/\/+$/, "") === key; })) return;
      out.push({ addr: u, serviceType: Common.SERVICE_VERSION_NONE, simplifyWorkspace: false });
    }
    readLines(Common.ADDR_CONF_PATH).slice(0, 1).forEach(push);
    readLines(path.join(path.dirname(Common.ADDR_CONF_PATH), "addr.list")).forEach(push);
    return out.slice(0, MAX_ADDR);
  }

  const origQueryHistory = module.exports._queryHistory.bind(module.exports);
  module.exports._queryHistory = async function () {
    let list = [];
    try { list = await origQueryHistory(); } catch (e) {}
    if (!list || list.length === 0) list = fallbackList();
    return list;
  };
})();
